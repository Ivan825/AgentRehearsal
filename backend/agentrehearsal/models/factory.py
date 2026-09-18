"""Pick the model that plays the target agent, or the one that authors scenarios."""
from __future__ import annotations

from typing import Any

from .. import config


def target_model(kind: str = "bedrock", model_id: str | None = None) -> Any:
    if kind == "scripted":
        from .scripted import ScriptedModel

        return ScriptedModel()
    if kind == "bedrock":
        from strands.models import BedrockModel

        return BedrockModel(model_id=model_id or config.TARGET_MODEL_ID, region_name=config.AWS_REGION, temperature=0.0)
    raise ValueError(f"unknown model kind {kind!r}; use 'bedrock' or 'scripted'")


def author_model(model_id: str | None = None) -> Any:
    from strands.models import BedrockModel

    return BedrockModel(model_id=model_id or config.AUTHOR_MODEL_ID, region_name=config.AWS_REGION, temperature=0.2)
