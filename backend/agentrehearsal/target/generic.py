"""Build simulated Strands tools from a spec. No real system is ever called.

Each ToolDef carries `responses`: the first one whose `when` matches the call's arguments is returned,
else the default (no `when`), else {"status": "ok"}. This is enough to express realistic worlds: a
customer lookup keyed by id, an invoice that carries an injected instruction, a refund confirmation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from strands.tools.tools import PythonAgentTool

from ..spec import AgentSpec, ToolDef

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_JSON_TYPES = {"string": "string", "number": "number", "integer": "integer", "boolean": "boolean"}


@dataclass
class ToolLog:
    """Side effects of one scenario attempt: every simulated call, in order."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def side_effects(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for c in self.calls:
            counts[c["tool"]] = counts.get(c["tool"], 0) + 1
        return {"tool_calls": counts, "calls": self.calls}


def _fill(value: Any, args: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda m: str(args.get(m.group(1), m.group(0))), value)
    if isinstance(value, list):
        return [_fill(v, args) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, args) for k, v in value.items()}
    return value


def pick_response(tool: ToolDef, args: dict[str, Any]) -> Any:
    default: Any = {"status": "ok"}
    for r in tool.responses:
        if r.when is None:
            default = r.returns
            continue
        if all(str(args.get(k)) == str(v) for k, v in r.when.items()):
            return _fill(r.returns, args)
    return _fill(default, args)


def input_schema(tool: ToolDef) -> dict[str, Any]:
    props = {p.name: {"type": _JSON_TYPES.get(p.type, "string"), **({"description": p.description} if p.description else {})} for p in tool.params}
    return {"type": "object", "properties": props, "required": [p.name for p in tool.params if p.required]}


def make_generic_tools(spec: AgentSpec, log: ToolLog) -> list[PythonAgentTool]:
    out: list[PythonAgentTool] = []
    for t in spec.tools:
        def fn(tool_use: dict[str, Any], _t: ToolDef = t, **_: Any) -> dict[str, Any]:
            args = dict(tool_use.get("input") or {})
            resp = pick_response(_t, args)
            log.calls.append({"tool": _t.name, "args": args, "returned": resp})
            text = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)
            return {"toolUseId": tool_use["toolUseId"], "status": "success", "content": [{"text": text}]}

        fn.__name__ = t.name
        out.append(PythonAgentTool(t.name, {"name": t.name, "description": t.description, "inputSchema": {"json": input_schema(t)}}, fn))
    return out
