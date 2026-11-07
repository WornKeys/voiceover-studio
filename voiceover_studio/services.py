"""What the app does, independent of how it is called (HTTP API, UI, CLI).

Providers are created on first use, so the app starts fast and a hosted provider never loads GPU libraries.
"""

from __future__ import annotations

import io
import json
import tempfile
import wave
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from voiceover_studio.core.audio import read_wav, write_wav
from voiceover_studio.core.config import AppConfig
from voiceover_studio.core.consent import check_sample, record_consent
from voiceover_studio.core.convert import to_wav_pcm16
from voiceover_studio.core.render import render_voiceover
from voiceover_studio.core.script import ScriptDraft, ScriptRequest, draft_from_text, generate_script
from voiceover_studio.core.watermark import AudioSealWatermarker, Watermarker
from voiceover_studio.jobs import Job, JobManager
from voiceover_studio.plugins import AVAILABLE, PluginContext, enabled_plugins
from voiceover_studio.providers.base import (
    ASRProvider,
    LLMProvider,
    StorageProvider,
    TTSProvider,
    VoiceReference,
)
from voiceover_studio.settings import Settings, build_asr, build_llm, build_storage, build_tts

OUTPUT_FILES = ("voiceover.wav", "voiceover.srt", "provenance.json")


class SampleRejectedError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__(" ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class VoiceInfo:
    voice_id: str
    seconds: float
    consent_score: float
    created_at: str
    warnings: list[str]


def _is_pcm16_wav(data: bytes, sample_rate: int) -> bool:
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return False
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getsampwidth() == 2 and w.getnchannels() == 1 and w.getframerate() == sample_rate
    except wave.Error:
        return False


class Services:
    def __init__(
        self,
        settings: Settings,
        cfg: AppConfig,
        *,
        tts: TTSProvider | None = None,
        llm: LLMProvider | None = None,
        asr: ASRProvider | None = None,
        storage: StorageProvider | None = None,
        watermarker_factory: Callable[[], Watermarker] | None = None,
        convert_audio: Callable[[bytes, int], bytes] = to_wav_pcm16,
        workdir: Path | None = None,
    ):
        self.settings = settings
        self.cfg = cfg
        self._tts, self._llm, self._asr, self._storage = tts, llm, asr, storage
        self._watermarker_factory = watermarker_factory or (
            lambda: AudioSealWatermarker(device="cuda" if settings.device == "cuda" else "cpu")
        )
        self._convert = convert_audio
        self.workdir = workdir or Path(tempfile.mkdtemp(prefix="voiceover-"))
        self.jobs = JobManager()
        self.plugins = {p.name: p for p in enabled_plugins(settings.plugins)}

    # --- providers (created on first use) -----------------------------------------------
    @cached_property
    def tts(self) -> TTSProvider:
        return self._tts or build_tts(self.settings)

    @cached_property
    def llm(self) -> LLMProvider:
        return self._llm or build_llm(self.settings)

    @cached_property
    def asr(self) -> ASRProvider:
        return self._asr or build_asr(self.settings)

    @cached_property
    def storage(self) -> StorageProvider:
        return self._storage or build_storage(self.settings)

    @cached_property
    def watermarker(self) -> Watermarker:
        return self._watermarker_factory()

    # --- app info ---------------------------------------------------------------------
    def info(self) -> dict[str, Any]:
        caps = self.tts.capabilities()
        return {
            "consent_sentence": self.cfg.voice_sample.consent_sentence,
            "sample_seconds": {
                "min": self.cfg.voice_sample.min_seconds,
                "max": self.cfg.voice_sample.max_seconds,
            },
            "languages": list(caps.languages),
            "voice_leaves_account": not caps.runs_locally,
            "words_per_minute": self.cfg.script.words_per_minute,
            "max_target_seconds": self.cfg.script.max_target_seconds,
            "plugins": [p.manifest() for p in self.plugins.values()],
            "compute_profile": self.settings.resolved_compute_profile,
        }

    # --- voices -----------------------------------------------------------------------
    def add_voice(self, data: bytes) -> VoiceInfo:
        rate = self.cfg.voice_sample.sample_rate
        wav_bytes = data if _is_pcm16_wav(data, rate) else self._convert(data, rate)
        raw_path = self.workdir / "incoming.wav"
        raw_path.write_bytes(wav_bytes)

        check = check_sample(read_wav(raw_path), self.cfg.voice_sample)
        if not check.ok:
            raise SampleRejectedError(check.problems)
        trimmed_path = write_wav(check.clip, self.workdir / "incoming-trimmed.wav")

        transcript = self.asr.transcribe(trimmed_path, "en")
        record = record_consent(
            self.cfg.voice_sample.consent_sentence,
            transcript,
            trimmed_path.read_bytes(),
            self.cfg.voice_sample.consent_match_threshold,
        )
        prefix = f"voices/{record.consent_id}"
        self.storage.put(f"{prefix}/sample.wav", trimmed_path.read_bytes(), {"consent_id": record.consent_id})
        self.storage.put(f"{prefix}/consent.json", json.dumps(asdict(record), indent=2).encode("utf-8"))
        return VoiceInfo(record.consent_id, round(check.clip.seconds, 1), record.score, record.created_at,
                         check.warnings)  # fmt: skip

    def list_voices(self) -> list[dict[str, Any]]:
        voices = []
        for obj in self.storage.list("voices/"):
            if obj.key.endswith("/consent.json"):
                record = json.loads(self.storage.get(obj.key))
                voices.append({"voice_id": record["consent_id"], "created_at": record["created_at"]})
        return sorted(voices, key=lambda v: v["created_at"], reverse=True)

    def delete_voice(self, voice_id: str) -> None:
        for name in ("sample.wav", "consent.json"):
            self.storage.delete(f"voices/{voice_id}/{name}")
        (self.workdir / "voices" / f"{voice_id}.wav").unlink(missing_ok=True)

    def voice_reference(self, voice_id: str) -> VoiceReference:
        record = json.loads(self.storage.get(f"voices/{voice_id}/consent.json"))
        local = self.workdir / "voices" / f"{voice_id}.wav"
        if not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(self.storage.get(f"voices/{voice_id}/sample.wav"))
        # The model gets the sentence the user was asked to read: the exact transcript of the clip.
        return VoiceReference(local, record["sentence"], consent_id=record["consent_id"])

    # --- scripts ----------------------------------------------------------------------
    def draft_script(self, request: ScriptRequest) -> ScriptDraft:
        if request.target_seconds > self.cfg.script.max_target_seconds:
            raise ValueError(f"Target length is limited to {self.cfg.script.max_target_seconds} seconds.")
        return generate_script(
            self.llm,
            request,
            words_per_minute=self.cfg.script.words_per_minute,
            temperature=self.cfg.script.temperature,
        )

    def estimate(self, text: str) -> ScriptDraft:
        return draft_from_text(text, self.cfg.script.words_per_minute)

    def run_plugin(
        self, name: str, script: str, language: str, target_seconds: float | None, settings: dict[str, Any]
    ) -> dict[str, Any]:
        if name not in self.plugins:
            raise LookupError(f"Plugin '{name}' is not enabled. Enabled: {', '.join(self.plugins) or 'none'}")
        plugin_cls = AVAILABLE[name]
        ctx = PluginContext(
            script=script,
            language=language,
            target_seconds=target_seconds,
            words_per_minute=self.cfg.script.words_per_minute,
            llm=self.llm,
            tts=self.tts,
        )
        ctx = plugin_cls().run(ctx, plugin_cls.Settings.model_validate(settings))
        draft = self.estimate(ctx.script)
        return {"script": ctx.script, "notes": ctx.notes, "words": draft.words,
                "estimated_seconds": round(draft.estimated_seconds, 1)}  # fmt: skip

    # --- renders ----------------------------------------------------------------------
    def submit_render(self, voice_id: str, script: str, language: str) -> Job:
        voice = self.voice_reference(voice_id)  # fail fast if the voice doesn't exist

        def work(report) -> dict[str, Any]:
            report(0, 0, "Loading the voice model...")
            out_dir = self.workdir / "renders" / uuid_dir()
            result = render_voiceover(
                script, voice, language, self.tts, self.watermarker, self.cfg, out_dir, report
            )
            key_prefix = f"outputs/{out_dir.name}"
            for name in OUTPUT_FILES:
                self.storage.put(
                    f"{key_prefix}/{name}", (out_dir / name).read_bytes(), {"consent_id": voice.consent_id}
                )
            return {
                "output_id": out_dir.name,
                "seconds": round(result.seconds, 1),
                "files": list(OUTPUT_FILES),
            }

        return self.jobs.submit("render", work)

    def output_file(self, output_id: str, name: str) -> bytes:
        if name not in OUTPUT_FILES:
            raise LookupError(name)
        return self.storage.get(f"outputs/{output_id}/{name}")


def uuid_dir() -> str:
    import uuid

    return uuid.uuid4().hex[:12]
