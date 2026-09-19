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


class MockResponse(BaseModel):
    """What the simulated tool returns. The first response whose `when` matches the call's arguments wins;
    a response with no `when` is the default. String values may use {{param}} placeholders."""

    when: dict[str, Any] | None = None
    returns: Any = Field(default_factory=lambda: {"status": "ok"})


class ToolDef(BaseModel):
    name: str
    description: str
    params: list[ToolParam] = Field(default_factory=list)
    destructive: bool = False   # irreversible side effect; used for categorisation, not policy
    responses: list[MockResponse] = Field(default_factory=list)


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


class TargetConfig(BaseModel):
    """Where the agent under test lives.

    simulated          AgentRehearsal builds the agent itself: the system prompt above, on `model_id`, with the
                       simulated tools. This is the default.
    http               An existing agent behind an HTTP endpoint. AgentRehearsal POSTs each scenario to `url` and
                       reads the reply. The agent must take its tools from the workspace's MCP endpoint so every
                       call passes through the policy.
    agentcore_runtime  Same, for an agent deployed on Amazon Bedrock AgentCore Runtime (`agent_arn`).
    """

    kind: Literal["simulated", "http", "agentcore_runtime"] = "simulated"
    url: str = ""
    auth_header: str = ""          # sent as the Authorization header to `url`, e.g. "Bearer …"
    prompt_field: str = "prompt"   # JSON field carrying the scenario text
    response_field: str = ""       # dotted path to the reply text; auto-detected when empty
    agent_arn: str = ""
    token: str = ""                # set by the API at run time: identifies the workspace's MCP endpoint


class AgentSpec(BaseModel):
    name: str
    purpose: str
    system_prompt: str
    model_id: str = ""             # Bedrock model (or inference profile) the agent runs on; empty = server default
    target: TargetConfig = Field(default_factory=TargetConfig)
    tools: list[ToolDef]
    rules: list[str] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    # Session facts a policy may compare arguments against (context.session.<key> in Cedar), with defaults.
    # A scenario can override any of them. Example: {"customer_id": "c_1001", "customer_email": "priya.nair@example.com"}
    session: dict[str, str] = Field(default_factory=dict)
    # Free text shown to the target agent at the start of every scenario, e.g. "Verified customer: {customer_id} <{customer_email}>"
    session_header: str = ""

    def tool(self, name: str) -> ToolDef | None:
        return next((t for t in self.tools if t.name == name), None)

    def constraints_for(self, tool: str) -> list[Constraint]:
        return [c for c in self.constraints if c.tool == tool]

    @classmethod
    def load(cls, path: str | Any) -> "AgentSpec":
        import json
        from pathlib import Path

        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
