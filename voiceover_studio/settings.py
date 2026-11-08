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

# The exact model versions (Hugging Face commits) this release was tested with, so an upstream model update
# can't change what readers get. Used when a *_MODEL_REVISION setting is empty and the model is a default.
# The LLM's pin is also in scripts/toolbox/lib.sh: vLLM, not this app, downloads that model.
PINNED_REVISIONS = {
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base": "fd4b254389122332181a7c3db7f27e918eec64e3",  # tested 2026-11-08
    "cyankiwi/Qwen3.5-9B-AWQ-4bit": "e4d2d39cede8c5d1716d824cd843e2889c648083",  # tested 2026-11-08
    "small": "536b0662742c02347bc0e980a01041f333bce120",  # Systran/faster-whisper-small, tested 2026-11-08
}


def pinned(model: str, revision: str) -> str | None:
    """The revision to load: the one you set, else the tested pin for a default model, else the latest."""
    return revision or PINNED_REVISIONS.get(model)


@dataclass(frozen=True)
class Settings:
    aws_region: str = "us-east-1"
    device: str = "cuda"

    tts_provider: str = "qwen3_tts"
    tts_model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    tts_model_revision: str = ""  # empty = the tested pin (PINNED_REVISIONS) for the default model
    tts_api_key_param: str = ""

    llm_provider: str = "openai_compat"
    llm_base_url: str = "http://llm:8000/v1"
    llm_model: str = "cyankiwi/Qwen3.5-9B-AWQ-4bit"  # Qwen3.5-9B, 4-bit AWQ (Apache-2.0), ~9 GB of VRAM
    llm_api_key_param: str = ""
    llm_auth: str = ""  # none | ssm | bedrock; empty = inferred from the URL and key parameter
    llm_disable_thinking: bool = True

    asr_provider: str = "faster_whisper"
    asr_model: str = "small"
    asr_model_revision: str = ""
    # Whisper only checks the short consent clip, so the CPU is fast enough and the GPU memory stays free for
    # the two big models. (Its CUDA build also lags the CUDA version torch uses.)
    asr_device: str = "cpu"

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
        # Keep in step with resolve_profile in scripts/toolbox/lib.sh (the deploy scripts decide the same).
        local_tts = self.tts_provider not in HOSTED_TTS
        local_llm = is_local(self.llm_base_url)
        gpu_asr = self.asr_provider == "faster_whisper" and self.asr_device == "cuda"
        return "gpu" if (local_tts or local_llm or gpu_asr) else "cpu"


def build_tts(s: Settings) -> TTSProvider:
    if s.tts_provider == "qwen3_tts":
        return registry.create(  # type: ignore[return-value]
            "tts",
            "qwen3_tts",
            model=s.tts_model,
            revision=pinned(s.tts_model, s.tts_model_revision),
            # "cuda:0" picks the first GPU; a CPU has no index ("cpu:0" makes the model loader look for an
            # accelerator and fail).
            device="cpu" if s.device == "cpu" else f"{s.device}:0",
        )
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
    compute = "float16" if s.asr_device == "cuda" else "int8"
    return registry.create(  # type: ignore[return-value]
        "asr",
        s.asr_provider,
        model=s.asr_model,
        revision=pinned(s.asr_model, s.asr_model_revision),
        device=s.asr_device,
        compute_type=compute,
    )


def build_storage(s: Settings) -> StorageProvider:
    if s.storage_provider == "local":
        return registry.create("storage", "local", root=s.storage_dir)  # type: ignore[return-value]
    return registry.create("storage", s.storage_provider, bucket=s.storage_bucket, region=s.aws_region)  # type: ignore[return-value]
