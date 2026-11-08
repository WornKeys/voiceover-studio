"""Plugin interface: server-side capabilities that the UI discovers and offers to the user.

A plugin runs at one pipeline stage, declares its settings as a pydantic model (the UI builds its controls
from that schema), and only depends on provider interfaces, never on a specific model.
Plugins are trusted code shipped in this repo: they are never downloaded or installed at runtime.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel

from voiceover_studio.providers.base import LLMProvider, TTSCapabilities, TTSProvider


class Stage(StrEnum):
    SCRIPT = "script"  # after the user approves the script, before synthesis
    AUDIO = "audio"  # after synthesis, before stitching
    OUTPUT = "output"  # after the final files are written


@dataclass
class PluginContext:
    """What a plugin can see and change. Providers are passed in so plugins never pick a model themselves."""

    script: str
    language: str  # a plugin may change it (translation does); the UI follows
    target_seconds: float | None
    words_per_minute: int
    llm: LLMProvider
    tts: TTSProvider
    # Plain-language messages shown to the user (what the plugin did, or why it did nothing).
    notes: list[str] = field(default_factory=list)


class Plugin(ABC):
    name: ClassVar[str]
    title: ClassVar[str]
    description: ClassVar[str]
    stage: ClassVar[Stage]
    Settings: ClassVar[type[BaseModel]]

    @classmethod
    def settings_schema(cls, tts: TTSCapabilities | None = None) -> dict[str, Any]:
        """JSON schema of the settings. Override it to fill in choices that depend on the providers,
        such as the languages the current voice model can speak."""
        return cls.Settings.model_json_schema()

    @classmethod
    def manifest(cls, tts: TTSCapabilities | None = None) -> dict[str, Any]:
        """What GET /api/plugins returns for this plugin."""
        return {
            "name": cls.name,
            "title": cls.title,
            "description": cls.description,
            "stage": cls.stage.value,
            "settings_schema": cls.settings_schema(tts),
        }

    @abstractmethod
    def run(self, ctx: PluginContext, settings: BaseModel) -> PluginContext: ...
