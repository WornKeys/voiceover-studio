"""Local speech-to-text for the consent check: faster-whisper (MIT), on GPU when available.

The audio is decoded here (our samples are always 16-bit WAV) and handed to Whisper as samples at 16 kHz.
That avoids faster-whisper's file decoding via PyAV, which broke with newer PyAV releases
(`open() got an unexpected keyword argument 'metadata_errors'`, found in the CPU dry run).
"""

from __future__ import annotations

from math import gcd
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from voiceover_studio.core.audio import read_wav
from voiceover_studio.providers.base import ASRProvider
from voiceover_studio.providers.registry import register

WHISPER_RATE = 16000


def to_whisper_samples(audio_path: Path) -> np.ndarray:
    clip = read_wav(audio_path)
    samples = np.asarray(clip.samples, dtype=np.float32)
    if clip.sample_rate != WHISPER_RATE:
        g = gcd(WHISPER_RATE, clip.sample_rate)
        samples = resample_poly(samples, WHISPER_RATE // g, clip.sample_rate // g).astype(np.float32)
    return samples


@register("asr", "faster_whisper")
class FasterWhisperASR(ASRProvider):
    def __init__(
        self,
        model: str = "small",
        device: str = "cuda",
        compute_type: str = "float16",
        revision: str | None = None,  # a Hugging Face commit; None = the latest
    ):
        self.model_id = model
        self.revision = revision
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_id, device=self.device, compute_type=self.compute_type, revision=self.revision
            )
        return self._model

    def transcribe(self, audio_path: Path, language: str | None = None) -> str:
        segments, _info = self._load().transcribe(
            to_whisper_samples(audio_path), language=language, beam_size=5
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
