"""A scenario is one conversation the target agent is put through, with an expected outcome."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal[
    "allowed",              # ordinary, legitimate request
    "boundary",             # exactly at a limit
    "scope_violation",      # tool exists but is outside the agent's purpose
    "parameter_violation",  # right tool, unsafe arguments
    "direct_injection",     # the user tries to override the rules
    "indirect_injection",   # a document the agent reads carries the instruction
    "destructive_action",   # irreversible action taken on an ambiguous request
]

ATTACK_CATEGORIES = {"scope_violation", "parameter_violation", "direct_injection", "indirect_injection", "destructive_action"}


class Scenario(BaseModel):
    id: str
    category: Category
    title: str
    prompt: str
    customer_id: str = ""              # legacy convenience; session values below are what the policy sees
    attachment_id: str | None = None
    session: dict[str, str] = Field(default_factory=dict)
    expected: Literal["allow", "deny"]
    must_call: str | None = None       # for allowed/boundary cases: the tool that proves the job got done
    runs: int = 1                      # attack scenarios default to 3 in the runner
    source: Literal["seed", "generated", "holdout", "escalated"] = "seed"   # holdout = authored after the policy; escalated = mutated from a resisted attack
    rationale: str = ""
    # For attacks: the call the author is trying to elicit ({"tool": ..., "args": {...}}). Lets the verdict say whether
    # a FAIL happened for the intended reason, and lets the coverage matrix count what each scenario really tests.
    expected_call: dict[str, Any] | None = None
    parent_id: str | None = None       # escalated scenarios: the resisted attack they were mutated from

    @property
    def is_attack(self) -> bool:
        return self.category in ATTACK_CATEGORIES


class ScenarioSet(BaseModel):
    scenarios: list[Scenario] = Field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "ScenarioSet":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, list):
            data = {"scenarios": data}
        return cls.model_validate(data)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")


def seeds_path() -> Path:
    return Path(__file__).with_name("seeds.json")
