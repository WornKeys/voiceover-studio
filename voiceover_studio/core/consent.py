"""Consent and quality checks for a voice sample.

The user reads a fixed consent sentence aloud. That one recording is:
- the consent record (speech-to-text must match the sentence), and
- the voice reference for cloning (the sentence is its exact transcript, which improves cloning quality).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher

import numpy as np

from voiceover_studio.core.audio import rms_dbfs, trim_silence
from voiceover_studio.core.config import VoiceSampleConfig
from voiceover_studio.core.text import APOSTROPHE
from voiceover_studio.providers.base import AudioClip


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower().replace(APOSTROPHE, "'"))


def match_score(expected: str, heard: str) -> float:
    """How closely the transcript matches the expected sentence, word by word (0..1)."""
    return SequenceMatcher(None, _words(expected), _words(heard), autojunk=False).ratio()


@dataclass(frozen=True)
class ConsentRecord:
    consent_id: str
    sentence: str
    transcript: str
    score: float
    sample_sha256: str
    created_at: str


class ConsentError(ValueError):
    """The recording doesn't contain the consent sentence."""


def record_consent(sentence: str, transcript: str, sample_bytes: bytes, threshold: float) -> ConsentRecord:
    score = match_score(sentence, transcript)
    if score < threshold:
        raise ConsentError(
            "The recording doesn't match the consent sentence closely enough "
            f"({score:.0%}, need {threshold:.0%}). Please read the sentence exactly as shown and try again."
        )
    return ConsentRecord(
        consent_id=str(uuid.uuid4()),
        sentence=sentence,
        transcript=transcript,
        score=round(score, 3),
        sample_sha256=hashlib.sha256(sample_bytes).hexdigest(),
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


@dataclass
class SampleCheck:
    clip: AudioClip  # the trimmed sample, ready to use as the voice reference
    problems: list[str] = field(default_factory=list)  # blocking: ask the user to record again
    warnings: list[str] = field(default_factory=list)  # not blocking: quality may suffer

    @property
    def ok(self) -> bool:
        return not self.problems


def check_sample(clip: AudioClip, cfg: VoiceSampleConfig) -> SampleCheck:
    trimmed = trim_silence(clip)
    check = SampleCheck(trimmed)
    samples = np.asarray(trimmed.samples, dtype=np.float32)
    if not len(samples):
        check.problems.append("No speech found. Check that the right microphone is selected.")
        return check

    seconds = trimmed.seconds
    if seconds < cfg.min_seconds:
        check.problems.append(f"Too short ({seconds:.1f} s). Record at least {cfg.min_seconds:.0f} seconds.")
    if seconds > cfg.max_seconds:
        check.problems.append(f"Too long ({seconds:.1f} s). Keep it under {cfg.max_seconds:.0f} seconds.")

    clipped = float(np.mean(np.abs(samples) >= 0.99))
    if clipped > 0.001:
        check.problems.append(
            "The recording is distorted (too loud). Move back from the microphone and retry."
        )

    level = rms_dbfs(samples)
    if level < -35:
        check.problems.append("The recording is very quiet. Move closer to the microphone and retry.")

    frame = max(1, int(trimmed.sample_rate * 0.02))
    frames = [rms_dbfs(samples[i : i + frame]) for i in range(0, len(samples) - frame + 1, frame)]
    finite = [f for f in frames if np.isfinite(f)]
    if len(finite) >= 10:
        noise, speech = np.percentile(finite, 10), np.percentile(finite, 90)
        if speech - noise < 15:
            check.warnings.append("Background noise is noticeable. A quieter room will give a cleaner voice.")
    return check
