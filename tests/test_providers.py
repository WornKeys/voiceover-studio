import json
import sys
import types
from pathlib import Path

import httpx2 as httpx
import numpy as np
import pytest

from voiceover_studio.core.audio import write_wav
from voiceover_studio.providers import registry
from voiceover_studio.providers.base import AudioClip, ChatMessage, VoiceReference
from voiceover_studio.providers.openai_compat import OpenAICompatLLM, infer_auth, is_local
from voiceover_studio.providers.storage import LocalStorage, S3Storage
from voiceover_studio.settings import (
    PINNED_REVISIONS,
    Settings,
    build_asr,
    build_llm,
    build_storage,
    build_tts,
)

# --- LLM -------------------------------------------------------------------


def _mock_llm(reply: str, seen: list[dict]) -> OpenAICompatLLM:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "body": json.loads(request.content)})
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": reply}}
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatLLM(base_url="http://llm:8000/v1", model="qwen", http_client=client)


def test_llm_sends_chat_request_with_thinking_disabled():
    seen: list[dict] = []
    llm = _mock_llm("Hello there.", seen)
    reply = llm.complete([ChatMessage("user", "hi")], max_tokens=100, temperature=0.5)
    assert reply == "Hello there."
    body = seen[0]["body"]
    assert seen[0]["url"] == "http://llm:8000/v1/chat/completions"
    assert body["model"] == "qwen" and body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert llm.capabilities().runs_locally


def test_llm_auth_and_locality_inference():
    assert infer_auth("http://llm:8000/v1", "") == "none"
    assert infer_auth("https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1", "") == "bedrock"
    assert infer_auth("https://api.example.com/v1", "/voiceover-studio/llm-key") == "ssm"
    assert is_local("http://localhost:8000/v1") and not is_local("https://api.example.com/v1")


# --- Storage ---------------------------------------------------------------


def test_local_storage_roundtrip_and_key_safety(tmp_path):
    store = LocalStorage(root=str(tmp_path))
    store.put("voices/a/sample.wav", b"abc", {"consent_id": "c1"})
    assert store.get("voices/a/sample.wav") == b"abc"
    assert [o.key for o in store.list("voices")] == ["voices/a/sample.wav"]
    store.delete("voices/a/sample.wav")
    assert store.list("voices") == []
    with pytest.raises(ValueError):
        store.put("../escape.txt", b"x")


class FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, Metadata):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        return {"Body": types.SimpleNamespace(read=lambda: self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def get_paginator(self, _name):
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": k, "Size": len(v)} for k, v in objects.items() if k.startswith(Prefix)
                    ]
                }

        return Paginator()


def test_s3_storage_uses_the_bucket_api():
    s3 = S3Storage(bucket="voiceover-studio-test", client=FakeS3())
    s3.put("outputs/1/voiceover.wav", b"RIFF")
    assert s3.get("outputs/1/voiceover.wav") == b"RIFF"
    assert [o.key for o in s3.list("outputs/")] == ["outputs/1/voiceover.wav"]


# --- Local models (stand-in modules, no GPU) --------------------------------


def test_qwen3_tts_maps_language_and_passes_reference_transcript(monkeypatch):
    calls = {}

    class FakeModel:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            calls["load"] = (model_id, kwargs["attn_implementation"])
            calls["dtype"] = kwargs["dtype"]
            return cls()

        def generate_voice_clone(self, **kwargs):
            calls["generate"] = kwargs
            return [np.zeros(2400, dtype=np.float32)], 24000

    def fake_snapshot_download(repo_id, revision=None):  # no 4 GB download in a unit test
        calls["download"] = (repo_id, revision)
        return f"/cache/{repo_id}@{revision}"

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(bfloat16="bf16", float32="f32"))
    monkeypatch.setitem(sys.modules, "qwen_tts", types.SimpleNamespace(Qwen3TTSModel=FakeModel))
    monkeypatch.setitem(
        sys.modules, "huggingface_hub", types.SimpleNamespace(snapshot_download=fake_snapshot_download)
    )
    tts = registry.create("tts", "qwen3_tts", device="cpu", revision="abc123")
    clip = tts.synthesize("Hello.", VoiceReference(Path("v.wav"), "I am recording my own voice.", "c1"), "en")
    assert calls["generate"]["language"] == "English"
    assert calls["generate"]["ref_text"] == "I am recording my own voice."
    # The whole repo is fetched at the pinned commit, then loaded from that folder (model + processor match).
    assert calls["download"] == ("Qwen/Qwen3-TTS-12Hz-1.7B-Base", "abc123")
    assert calls["load"] == ("/cache/Qwen/Qwen3-TTS-12Hz-1.7B-Base@abc123", "sdpa")
    assert calls["dtype"] == "f32"  # CPUs have no fast bfloat16 maths
    registry.create("tts", "qwen3_tts", device="cuda:0").synthesize(
        "Hello.", VoiceReference(Path("v.wav"), "I am recording my own voice.", "c1"), "en"
    )
    assert calls["dtype"] == "bf16"  # on a GPU, half the memory
    assert clip.sample_rate == 24000 and abs(clip.seconds - 0.1) < 1e-6
    with pytest.raises(ValueError, match="doesn't support"):
        tts.synthesize("Namaste.", VoiceReference(Path("v.wav"), "t", "c1"), "hi")


def test_faster_whisper_gets_16k_samples_not_a_file_path(monkeypatch, tmp_path):
    received = {}

    class FakeWhisper:
        def __init__(self, model, device, compute_type, revision=None):
            received["load"] = (model, device, compute_type, revision)

        def transcribe(self, audio, language, beam_size):
            received["audio"] = audio
            return iter(
                [types.SimpleNamespace(text=" I am recording"), types.SimpleNamespace(text=" my voice.")]
            ), {}

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisper))
    wav = write_wav(AudioClip(np.zeros(24000, dtype=np.float32), 24000), tmp_path / "sample.wav")
    asr = registry.create(
        "asr", "faster_whisper", model="small", device="cpu", compute_type="int8", revision="abc123"
    )
    assert asr.transcribe(wav, "en") == "I am recording my voice."
    assert isinstance(received["audio"], np.ndarray) and len(received["audio"]) == 16000  # 1 s at 16 kHz
    assert received["load"] == ("small", "cpu", "int8", "abc123")


# --- Settings ---------------------------------------------------------------


def test_settings_from_env_and_derived_values(tmp_path):
    s = Settings.from_env(
        {
            "LLM_BASE_URL": "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1",
            "LLM_DISABLE_THINKING": "false",
            "STORAGE_PROVIDER": "local",
            "STORAGE_DIR": str(tmp_path),
            "PLUGINS": "fit_to_length",
        }
    )
    assert s.resolved_llm_auth == "bedrock" and s.llm_disable_thinking is False
    assert s.resolved_compute_profile == "gpu"  # the voice model still runs locally
    assert isinstance(build_storage(s), LocalStorage)
    assert build_llm(s).capabilities().runs_locally is False
    assert Settings.from_env({"COMPUTE_PROFILE": "cpu"}).resolved_compute_profile == "cpu"
    assert s.asr_device == "cpu"  # Whisper on the CPU by default: it doesn't need the GPU


def test_registry_lists_builtin_providers():
    assert "qwen3_tts" in registry.available("tts")
    assert {"local", "s3"} <= set(registry.available("storage"))


def test_default_models_load_the_tested_versions():
    s = Settings()
    assert build_tts(s).revision == PINNED_REVISIONS[s.tts_model]
    assert build_asr(s).revision == PINNED_REVISIONS["small"]
    assert PINNED_REVISIONS[s.llm_model]  # vLLM gets it through scripts/toolbox/lib.sh
    # Your own revision wins; another model has no pin, so it loads the latest unless you set one.
    assert build_tts(Settings(tts_model_revision="abc123")).revision == "abc123"
    assert build_tts(Settings(device="cuda")).device == "cuda:0"
    assert build_tts(Settings(device="cpu")).device == "cpu"  # "cpu:0" fails to load
    assert build_asr(Settings(asr_model="medium")).revision is None
    assert build_tts(Settings.from_env({"TTS_MODEL_REVISION": "v2"})).revision == "v2"


def test_llm_pin_is_the_same_in_the_deploy_scripts():
    lib = (Path(__file__).parents[1] / "scripts" / "toolbox" / "lib.sh").read_text(encoding="utf-8")
    llm = Settings().llm_model
    assert f"DEFAULT_LLM_MODEL={llm}" in lib
    assert f"DEFAULT_LLM_REVISION={PINNED_REVISIONS[llm]}" in lib
