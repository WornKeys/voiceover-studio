"""The real AudioSeal watermark survives a resample (runs only where the model packages are installed).

CI installs no model packages, so this is skipped there; run it locally after `uv sync --extra gpu`.
"""

import numpy as np
import pytest

pytest.importorskip("audioseal")
pytest.importorskip("torchaudio")

from voiceover_studio.core.watermark import MESSAGE, AudioSealWatermarker
from voiceover_studio.providers.base import AudioClip


def speechlike(seconds: float, rate: int) -> np.ndarray:
    """Noise shaped by a syllable-rate envelope: enough signal for the mark, no recorded voice needed."""
    rng = np.random.default_rng(1)
    t = np.arange(int(seconds * rate)) / rate
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)
    return (rng.normal(0, 0.1, t.size) * envelope).astype(np.float32)


@pytest.fixture(scope="module")
def watermarker():
    return AudioSealWatermarker(device="cpu")


def test_mark_made_at_24k_survives_a_resample(watermarker):
    clip = AudioClip(speechlike(4.0, 24000), 24000)
    marked = watermarker.embed(clip)
    assert marked.sample_rate == 24000 and len(marked.samples) == len(clip.samples)

    score, message = watermarker.inspect(marked)
    assert score > 0.9 and message == MESSAGE

    # A video export resamples, e.g. to 48 kHz. The mark has to survive that (it didn't before 2026-11-08).
    import torch
    import torchaudio.functional as taf

    at48 = taf.resample(torch.from_numpy(marked.samples), 24000, 48000).numpy()
    score48, message48 = watermarker.inspect(AudioClip(at48, 48000))
    assert score48 > 0.9 and message48 == MESSAGE


def test_unmarked_audio_is_not_detected(watermarker):
    assert watermarker.detect(AudioClip(speechlike(4.0, 24000), 24000)) < 0.5
