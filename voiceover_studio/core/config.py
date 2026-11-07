"""App settings from config.yaml, with optional environment overrides.

Override any value with an environment variable named VS__<SECTION>__<KEY>, e.g.
VS__SCRIPT__WORDS_PER_MINUTE=140. Deployment settings (AWS, providers) live in the env file, not here.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
ENV_PREFIX = "VS__"


class VoiceSampleConfig(BaseModel):
    min_seconds: float = Field(5, gt=0)
    max_seconds: float = Field(15, gt=0)
    sample_rate: int = 24000
    consent_sentence: str
    consent_match_threshold: float = Field(0.8, ge=0, le=1)


class ScriptConfig(BaseModel):
    words_per_minute: int = Field(150, ge=60, le=250)
    max_target_seconds: int = Field(600, gt=0)
    temperature: float = Field(0.7, ge=0, le=2)


class SynthesisConfig(BaseModel):
    max_chunk_chars: int = Field(250, ge=40)
    pause_between_sentences_ms: int = Field(250, ge=0, le=2000)


class OutputConfig(BaseModel):
    loudness_lufs: float = Field(-16, ge=-30, le=-9)
    formats: list[str] = ["wav"]
    captions: str = "srt"
    provenance_label: str = "AI-generated voice (voiceover-studio)"


class AppConfig(BaseModel):
    voice_sample: VoiceSampleConfig
    script: ScriptConfig = ScriptConfig()
    synthesis: SynthesisConfig = SynthesisConfig()
    output: OutputConfig = OutputConfig()


def _apply_env_overrides(data: dict, environ: dict[str, str]) -> dict:
    for name, value in environ.items():
        if not name.startswith(ENV_PREFIX):
            continue
        section, _, key = name[len(ENV_PREFIX) :].lower().partition("__")
        if not key:
            continue
        data.setdefault(section, {})[key] = yaml.safe_load(value)
    return data


def load_config(path: Path | None = None, environ: dict[str, str] | None = None) -> AppConfig:
    raw = yaml.safe_load((path or DEFAULT_CONFIG_PATH).read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(
        _apply_env_overrides(raw, dict(os.environ if environ is None else environ))
    )
