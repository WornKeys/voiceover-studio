"""Inaudible watermark on every output, applied by the core whatever TTS provider produced the audio.

The render pipeline requires a Watermarker: there is no setting to turn it off. AudioSeal (Meta, MIT licence
for code and weights) is the implementation; torch and audioseal are only imported when it is created.
"""

from __future__ import annotations

import contextlib
import os
from abc import ABC, abstractmethod

import numpy as np

from voiceover_studio.providers.base import AudioClip

# 16-bit message embedded in every file: "VS" (voiceover-studio).
MESSAGE = 0x5653
# AudioSeal's models work at 16 kHz.
RATE = 16000


class Watermarker(ABC):
    method: str

    @abstractmethod
    def embed(self, clip: AudioClip) -> AudioClip: ...

    @abstractmethod
    def detect(self, clip: AudioClip) -> float:
        """Probability (0..1) that the clip carries the watermark."""


class AudioSealWatermarker(Watermarker):
    method = "audioseal"

    def __init__(self, device: str = "cpu") -> None:
        # AudioSeal 0.2 wraps some layers in torch.compile, which needs a C/C++ compiler at runtime (absent
        # on Windows and in our slim image; found in the CPU dry run). The model is small: compiling gains
        # nothing.
        os.environ.setdefault("NO_TORCH_COMPILE", "1")
        import torch  # noqa: F401  (heavy: imported only when the watermarker is created)
        from audioseal import AudioSeal

        try:
            from audioseal.libs.moshi.utils.compile import no_compile
        except ImportError:  # older AudioSeal without the compile wrappers
            no_compile = contextlib.nullcontext
        self._no_compile = no_compile
        self._device = device
        self._generator = AudioSeal.load_generator("audioseal_wm_16bits").to(device).eval()
        self._detector = AudioSeal.load_detector("audioseal_detector_16bits").to(device).eval()

    def _tensor(self, samples: np.ndarray):
        import torch

        tensor = torch.from_numpy(np.ascontiguousarray(samples, dtype=np.float32))
        return tensor[None, None, :].to(self._device)

    @staticmethod
    def _resample(wav, from_rate: int, to_rate: int):
        import torchaudio.functional as taf

        return wav if from_rate == to_rate else taf.resample(wav, from_rate, to_rate)

    def embed(self, clip: AudioClip) -> AudioClip:
        """Mark the clip at AudioSeal's own rate (16 kHz), then add the mark back at the clip's rate.

        AudioSeal 0.2 doesn't resample: it treats any input as 16 kHz. Marking 24 kHz audio directly gave a
        mark that read back perfectly at 24 kHz but vanished after any resample (found 2026-11-08), and every
        video export resamples. Computing the mark on a 16 kHz copy and resampling only the mark keeps the
        voice at full quality and lets the mark survive an export.
        """
        import torch

        wav = self._tensor(clip.samples)
        bits = [(MESSAGE >> (15 - i)) & 1 for i in range(16)]
        message = torch.tensor([bits], device=self._device)
        with torch.no_grad(), self._no_compile():
            wav16 = self._resample(wav, clip.sample_rate, RATE)
            mark16 = self._generator.get_watermark(wav16, message=message)
        mark = self._resample(mark16, RATE, clip.sample_rate)[..., : wav.shape[-1]]
        out = (wav + mark).squeeze().cpu().numpy().astype(np.float32)
        return AudioClip(np.clip(out, -1.0, 1.0), clip.sample_rate)

    def detect(self, clip: AudioClip) -> float:
        return self.inspect(clip)[0]

    def inspect(self, clip: AudioClip) -> tuple[float, int]:
        """Detection probability, and the 16-bit message read from the clip (random if there's no mark)."""
        import torch

        wav = self._resample(self._tensor(clip.samples), clip.sample_rate, RATE)
        with torch.no_grad(), self._no_compile():
            result, bits = self._detector.detect_watermark(wav)
        message = 0
        for bit in bits[0].tolist():  # most significant bit first, as in embed()
            message = (message << 1) | int(bit)
        return float(result), message
