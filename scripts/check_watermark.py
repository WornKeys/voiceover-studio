#!/usr/bin/env python3
"""Check audio or video files for the studio's watermark.

Every voiceover the studio makes carries an inaudible AudioSeal watermark with the message "VS". This reads
any file ffmpeg can decode (WAV, MP3, the audio track of an MP4...) and reports how much of the audio carries
a mark, and whether it's the studio's.

  uv sync --extra gpu                                   # once: the model packages (they run on a CPU too)
  uv run python scripts/check_watermark.py voiceover.wav my-video.mp4

Exit code 0 when every file carries the studio's mark, 1 otherwise.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import numpy as np

from voiceover_studio.core.watermark import MESSAGE, AudioSealWatermarker
from voiceover_studio.providers.base import AudioClip

RATE = 16000  # AudioSeal works at 16 kHz
THRESHOLD = 0.5  # share of the audio that must carry the mark


def decode(path: Path) -> AudioClip:
    """The file's audio as 16 kHz mono, via ffmpeg (so video files and compressed audio work too)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is needed to read audio and video files.")
    cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path),
           "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"]  # fmt: skip
    out = subprocess.run(cmd, capture_output=True, check=False)
    if out.returncode != 0 or not out.stdout:
        raise ValueError(out.stderr.decode(errors="replace").strip() or "no audio track")
    samples = np.frombuffer(out.stdout, dtype="<i2").astype(np.float32) / 32768.0
    return AudioClip(samples, RATE)


def verdict(score: float, message: int) -> tuple[bool, str]:
    if score < THRESHOLD:
        return False, f"no watermark found ({score:.0%} of the audio)"
    if message != MESSAGE:
        return False, f"a watermark, but not the studio's (message {message:#06x}, {score:.0%} of the audio)"
    return True, f"watermarked by the studio ({score:.0%} of the audio carries the mark)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("files", nargs="+", type=Path, help="audio or video files")
    args = parser.parse_args(argv)

    watermarker = AudioSealWatermarker(device="cpu")
    all_marked = True
    for path in args.files:
        try:
            clip = decode(path)
        except ValueError as exc:
            print(f"{path}: can't read it ({exc})")
            all_marked = False
            continue
        marked, text = verdict(*watermarker.inspect(clip))
        print(f"{path}: {text}")
        all_marked &= marked
    return 0 if all_marked else 1


if __name__ == "__main__":
    raise SystemExit(main())
