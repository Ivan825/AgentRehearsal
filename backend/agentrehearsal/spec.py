"""The agent specification: what the agent is, which tools it has, and what it is allowed to do.

A spec is what the developer gives AgentRehearsal. Rules are plain English; constraints are the
structured form the rules are parsed into (and which the developer confirms in the UI). Constraints
are the only thing the policy engine reads.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ConstraintKind = Literal[
    "allow",                 # tool may be called with any arguments
    "forbid",                # tool must never be called
    "param_max",             # numeric param <= value
    "param_min",             # numeric param >= value
    "param_in",              # param must be one of `values`
    "param_equals_session",  # param must equal a session value (e.g. the verified customer email)
]


class ToolParam(BaseModel):
    name: str
    type: Literal["string", "number", "integer", "boolean"] = "string"
    description: str = ""
    required: bool = True


class ToolDef(BaseModel):
    name: str
    description: str
    params: list[ToolParam] = Field(default_factory=list)
    destructive: bool = False   # irreversible side effect; used for categorisation, not policy


class Constraint(BaseModel):
    """One enforceable rule about one tool.

    Several constraints may target the same tool; they are ANDed into one Cedar permit.
    A tool with no constraint at all is denied by default, exactly as AgentCore Policy behaves.
    """

    id: str
    tool: str
    kind: ConstraintKind
    param: str | None = None
    value: float | None = None
    values: list[str] | None = None
    session_key: str | None = None
    rule: str = ""              # the plain-English rule this constraint came from
    description: str = ""       # one line shown in the UI


class AgentSpec(BaseModel):
    name: str
    purpose: str
    system_prompt: str
    tools: list[ToolDef]
    rules: list[str] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)

    def tool(self, name: str) -> ToolDef | None:
        return next((t for t in self.tools if t.name == name), None)

    def constraints_for(self, tool: str) -> list[Constraint]:
        return [c for c in self.constraints if c.tool == tool]

    @classmethod
    def load(cls, path: str | Any) -> "AgentSpec":
        import json
        from pathlib import Path

        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
