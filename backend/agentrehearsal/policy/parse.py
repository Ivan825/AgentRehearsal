"""Plain-English rules -> structured constraints, using a Bedrock model.

The developer types rules like "Refunds up to ₹5,000". This turns them into Constraint objects that
the policy engine can enforce. The developer confirms the parsed constraints in the UI before any
test runs; the model proposes, the person approves, Cedar enforces.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from strands import Agent

from ..models.factory import author_model
from ..spec import AgentSpec, Constraint

SYSTEM = """You convert plain-English operating rules for a tool-using AI agent into structured constraints.
Each constraint applies to exactly one tool. Kinds:
- allow: the tool may be called with any arguments
- forbid: the tool must never be called
- param_max / param_min: a numeric parameter must be <= / >= value
- param_in: a string parameter must be one of `values`
- param_equals_session: a parameter must equal a session value; the only session keys are customer_id and customer_email
Every tool the agent should be able to use at all needs at least one constraint (allow or a param rule), because
tools with no constraint are denied by default. Use short kebab-case ids. Copy the source rule into `rule`."""


class ParsedConstraints(BaseModel):
    constraints: list[Constraint] = Field(default_factory=list)


def parse_rules(spec: AgentSpec, model_id: str | None = None) -> list[Constraint]:
    tools = "\n".join(f"- {t.name}({', '.join(f'{p.name}: {p.type}' for p in t.params)}): {t.description}" for t in spec.tools)
    rules = "\n".join(f"- {r}" for r in spec.rules)
    prompt = f"Agent purpose: {spec.purpose}\n\nTools:\n{tools}\n\nRules:\n{rules}\n\nReturn the constraints."
    agent = Agent(model=author_model(model_id), system_prompt=SYSTEM, callback_handler=None)
    return agent.structured_output(ParsedConstraints, prompt).constraints
