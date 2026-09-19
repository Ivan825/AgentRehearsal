"""Pick the model that plays the target agent, or the one that authors scenarios.

Model ids are provider-prefixed. No prefix (or `bedrock:`) means Amazon Bedrock, which is the default
and the only provider that needs no extra key. The others read one API key each from the environment:

    openai:gpt-4o-mini            OPENAI_API_KEY
    gemini:gemini-2.5-flash       GEMINI_API_KEY (or GOOGLE_API_KEY)
    anthropic:claude-sonnet-4-5   ANTHROPIC_API_KEY

Every provider is a Strands model class, so hooks, tool calls and verdicts work identically: the policy
sits at the tool boundary and never cares which model is on the other side.
"""
from __future__ import annotations

import os
from typing import Any

from .. import config

PROVIDERS: dict[str, dict[str, Any]] = {
    "bedrock": {"label": "Amazon Bedrock", "env": None},
    "openai": {"label": "OpenAI", "env": "OPENAI_API_KEY"},
    "gemini": {"label": "Google Gemini", "env": "GEMINI_API_KEY"},
    "anthropic": {"label": "Anthropic API", "env": "ANTHROPIC_API_KEY"},
}


def split_model_id(model_id: str) -> tuple[str, str]:
    """'openai:gpt-4o-mini' -> ('openai', 'gpt-4o-mini'); 'us.amazon.nova-lite-v1:0' -> ('bedrock', ...)."""
    head, sep, rest = model_id.partition(":")
    if sep and head in PROVIDERS:
        return head, rest
    return "bedrock", model_id


def provider_key(provider: str) -> str | None:
    env = PROVIDERS[provider]["env"]
    if env is None:
        return None
    if provider == "gemini":
        return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    return os.getenv(env)


def provider_available(provider: str) -> bool:
    return provider == "bedrock" or bool(provider_key(provider))


def _build(model_id: str, temperature: float) -> Any:
    provider, mid = split_model_id(model_id)
    if provider == "bedrock":
        from strands.models import BedrockModel

        return BedrockModel(model_id=mid, region_name=config.AWS_REGION, temperature=temperature)
    key = provider_key(provider)
    if not key:
        raise ValueError(f"{PROVIDERS[provider]['label']} models need {PROVIDERS[provider]['env']} set on the server")
    if provider == "openai":
        from strands.models.openai import OpenAIModel

        return OpenAIModel(client_args={"api_key": key}, model_id=mid, params={"temperature": temperature})
    if provider == "gemini":
        from strands.models.gemini import GeminiModel

        return GeminiModel(client_args={"api_key": key}, model_id=mid, params={"temperature": temperature})
    if provider == "anthropic":
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(client_args={"api_key": key}, model_id=mid, max_tokens=2048, params={"temperature": temperature})
    raise ValueError(f"unknown provider {provider!r}")


def target_model(kind: str = "bedrock", model_id: str | None = None) -> Any:
    """kind: 'bedrock' (any provider, chosen by the model id prefix) | 'scripted' | 'none' (external agents)."""
    if kind == "none":
        return None
    if kind == "scripted":
        from .scripted import ScriptedModel

        return ScriptedModel()
    if kind == "bedrock":
        return _build(model_id or config.TARGET_MODEL_ID, temperature=0.0)
    raise ValueError(f"unknown model kind {kind!r}; use 'bedrock' or 'scripted'")


def author_model(model_id: str | None = None) -> Any:
    return _build(model_id or config.AUTHOR_MODEL_ID, temperature=0.2)
