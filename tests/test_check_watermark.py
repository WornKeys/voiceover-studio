import importlib.util
import shutil
from pathlib import Path

import numpy as np
import pytest

from voiceover_studio.core.audio import write_wav
from voiceover_studio.core.watermark import MESSAGE
from voiceover_studio.providers.base import AudioClip

_spec = importlib.util.spec_from_file_location(
    "check_watermark", Path(__file__).parents[1] / "scripts" / "check_watermark.py"
)
check_watermark = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_watermark)


def test_verdict_needs_enough_marked_audio_and_the_studio_message():
    assert check_watermark.verdict(0.98, MESSAGE)[0] is True
    assert check_watermark.verdict(0.2, MESSAGE)[0] is False
    marked, text = check_watermark.verdict(0.9, MESSAGE ^ 0x00FF)
    assert marked is False
    assert "not the studio's" in text


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_decode_reads_any_format_as_16k_mono(tmp_path):
    tone = np.sin(2 * np.pi * 440 * np.arange(24000) / 24000).astype(np.float32) * 0.3
    wav = write_wav(AudioClip(tone, 24000), tmp_path / "tone.wav")
    clip = check_watermark.decode(wav)
    assert clip.sample_rate == 16000
    assert abs(len(clip.samples) - 16000) < 100


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_decode_reports_files_without_audio(tmp_path):
    empty = tmp_path / "notes.wav"
    empty.write_bytes(b"not audio")
    with pytest.raises(ValueError):
        check_watermark.decode(empty)
