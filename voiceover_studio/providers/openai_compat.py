"""LLM provider for any OpenAI-compatible Chat Completions endpoint.

One adapter covers the local default (vLLM serving Qwen3.5 on the same GPU) and hosted options such as
Amazon Bedrock. Authentication:
- "none":    local server, no key
- "ssm":     API key read at runtime from an SSM SecureString parameter
- "bedrock": requests signed with the instance role's AWS credentials (SigV4) by the OpenAI SDK's built-in
             Bedrock provider. No API key exists anywhere; the role needs bedrock:InvokeModel on the model.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

import httpx2
from openai import OpenAI

from voiceover_studio.providers.base import ChatMessage, LLMCapabilities, LLMProvider
from voiceover_studio.providers.registry import register
from voiceover_studio.ssm import ssm_secret

Auth = Literal["none", "ssm", "bedrock"]
LOCAL_HOSTS = {"llm", "localhost", "127.0.0.1"}


def infer_auth(base_url: str, api_key_param: str) -> Auth:
    if api_key_param:
        return "ssm"
    if "bedrock" in (urlsplit(base_url).hostname or ""):
        return "bedrock"
    return "none"


def is_local(base_url: str) -> bool:
    return (urlsplit(base_url).hostname or "") in LOCAL_HOSTS


@register("llm", "openai_compat")
class OpenAICompatLLM(LLMProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        auth: Auth = "none",
        api_key_param: str = "",
        region: str = "us-east-1",
        disable_thinking: bool = True,
        max_context_tokens: int = 32768,
        timeout_s: float = 120.0,
        http_client: httpx2.Client | None = None,
    ):
        self.base_url = base_url
        self.model = model
        self.auth = auth
        self.api_key_param = api_key_param
        self.region = region
        self.disable_thinking = disable_thinking
        self.max_context_tokens = max_context_tokens
        self.timeout_s = timeout_s
        self._http_client = http_client

    def _client(self) -> OpenAI:
        common = {"timeout": self.timeout_s, "max_retries": 2, "http_client": self._http_client}
        if self.auth == "bedrock":
            from openai.providers import bedrock

            return OpenAI(provider=bedrock(region=self.region, base_url=self.base_url), **common)
        api_key = ssm_secret(self.api_key_param, self.region) if self.auth == "ssm" else "not-needed"
        return OpenAI(base_url=self.base_url, api_key=api_key, **common)

    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            max_context_tokens=self.max_context_tokens, runs_locally=is_local(self.base_url)
        )

    def complete(self, messages: list[ChatMessage], *, max_tokens: int, temperature: float) -> str:
        extra_body = {}
        if self.disable_thinking:
            # Qwen3.x reasoning models write long hidden reasoning unless told not to (vLLM chat template).
            extra_body["chat_template_kwargs"] = {"enable_thinking": False}
        response = self._client().chat.completions.create(
            model=self.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body=extra_body or None,
        )
        return response.choices[0].message.content or ""
