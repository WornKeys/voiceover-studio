#!/usr/bin/env python3
"""Keep voice recordings out of the repository (see RESPONSIBLE_USE.md).

Detects audio by file extension AND by content (so a renamed recording is still caught).
The only allowed audio file is the synthetic demo voice.

Usage:
  check_no_audio.py FILE...     check the given files (used by the pre-commit hook)
  check_no_audio.py --tracked   check every file tracked by git
  check_no_audio.py --history   check every file in the whole git history (run before making the repo public)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path, PurePosixPath

AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".webm", ".ogg", ".oga", ".opus",
    ".flac", ".aac", ".aif", ".aiff", ".mka", ".wma",
}  # fmt: skip
ALLOWED = {"samples/demo-voice.wav"}


def sniff(head: bytes) -> str | None:
    """Return the audio format if the first bytes look like an audio file."""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:3] == b"ID3":
        return "mp3"
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return "mp3"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        return "ogg/opus"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm/mka"
    if head[4:8] == b"ftyp" and head[8:12] in (b"M4A ", b"M4B ", b"mp42", b"isom"):
        return "m4a/mp4"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    return None


def problem(path: str, head: bytes) -> str | None:
    if PurePosixPath(path).as_posix() in ALLOWED:
        return None
    if PurePosixPath(path).suffix.lower() in AUDIO_EXTENSIONS:
        return "audio file extension"
    kind = sniff(head)
    return f"looks like {kind} audio" if kind else None


def check_files(paths: list[str]) -> list[str]:
    found = []
    for path in paths:
        p = Path(path)
        if not p.is_file():
            continue
        with p.open("rb") as fh:
            head = fh.read(16)
        if reason := problem(p.as_posix(), head):
            found.append(f"{p.as_posix()}: {reason}")
    return found


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def check_history() -> list[str]:
    found = []
    seen = set()
    for line in git("rev-list", "--objects", "--all").splitlines():
        sha, _, path = line.partition(" ")
        if not path or sha in seen:
            continue
        seen.add(sha)
        if git("cat-file", "-t", sha).strip() != "blob":
            continue
        head = subprocess.run(["git", "cat-file", "blob", sha], check=True, capture_output=True).stdout[:16]
        if reason := problem(path, head):
            found.append(f"{path} ({sha[:10]}): {reason}")
    return found


def main(argv: list[str]) -> int:
    if argv == ["--tracked"]:
        found = check_files(git("ls-files").splitlines())
    elif argv == ["--history"]:
        found = check_history()
    else:
        found = check_files(argv)
    if found:
        print("Audio files must not be committed (voices are personal data). Found:", file=sys.stderr)
        for item in found:
            print(f"  {item}", file=sys.stderr)
        print("Remove them from the commit. If one is already in history, rewrite history before publishing.",
              file=sys.stderr)  # fmt: skip
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
