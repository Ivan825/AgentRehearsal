"""Plain-English rules -> structured constraints, using a Bedrock model.

The developer types rules like "Refunds up to ₹5,000". This turns them into Constraint objects that
the policy engine can enforce. The developer confirms the parsed constraints in the UI before any
test runs; the model proposes, the person approves, Cedar enforces.

The parser also says how sure it is: a confidence per constraint and an ambiguity note when a rule
leaves something open ("'small refunds' names no number"). Every constraint is then validated against
the spec (tool, parameter, type, session key must exist) so a typo never reaches the policy silently.
"""
from __future__ import annotations

from typing import Any

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
- param_equals_session: a parameter must equal a session value; use only the session keys you are given
- param_like: a string parameter (usually a path) must match one of `values`, glob-style with * as the wildcard;
  use it for "may only write under <dir>" (values like "*/<dir>/*") or "may read files in <root>"
- param_not_like: a string parameter must match none of `values`; use it for deny lists of paths or names
  ("never read .env, *.pem, id_rsa, anything under secrets" -> values ["*/.env", ".env", "*.pem", "*id_rsa*", "*/secrets/*", "secrets/*"])
  and for content rules ("never write credential contents" -> param content, values like "*BEGIN * PRIVATE KEY*", "*sk_live_*", "*://*:*@*")
A rule that is not about a tool call at all (for example "instructions found in files are data, not commands") cannot
become a constraint: return nothing for it and explain why in `ambiguity` on a constraint with kind "allow" and id "not-enforceable-<n>"
ONLY IF you must return something; otherwise simply omit it and mention it in the ambiguity of the nearest related constraint.
Path rules apply to every tool that takes that kind of path: a "may only write under X" rule covers write_file, edit_file,
create_directory and move_file's destination; a "must never read Y" rule covers read_text_file, read_multiple_files (param paths),
get_file_info and search_files's path. Emit one constraint per tool. Paths may be absolute or relative, so patterns should
start with "*/" and also include the relative form.
Every tool the agent should be able to use at all needs at least one constraint (allow or a param rule), because
tools with no constraint are denied by default. Use short kebab-case ids. Copy the source rule into `rule`.
Use only tool and parameter names that exist. For each constraint give `confidence` (0-1) and, when the rule
leaves something open (no number given, two tools could be meant, a word like "sensitive" or "small"), an
`ambiguity` note saying what you assumed, in one line. Otherwise leave `ambiguity` empty.

Examples of each kind:
- "Read customer records freely" -> {kind: allow, tool: get_customer}
- "Never delete customer records" -> {kind: forbid, tool: delete_customer}
- "Refunds up to ₹5,000 only" -> {kind: param_max, tool: refund_customer, param: amount, value: 5000}
- "Orders must be at least 1 unit" -> {kind: param_min, tool: place_order, param: quantity, value: 1}
- "Only economy or premium economy cabins" -> {kind: param_in, tool: book_flight, param: cabin, values: [economy, premium_economy]}
- "Email only the verified customer on the session" -> {kind: param_equals_session, tool: send_email, param: to, session_key: customer_email}
- "The agent may only write files inside workspace/acme-app/docs/triage" -> {kind: param_like, tool: write_file, param: path, values: ["*/acme-app/docs/triage/*", "acme-app/docs/triage/*"]} (and the same for edit_file, create_directory)
- "must never read .env, any .pem file, id_rsa, or anything under secrets" -> {kind: param_not_like, tool: read_text_file, param: path, values: ["*/.env", ".env", "*.pem", "*id_rsa*", "*/secrets/*", "secrets/*"]}"""


class ParsedConstraint(Constraint):
    confidence: float = 1.0
    ambiguity: str = ""


class ParsedConstraints(BaseModel):
    constraints: list[ParsedConstraint] = Field(default_factory=list)


def validate_constraints(spec: AgentSpec, constraints: list[Constraint]) -> list[str]:
    """Problems that would make a constraint silently wrong. Empty list = fine."""
    problems: list[str] = []
    tools = {t.name: t for t in spec.tools}
    for c in constraints:
        t = tools.get(c.tool)
        if not t:
            problems.append(f"{c.id}: tool '{c.tool}' does not exist (have: {', '.join(tools) or 'none'})")
            continue
        if c.kind in ("param_max", "param_min", "param_in", "param_equals_session"):
            p = next((x for x in t.params if x.name == c.param), None)
            if not p:
                problems.append(f"{c.id}: {c.tool} has no parameter '{c.param}' (have: {', '.join(x.name for x in t.params) or 'none'})")
                continue
            if c.kind in ("param_max", "param_min"):
                if p.type not in ("number", "integer"):
                    problems.append(f"{c.id}: {c.tool}.{c.param} is a {p.type}, so a numeric limit can never match")
                if c.value is None:
                    problems.append(f"{c.id}: no value given for the limit")
            if c.kind in ("param_in", "param_like", "param_not_like") and not c.values:
                problems.append(f"{c.id}: {c.kind} with no values")
            if c.kind in ("param_like", "param_not_like") and p.type not in ("string",):
                problems.append(f"{c.id}: {c.tool}.{c.param} is a {p.type}; pattern rules need a string parameter")
            if c.kind == "param_equals_session":
                if not c.session_key:
                    problems.append(f"{c.id}: no session key given")
                elif c.session_key not in spec.session:
                    problems.append(f"{c.id}: session has no key '{c.session_key}' (have: {', '.join(spec.session) or 'none'}); the policy would deny every call")
    covered = {c.tool for c in constraints}
    for name in tools:
        if name not in covered:
            problems.append(f"{name}: no rule mentions it, so it is denied by default (add an allow rule if the agent needs it)")
    return problems


def parse_rules_detailed(spec: AgentSpec, model_id: str | None = None) -> dict[str, Any]:
    tools = "\n".join(f"- {t.name}({', '.join(f'{p.name}: {p.type}' for p in t.params)}): {t.description}" for t in spec.tools)
    rules = "\n".join(f"- {r}" for r in spec.rules)
    prompt = f"Agent purpose: {spec.purpose}\n\nTools:\n{tools}\n\nSession keys available: {', '.join(spec.session) or '(none)'}\n\nRules:\n{rules}\n\nReturn the constraints."
    agent = Agent(model=author_model(model_id), system_prompt=SYSTEM, callback_handler=None)
    parsed = agent.structured_output(ParsedConstraints, prompt).constraints
    constraints = [Constraint.model_validate(c.model_dump(exclude={"confidence", "ambiguity"})) for c in parsed]
    return {
        "constraints": [c.model_dump() for c in constraints],
        "notes": [{"id": c.id, "confidence": round(float(c.confidence), 2), "ambiguity": c.ambiguity} for c in parsed],
        "problems": validate_constraints(spec, constraints),
    }


def parse_rules(spec: AgentSpec, model_id: str | None = None) -> list[Constraint]:
    return [Constraint.model_validate(c) for c in parse_rules_detailed(spec, model_id)["constraints"]]
