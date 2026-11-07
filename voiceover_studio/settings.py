"""Deployment settings (from the environment) and building the configured providers.

The deploy script writes these variables on the instance; in development they come from your shell.
Only parameter NAMES of secrets appear here, never secret values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from typing import Literal

from voiceover_studio.providers import registry
from voiceover_studio.providers.base import ASRProvider, LLMProvider, StorageProvider, TTSProvider
from voiceover_studio.providers.openai_compat import infer_auth, is_local

HOSTED_TTS: set[str] = set()  # names of hosted TTS providers (e.g. "fish_audio" once added)


@dataclass(frozen=True)
class Settings:
    aws_region: str = "us-east-1"
    device: str = "cuda"

    tts_provider: str = "qwen3_tts"
    tts_model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    tts_api_key_param: str = ""

    llm_provider: str = "openai_compat"
    llm_base_url: str = "http://llm:8000/v1"
    llm_model: str = "Qwen/Qwen3.5-9B"
    llm_api_key_param: str = ""
    llm_auth: str = ""  # none | ssm | bedrock; empty = inferred from the URL and key parameter
    llm_disable_thinking: bool = True

    asr_provider: str = "faster_whisper"
    asr_model: str = "small"

    storage_provider: str = "s3"
    storage_bucket: str = ""
    storage_dir: str = "data"

    plugins: str = ""
    compute_profile: str = ""  # gpu | cpu; empty = derived from the providers

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if environ is None else environ)
        values: dict[str, object] = {}
        for f in fields(cls):
            raw = env.get(f.name.upper())
            if raw is None or raw == "":
                continue
            values[f.name] = raw.strip().lower() in {"1", "true", "yes"} if f.type == "bool" else raw.strip()
        return cls(**values)

    @property
    def resolved_llm_auth(self) -> str:
        return self.llm_auth or infer_auth(self.llm_base_url, self.llm_api_key_param)

    @property
    def resolved_compute_profile(self) -> Literal["gpu", "cpu"]:
        if self.compute_profile in ("gpu", "cpu"):
            return self.compute_profile  # type: ignore[return-value]
        local_tts = self.tts_provider not in HOSTED_TTS
        local_llm = is_local(self.llm_base_url)
        local_asr = self.asr_provider == "faster_whisper"
        return "gpu" if (local_tts or local_llm or local_asr) else "cpu"


def build_tts(s: Settings) -> TTSProvider:
    if s.tts_provider == "qwen3_tts":
        return registry.create("tts", "qwen3_tts", model=s.tts_model, device=f"{s.device}:0")  # type: ignore[return-value]
    return registry.create("tts", s.tts_provider, api_key_param=s.tts_api_key_param, region=s.aws_region)  # type: ignore[return-value]


def build_llm(s: Settings) -> LLMProvider:
    return registry.create(  # type: ignore[return-value]
        "llm",
        s.llm_provider,
        base_url=s.llm_base_url,
        model=s.llm_model,
        auth=s.resolved_llm_auth,
        api_key_param=s.llm_api_key_param,
        region=s.aws_region,
        disable_thinking=s.llm_disable_thinking,
    )


def build_asr(s: Settings) -> ASRProvider:
    compute = "float16" if s.device == "cuda" else "int8"
    return registry.create("asr", s.asr_provider, model=s.asr_model, device=s.device, compute_type=compute)  # type: ignore[return-value]


def build_storage(s: Settings) -> StorageProvider:
    if s.storage_provider == "local":
        return registry.create("storage", "local", root=s.storage_dir)  # type: ignore[return-value]
    return registry.create("storage", s.storage_provider, bucket=s.storage_bucket, region=s.aws_region)  # type: ignore[return-value]
