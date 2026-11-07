"""Fake providers for tests: no models, no GPU, no network."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from voiceover_studio.core.text import word_count
from voiceover_studio.core.watermark import Watermarker
from voiceover_studio.providers.base import (
    AudioClip,
    ChatMessage,
    LLMCapabilities,
    LLMProvider,
    TTSCapabilities,
    TTSProvider,
    VoiceReference,
)

RATE = 24000


def tone(seconds: float, amplitude: float = 0.3, freq: float = 220.0, rate: int = RATE) -> AudioClip:
    t = np.arange(int(seconds * rate)) / rate
    return AudioClip((amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32), rate)


class FakeLLM(LLMProvider):
    name = "fake_llm"

    def __init__(self, reply: str | Callable[[list[ChatMessage]], str]):
        self.reply = reply
        self.calls: list[list[ChatMessage]] = []

    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(max_context_tokens=8192, runs_locally=True)

    def complete(self, messages: list[ChatMessage], *, max_tokens: int, temperature: float) -> str:
        self.calls.append(messages)
        return self.reply(messages) if callable(self.reply) else self.reply


class FakeTTS(TTSProvider):
    """Speaks every word as 0.4 s of tone."""

    name = "fake_tts"

    def __init__(self, languages: tuple[str, ...] = ("en",), cloning: bool = True, max_chars: int = 200):
        self._caps = TTSCapabilities(
            languages=languages,
            cloning=cloning,
            min_reference_seconds=3,
            max_reference_seconds=15,
            uses_reference_transcript=True,
            sample_rate=RATE,
            max_chars_per_call=max_chars,
            builtin_watermark=False,
            runs_locally=True,
        )
        self.spoken: list[str] = []

    def capabilities(self) -> TTSCapabilities:
        return self._caps

    def synthesize(self, text: str, voice: VoiceReference, language: str, **settings: float) -> AudioClip:
        assert len(text) <= self._caps.max_chars_per_call
        self.spoken.append(text)
        return tone(0.4 * max(1, word_count(text)))


class FakeWatermarker(Watermarker):
    """Marks a clip by adding a tiny constant offset, so detect() can tell marked and unmarked clips apart."""

    method = "fake"
    OFFSET = 1e-3

    def embed(self, clip: AudioClip) -> AudioClip:
        return AudioClip((clip.samples + self.OFFSET).astype(np.float32), clip.sample_rate)

    def detect(self, clip: AudioClip) -> float:
        return 1.0 if abs(float(np.mean(clip.samples)) - self.OFFSET) < self.OFFSET / 2 else 0.0
