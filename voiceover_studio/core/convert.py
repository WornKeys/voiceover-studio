"""Convert uploaded or recorded audio (browser webm/opus, m4a, mp3, wav) to mono 16-bit WAV with ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

MAX_INPUT_BYTES = 20 * 1024 * 1024  # a 15 s voice sample is far smaller than this


class ConversionError(ValueError):
    pass


def to_wav_pcm16(data: bytes, sample_rate: int, max_seconds: float = 60) -> bytes:
    if len(data) > MAX_INPUT_BYTES:
        raise ConversionError("The audio file is too large. Upload a short voice sample (under 15 s).")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ConversionError("ffmpeg is not installed, so this audio format can't be converted.")
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "input", Path(tmp) / "output.wav"
        src.write_bytes(data)
        cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
               "-i", str(src), "-t", str(max_seconds),
               "-ac", "1", "-ar", str(sample_rate), "-sample_fmt", "s16", "-f", "wav", str(dst)]  # fmt: skip
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0 or not dst.exists():
            raise ConversionError("This file doesn't look like audio that can be read. Try WAV, MP3 or M4A.")
        return dst.read_bytes()
