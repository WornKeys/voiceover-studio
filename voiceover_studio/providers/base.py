"""Provider interfaces: the contract between the stable core and replaceable models/vendors.

The core only talks to these interfaces. Swapping a model or vendor means adding a provider and changing a
setting, never changing the core. Each provider declares its capabilities, so the core and UI never assume
what a model can do (languages, sample length, sample rate, watermarking, where data goes).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np

# ---------------------------------------------------------------------------
# Shared data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AudioClip:
    """Mono audio as float32 samples in [-1, 1]."""

    samples: np.ndarray
    sample_rate: int

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.sample_rate


@dataclass(frozen=True)
class VoiceReference:
    """The voice to clone: a short recording plus the exact words spoken in it."""

    audio_path: Path
    transcript: str
    # Every cloned voice must point back to a recorded consent (see core guardrails).
    consent_id: str


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


# ---------------------------------------------------------------------------
# Text-to-speech
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TTSCapabilities:
    languages: tuple[str, ...]
    cloning: bool
    min_reference_seconds: float
    max_reference_seconds: float
    # True if the model clones better when it is given the transcript of the reference clip.
    uses_reference_transcript: bool
    sample_rate: int
    max_chars_per_call: int
    builtin_watermark: bool
    # False means the voice sample and text are sent to a third-party service outside the AWS account.
    runs_locally: bool


class TTSProvider(ABC):
    name: str

    @abstractmethod
    def capabilities(self) -> TTSCapabilities: ...

    @abstractmethod
    def synthesize(self, text: str, voice: VoiceReference, language: str, **settings: float) -> AudioClip:
        """Speak `text` (one chunk, at most `max_chars_per_call` characters) in the reference voice."""


# ---------------------------------------------------------------------------
# Language model (script writing, rewriting, translation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMCapabilities:
    max_context_tokens: int
    runs_locally: bool


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def capabilities(self) -> LLMCapabilities: ...

    @abstractmethod
    def complete(self, messages: list[ChatMessage], *, max_tokens: int, temperature: float) -> str: ...


# ---------------------------------------------------------------------------
# Speech-to-text (consent check)
# ---------------------------------------------------------------------------


class ASRProvider(ABC):
    name: str

    @abstractmethod
    def transcribe(self, audio_path: Path, language: str | None = None) -> str: ...


# ---------------------------------------------------------------------------
# Storage (voice samples, consent records, outputs)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    metadata: dict[str, str] = field(default_factory=dict)


class StorageProvider(ABC):
    name: str

    @abstractmethod
    def put(self, key: str, data: bytes, metadata: dict[str, str] | None = None) -> StoredObject: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def list(self, prefix: str) -> list[StoredObject]: ...
