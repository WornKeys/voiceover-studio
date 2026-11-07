"""Captions (SRT) from the spoken chunks and their timings."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def _timestamp(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def make_cues(
    segments: list[tuple[float, float, str]], max_line_chars: int = 42, max_lines: int = 2
) -> list[Cue]:
    """One cue per segment, split into several cues (time shared by length) when the text doesn't fit."""
    cues: list[Cue] = []
    for start, end, text in segments:
        lines = textwrap.wrap(text, max_line_chars)
        if not lines:
            continue
        groups = [lines[i : i + max_lines] for i in range(0, len(lines), max_lines)]
        total = sum(len(" ".join(g)) for g in groups)
        position = start
        for group in groups:
            share = (end - start) * len(" ".join(group)) / total
            cues.append(Cue(position, position + share, "\n".join(group)))
            position += share
    return cues


def to_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{i}\n{_timestamp(c.start)} --> {_timestamp(c.end)}\n{c.text}\n" for i, c in enumerate(cues, start=1)
    ]
    return "\n".join(blocks)
