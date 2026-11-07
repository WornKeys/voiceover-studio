"""Provider registry: maps a setting value (e.g. TTS_PROVIDER=qwen3_tts) to an implementation.

Providers register themselves with a decorator. Built-in providers are imported only when selected, and heavy
dependencies (torch, model weights) are imported inside the provider, so choosing a hosted provider never
loads GPU libraries.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Literal, TypeVar

Kind = Literal["tts", "llm", "asr", "storage"]
T = TypeVar("T")

_REGISTRY: dict[Kind, dict[str, Callable[..., object]]] = {"tts": {}, "llm": {}, "asr": {}, "storage": {}}

# Built-in providers: imported on first use.
BUILTIN: dict[tuple[Kind, str], str] = {
    ("tts", "qwen3_tts"): "voiceover_studio.providers.qwen3_tts",
    ("llm", "openai_compat"): "voiceover_studio.providers.openai_compat",
    ("asr", "faster_whisper"): "voiceover_studio.providers.faster_whisper_asr",
    ("storage", "local"): "voiceover_studio.providers.storage",
    ("storage", "s3"): "voiceover_studio.providers.storage",
}


class UnknownProviderError(LookupError):
    pass


def register(kind: Kind, name: str) -> Callable[[type[T]], type[T]]:
    def decorator(cls: type[T]) -> type[T]:
        if name in _REGISTRY[kind]:
            raise ValueError(f"{kind} provider '{name}' is already registered")
        _REGISTRY[kind][name] = cls
        cls.name = name  # type: ignore[attr-defined]
        return cls

    return decorator


def available(kind: Kind) -> list[str]:
    return sorted(set(_REGISTRY[kind]) | {name for (k, name) in BUILTIN if k == kind})


def create(kind: Kind, name: str, **config: object) -> object:
    if name not in _REGISTRY[kind] and (kind, name) in BUILTIN:
        importlib.import_module(BUILTIN[(kind, name)])
    try:
        factory = _REGISTRY[kind][name]
    except KeyError:
        options = ", ".join(available(kind)) or "none registered"
        raise UnknownProviderError(f"Unknown {kind} provider '{name}'. Available: {options}") from None
    return factory(**config)
