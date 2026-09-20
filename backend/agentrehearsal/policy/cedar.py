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
    if c.kind == "param_like":
        pats = [_cedar_pattern(v) for v in (c.values or [])]
        return "(" + " || ".join(f"{p} like {q}" for q in pats) + ")" if pats else None
    if c.kind == "param_not_like":
        pats = [_cedar_pattern(v) for v in (c.values or [])]
        return " && ".join(f"!({p} like {q})" for q in pats) if pats else None
    raise ValueError(f"unknown constraint kind {c.kind}")


def _cedar_pattern(v: str) -> str:
    """A Cedar `like` pattern literal: `*` is the only wildcard; other characters are literal."""
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def normalise_path(v: str) -> str:
    """Collapse `.`/`..` segments and duplicate slashes so a policy sees the path the OS would resolve.
    `docs/triage/../triage/x.md` -> `docs/triage/x.md`; a leading `../` that escapes the root is kept visible."""
    import posixpath

    if not isinstance(v, str) or ("/" not in v and "\\" not in v and not v.startswith(".")):
        return v
    s = v.replace("\\", "/")
    out = posixpath.normpath(s)
    if s.endswith("/") and not out.endswith("/"):
        out += "/"
    return out


_PATH_WORDS = ("path", "file", "dir", "folder", "source", "destination", "target", "location", "root", "uri")


def _is_path_param(name: str) -> bool:
    """Only parameters that name a location are normalised; a file's *content* is matched as written."""
    n = name.lower()
    return any(w in n for w in _PATH_WORDS) and "content" not in n


def normalise_args(spec: AgentSpec | None, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Path-like parameters of pattern constraints are normalised before the policy sees them."""
    if not spec:
        return args
    params = {c.param for c in spec.constraints_for(tool) if c.kind in ("param_like", "param_not_like") and c.param and _is_path_param(c.param)}
    if not params:
        return args
    out = dict(args)
    for k in params:
        if isinstance(out.get(k), str) and "\n" not in out[k]:
            out[k] = normalise_path(out[k])
        elif isinstance(out.get(k), list):
            out[k] = [normalise_path(x) if isinstance(x, str) else x for x in out[k]]
    return out


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
        args = normalise_args(self.spec, tool, args)
        # a list-valued path parameter (read_multiple_files) is judged element by element: every element must pass
        for k, v in list(args.items()):
            if isinstance(v, list) and v and all(isinstance(x, str) for x in v) and any(c.param == k and c.kind in ("param_like", "param_not_like") for c in (self.spec.constraints_for(tool) if self.spec else [])):
                worst: Decision | None = None
                for x in v:
                    d = self.evaluate(tool, {**args, k: x}, session)
                    if not d.allowed:
                        worst = d
                        break
                return worst or Decision(allowed=True, reasons=["all-elements"])
        request = {
            "principal": CEDAR_PRINCIPAL,
            "action": f'Action::"{tool}"',
            "resource": f'Tool::"{tool}"',
            "context": {"input": _coerce(args), "session": _coerce(session or {})},
        }
        with _CEDAR_LOCK:
            result = cedarpy.is_authorized(request, self._policy_set, [])
        allowed = result.decision == cedarpy.Decision.Allow
        errors = [str(e) for e in result.diagnostics.errors]
        if result.decision not in (cedarpy.Decision.Allow, cedarpy.Decision.Deny):
            errors.insert(0, "policy could not evaluate this call (an argument has a type the policy cannot judge); denied to be safe")
        d = Decision(allowed=allowed, reasons=[self._names.get(r, r) for r in result.diagnostics.reasons], errors=errors)
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
            elif c.kind == "param_like" and isinstance(args.get(c.param), str) and not any(_like(args[c.param], v) for v in (c.values or [])):
                out.append(c.id)
            elif c.kind == "param_not_like" and isinstance(args.get(c.param), str) and any(_like(args[c.param], v) for v in (c.values or [])):
                out.append(c.id)
        return out or ["policy-deny:" + tool]


def _like(value: str, pattern: str) -> bool:
    import fnmatch

    return fnmatch.fnmatchcase(value, pattern)


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coerce(d: dict[str, Any]) -> dict[str, Any]:
    """Make a call's arguments evaluable by Cedar: it has no null and no float.

    None is dropped (an absent optional argument), whole-number floats become ints, and other floats are rounded to the
    nearest integer so a limit rule can still judge them (12.5 -> 13; a boundary this fine is reported by the trace).
    """
    out: dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, float):
            out[k] = int(v) if v.is_integer() else int(round(v))
        elif isinstance(v, dict):
            out[k] = _coerce(v)
        elif isinstance(v, list):
            out[k] = [_coerce(x) if isinstance(x, dict) else (int(round(x)) if isinstance(x, float) else x) for x in v if x is not None]
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
