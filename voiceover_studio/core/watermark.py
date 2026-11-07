"""Inaudible watermark on every output, applied by the core whatever TTS provider produced the audio.

The render pipeline requires a Watermarker: there is no setting to turn it off. AudioSeal (Meta, MIT licence
for code and weights) is the implementation; torch and audioseal are only imported when it is created.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from voiceover_studio.providers.base import AudioClip

# 16-bit message embedded in every file: "VS" (voiceover-studio).
MESSAGE = 0x5653


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
        import torch  # noqa: F401  (heavy: imported only when the watermarker is created)
        from audioseal import AudioSeal

        self._device = device
        self._generator = AudioSeal.load_generator("audioseal_wm_16bits").to(device).eval()
        self._detector = AudioSeal.load_detector("audioseal_detector_16bits").to(device).eval()

    def _tensor(self, clip: AudioClip):
        import torch

        return torch.from_numpy(np.ascontiguousarray(clip.samples, dtype=np.float32))[None, None, :].to(
            self._device
        )

    def embed(self, clip: AudioClip) -> AudioClip:
        import torch

        wav = self._tensor(clip)
        bits = [(MESSAGE >> (15 - i)) & 1 for i in range(16)]
        message = torch.tensor([bits], device=self._device)
        with torch.no_grad():
            mark = self._generator.get_watermark(wav, sample_rate=clip.sample_rate, message=message)
        out = (wav + mark).squeeze().cpu().numpy().astype(np.float32)
        return AudioClip(np.clip(out, -1.0, 1.0), clip.sample_rate)

    def detect(self, clip: AudioClip) -> float:
        import torch

        with torch.no_grad():
            result, _message = self._detector.detect_watermark(
                self._tensor(clip), sample_rate=clip.sample_rate
            )
        return float(result)
