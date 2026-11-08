import time

import pytest
from fastapi.testclient import TestClient

from tests.fakes import RATE, FakeLLM, FakeTTS, FakeWatermarker, tone
from voiceover_studio.api import create_app
from voiceover_studio.core.audio import write_wav
from voiceover_studio.core.config import load_config
from voiceover_studio.providers.base import ASRProvider
from voiceover_studio.providers.storage import LocalStorage
from voiceover_studio.services import Services
from voiceover_studio.settings import Settings

CFG = load_config(environ={})


class FakeASR(ASRProvider):
    name = "fake_asr"

    def __init__(self, heard: str):
        self.heard = heard

    def transcribe(self, audio_path, language=None) -> str:
        return self.heard


def no_conversion(data: bytes, rate: int) -> bytes:
    raise AssertionError("WAV input at the right rate must not need ffmpeg")


def make_client(
    tmp_path,
    heard: str = CFG.voice_sample.consent_sentence,
    llm_reply: str = "Hello there. Welcome.",
    plugins: str = "fit_to_length",
    languages: tuple[str, ...] = ("en",),
):
    services = Services(
        Settings(plugins=plugins),
        CFG,
        tts=FakeTTS(languages=languages),
        llm=FakeLLM(llm_reply),
        asr=FakeASR(heard),
        storage=LocalStorage(root=str(tmp_path / "store")),
        watermarker_factory=FakeWatermarker,
        convert_audio=no_conversion,
        workdir=tmp_path / "work",
    )
    (tmp_path / "work").mkdir()
    return TestClient(create_app(services))


def sample_wav(tmp_path, seconds: float = 8.0) -> bytes:
    rng = __import__("numpy").random.default_rng(1)
    clip = tone(seconds)
    samples = clip.samples * (0.6 + 0.4 * (rng.random(len(clip.samples)) > 0.5))
    path = write_wav(type(clip)(samples.astype("float32"), RATE), tmp_path / "upload.wav")
    return path.read_bytes()


def test_info_lists_consent_sentence_languages_and_plugins(tmp_path):
    info = make_client(tmp_path).get("/api/info").json()
    assert info["consent_sentence"] == CFG.voice_sample.consent_sentence
    assert info["languages"] == ["en"] and info["voice_leaves_account"] is False
    assert info["plugins"][0]["name"] == "fit_to_length"


def test_full_flow_voice_script_plugin_render_download(tmp_path):
    client = make_client(tmp_path)

    r = client.post("/api/voices", files={"file": ("sample.wav", sample_wav(tmp_path), "audio/wav")})
    assert r.status_code == 201, r.text
    voice_id = r.json()["voice_id"]
    assert client.get("/api/voices").json()[0]["voice_id"] == voice_id

    r = client.post(
        "/api/scripts", json={"description": "An intro to our new lab series", "target_seconds": 20}
    )
    assert r.status_code == 200 and r.json()["script"] == "Hello there. Welcome."

    r = client.post(
        "/api/plugins/fit_to_length", json={"script": "Hello there. Welcome.", "target_seconds": None}
    )
    assert "no target" in r.json()["notes"][0]

    r = client.post("/api/renders", json={"voice_id": voice_id, "script": "Hello there. Welcome."})
    assert r.status_code == 202
    job_id = r.json()["id"]
    for _ in range(100):
        job = client.get(f"/api/renders/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job["error"]
    assert job["progress"]["done"] == job["progress"]["total"] == 2

    output_id = job["result"]["output_id"]
    wav = client.get(f"/api/outputs/{output_id}/voiceover.wav")
    assert wav.status_code == 200 and wav.content[:4] == b"RIFF"
    assert "-->" in client.get(f"/api/outputs/{output_id}/voiceover.srt").text
    assert client.get(f"/api/outputs/{output_id}/secrets.txt").status_code == 404

    assert client.delete(f"/api/voices/{voice_id}").status_code == 204
    assert client.get("/api/voices").json() == []


def test_translate_plugin_offers_the_voice_models_languages_and_switches_language(tmp_path):
    client = make_client(
        tmp_path, llm_reply="Hola. Bienvenidos.", plugins="fit_to_length,translate", languages=("en", "es")
    )
    translate = client.get("/api/info").json()["plugins"][1]
    assert translate["settings_schema"]["properties"]["target_language"]["enum"] == ["en", "es"]

    r = client.post(
        "/api/plugins/translate",
        json={"script": "Hello there. Welcome.", "settings": {"target_language": "es"}},
    )
    assert (
        r.status_code == 200 and r.json()["language"] == "es" and r.json()["script"] == "Hola. Bienvenidos."
    )
    r = client.post(
        "/api/plugins/translate", json={"script": "Hello.", "settings": {"target_language": "hi"}}
    )
    assert r.status_code == 422 and "can't speak" in r.json()["detail"]["message"]


def test_wrong_sentence_is_rejected_as_no_consent(tmp_path):
    client = make_client(tmp_path, heard="hi this is my podcast")
    r = client.post("/api/voices", files={"file": ("sample.wav", sample_wav(tmp_path), "audio/wav")})
    assert r.status_code == 422 and "consent sentence" in r.json()["detail"]["message"]


def test_too_short_sample_returns_problems_to_fix(tmp_path):
    client = make_client(tmp_path)
    r = client.post("/api/voices", files={"file": ("sample.wav", sample_wav(tmp_path, 2.0), "audio/wav")})
    assert r.status_code == 422 and any("Too short" in p for p in r.json()["detail"]["problems"])


def test_impersonation_request_is_refused(tmp_path):
    r = make_client(tmp_path).post(
        "/api/scripts",
        json={"description": "Announce it in the voice of a famous actor", "target_seconds": 20},
    )
    assert r.status_code == 422 and "can't help" in r.json()["detail"]["message"]


@pytest.mark.parametrize("path", ["/api/renders/../../etc", "/api/outputs/zzz/voiceover.wav"])
def test_ids_are_validated(tmp_path, path):
    assert make_client(tmp_path).get(path).status_code in (404, 422)


def test_render_with_unknown_voice_is_404(tmp_path):
    r = make_client(tmp_path).post(
        "/api/renders", json={"voice_id": "00000000-0000-0000-0000-000000000000", "script": "Hi."}
    )
    assert r.status_code == 404
