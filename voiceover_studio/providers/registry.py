"""Provider registry: maps a setting value (e.g. TTS_PROVIDER=qwen3_tts) to an implementation.

Providers register themselves with a decorator. Heavy dependencies (torch, model weights) are imported inside
the provider module, so selecting a hosted provider never loads GPU libraries.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, TypeVar

Kind = Literal["tts", "llm", "asr", "storage"]
T = TypeVar("T")

_REGISTRY: dict[Kind, dict[str, Callable[..., object]]] = {"tts": {}, "llm": {}, "asr": {}, "storage": {}}


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
    return sorted(_REGISTRY[kind])


def create(kind: Kind, name: str, **config: object) -> object:
    try:
        factory = _REGISTRY[kind][name]
    except KeyError:
        options = ", ".join(available(kind)) or "none registered"
        raise UnknownProviderError(f"Unknown {kind} provider '{name}'. Available: {options}") from None
    return factory(**config)
