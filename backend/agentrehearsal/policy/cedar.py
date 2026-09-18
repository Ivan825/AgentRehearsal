"""Constraints -> Cedar policy text, and local Cedar evaluation of a tool call.

The request shape mirrors AgentCore Policy so the same policy text works in both places:
tool arguments are exposed as ``context.input.<param>``. Session facts the policy may compare
against (the verified customer email, for instance) are exposed as ``context.session.<key>``.

Default deny: a tool with no permit is denied. That is how AgentCore Policy behaves too, so the
generated policy must permit every legitimate tool explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import re
import threading

import cedarpy

# cedarpy is a native extension; serialise calls into it so worker threads never enter it concurrently.
_CEDAR_LOCK = threading.Lock()

from ..config import CEDAR_PRINCIPAL
from ..spec import AgentSpec, Constraint


def _cedar_literal(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(int(v)) if float(v).is_integer() else str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _condition(c: Constraint) -> str | None:
    """One Cedar boolean expression for a constraint, or None if it needs no condition."""
    if c.kind in ("allow", "forbid"):
        return None
    p = f"context.input.{c.param}"
    if c.kind == "param_max":
        return f"{p} <= {_cedar_literal(c.value)}"
    if c.kind == "param_min":
        return f"{p} >= {_cedar_literal(c.value)}"
    if c.kind == "param_in":
        return f"[{', '.join(_cedar_literal(v) for v in (c.values or []))}].contains({p})"
    if c.kind == "param_equals_session":
        return f"{p} == context.session.{c.session_key}"
    raise ValueError(f"unknown constraint kind {c.kind}")


def constraints_to_cedar(spec: AgentSpec, agentcore_target: str | None = None, gateway_arn: str | None = None) -> str:
    """Render one permit per tool. Forbidden tools and tools with no constraints get no permit.

    With ``agentcore_target`` (and optionally ``gateway_arn``) the policy is rendered in the form AgentCore Policy
    expects: actions are ``AgentCore::Action::"<Target>___<tool>"`` and the resource is the Gateway.
    """
    def action(tool: str) -> str:
        if agentcore_target:
            return f'AgentCore::Action::"{agentcore_target}___{tool}"'
        return f'Action::"{tool}"'

    resource = f'resource == AgentCore::Gateway::"{gateway_arn}"' if (agentcore_target and gateway_arn) else "resource"
    lines: list[str] = [
        f"// AgentRehearsal least-privilege policy for {spec.name}",
        "// Default deny: any tool without a permit below is denied.",
        "",
    ]
    for tool in spec.tools:
        cs = spec.constraints_for(tool.name)
        if not cs:
            lines.append(f"// {tool.name}: no rule permits it, so it is denied.")
            lines.append("")
            continue
        if any(c.kind == "forbid" for c in cs):
            rule = next(c for c in cs if c.kind == "forbid")
            lines.append(f"// {tool.name}: forbidden ({rule.rule or rule.id}). Denied by default; forbid made explicit.")
            lines.append(f'@id("{rule.id}")')
            lines.append(f'forbid(principal, action == {action(tool.name)}, {resource});')
            lines.append("")
            continue
        conds = [x for x in (_condition(c) for c in cs) if x]
        rules = "; ".join(sorted({c.rule for c in cs if c.rule}))
        lines.append(f"// {tool.name}: {rules or 'allowed'}")
        lines.append('@id("' + "+".join(c.id for c in cs) + '")')
        head = f'permit(principal, action == {action(tool.name)}, {resource})'
        if conds:
            lines.append(head)
            lines.append("when { " + " && ".join(conds) + " };")
        else:
            lines.append(head + ";")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@dataclass
class Decision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)   # policy ids that matched
    errors: list[str] = field(default_factory=list)
    violated: list[str] = field(default_factory=list)  # constraint ids that this call breaks (best effort)

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reasons": self.reasons, "errors": self.errors, "violated": self.violated}


class CedarPolicy:
    """A parsed Cedar policy that can judge tool calls."""

    def __init__(self, cedar_text: str, spec: AgentSpec | None = None):
        self.text = cedar_text
        self.spec = spec
        with _CEDAR_LOCK:
            self._policy_set = cedarpy.PolicySet.from_str(cedar_text)
        # Map cedarpy's positional ids (policy0, policy1, ...) to @id annotations when every statement has one.
        ids = re.findall(r'@id\("([^"]+)"\)', cedar_text)
        n_statements = len(re.findall(r'^\s*(?:@id\([^)]*\)\s*)?(?:permit|forbid)\s*\(', cedar_text, re.M))
        self._names = {f"policy{i}": pid for i, pid in enumerate(ids)} if ids and len(ids) == n_statements else {}

    @classmethod
    def from_spec(cls, spec: AgentSpec) -> "CedarPolicy":
        return cls(constraints_to_cedar(spec), spec)

    def evaluate(self, tool: str, args: dict[str, Any], session: dict[str, Any] | None = None) -> Decision:
        request = {
            "principal": CEDAR_PRINCIPAL,
            "action": f'Action::"{tool}"',
            "resource": f'Tool::"{tool}"',
            "context": {"input": _coerce(args), "session": _coerce(session or {})},
        }
        with _CEDAR_LOCK:
            result = cedarpy.is_authorized(request, self._policy_set, [])
        allowed = result.decision == cedarpy.Decision.Allow
        d = Decision(allowed=allowed, reasons=[self._names.get(r, r) for r in result.diagnostics.reasons], errors=[str(e) for e in result.diagnostics.errors])
        if not allowed and self.spec:
            d.violated = self._explain_violation(tool, args, session or {})
        return d

    def _explain_violation(self, tool: str, args: dict[str, Any], session: dict[str, Any]) -> list[str]:
        """Which constraints did this call break? Plain Python re-check, so the trace can name the rule."""
        cs = self.spec.constraints_for(tool) if self.spec else []
        if not cs:
            return ["no-permit:" + tool]
        out: list[str] = []
        for c in cs:
            if c.kind == "forbid":
                out.append(c.id)
            elif c.kind == "param_max" and _num(args.get(c.param)) is not None and _num(args.get(c.param)) > float(c.value or 0):
                out.append(c.id)
            elif c.kind == "param_min" and _num(args.get(c.param)) is not None and _num(args.get(c.param)) < float(c.value or 0):
                out.append(c.id)
            elif c.kind == "param_in" and args.get(c.param) not in (c.values or []):
                out.append(c.id)
            elif c.kind == "param_equals_session" and args.get(c.param) != session.get(c.session_key or ""):
                out.append(c.id)
        return out or ["policy-deny:" + tool]


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coerce(d: dict[str, Any]) -> dict[str, Any]:
    """Cedar has no float type; whole-number floats become ints. Nested values are kept as-is."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, float) and v.is_integer():
            out[k] = int(v)
        elif isinstance(v, dict):
            out[k] = _coerce(v)
        else:
            out[k] = v
    return out


def validate_cedar(cedar_text: str) -> list[str]:
    """Return parse problems, empty if the policy is well-formed."""
    try:
        cedarpy.PolicySet.from_str(cedar_text)
        return []
    except Exception as e:  # cedarpy raises a generic error type
        return [str(e)]
