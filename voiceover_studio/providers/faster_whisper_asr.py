"""Local speech-to-text for the consent check: faster-whisper (MIT), on GPU when available."""

from __future__ import annotations

from pathlib import Path

from voiceover_studio.providers.base import ASRProvider
from voiceover_studio.providers.registry import register


@register("asr", "faster_whisper")
class FasterWhisperASR(ASRProvider):
    def __init__(self, model: str = "small", device: str = "cuda", compute_type: str = "float16"):
        self.model_id = model
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_id, device=self.device, compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio_path: Path, language: str | None = None) -> str:
        segments, _info = self._load().transcribe(str(audio_path), language=language, beam_size=5)
        return " ".join(segment.text.strip() for segment in segments).strip()
