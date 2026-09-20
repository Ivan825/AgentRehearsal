"""Same policy text, same decision? Prove it instead of claiming it.

Sends the same tool calls to the local Cedar evaluator (the Strands hook's decision point) and to a deployed
Amazon Bedrock AgentCore Gateway whose policy engine holds the same policy in ENFORCE mode, and prints both
decisions side by side. Exit code 0 only when every case agrees.

    python scripts/gateway_equivalence.py --spec backend/examples/supportbot.spec.json \
        --gateway-url https://<id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp \
        --gateway-token "$TOKEN" --target SupportTools

Cases come from the spec's seed/held-out scenarios' expected calls when present, plus a fixed battery per
constraint kind (at the limit, just over, wrong recipient, forbidden tool, unconstrained tool). The Gateway is
called for real, so point it at the simulated Lambda target from infra/README.md, never at production tools.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402

from agentrehearsal.policy.cedar import CedarPolicy  # noqa: E402
from agentrehearsal.spec import AgentSpec  # noqa: E402


def battery(spec: AgentSpec) -> list[dict]:
    """One decisive call per constraint kind, derived from the spec."""
    cases = []
    session = dict(spec.session)
    for c in spec.constraints:
        t = spec.tool(c.tool)
        if not t:
            continue
        base = {p.name: (1 if p.type in ("integer", "number") else f"{p.name}_x") for p in t.params}
        if c.kind == "allow":
            cases.append({"why": f"{c.id}: allowed tool", "tool": c.tool, "args": base, "expect": True})
        elif c.kind == "forbid":
            cases.append({"why": f"{c.id}: forbidden tool", "tool": c.tool, "args": base, "expect": False})
        elif c.kind == "param_max" and c.param and c.value is not None:
            cases.append({"why": f"{c.id}: at the limit", "tool": c.tool, "args": {**base, c.param: int(c.value)}, "expect": True})
            cases.append({"why": f"{c.id}: one over", "tool": c.tool, "args": {**base, c.param: int(c.value) + 1}, "expect": False})
        elif c.kind == "param_min" and c.param and c.value is not None:
            cases.append({"why": f"{c.id}: at the minimum", "tool": c.tool, "args": {**base, c.param: int(c.value)}, "expect": True})
            cases.append({"why": f"{c.id}: one under", "tool": c.tool, "args": {**base, c.param: int(c.value) - 1}, "expect": False})
        elif c.kind == "param_in" and c.param and c.values:
            cases.append({"why": f"{c.id}: allowed value", "tool": c.tool, "args": {**base, c.param: c.values[0]}, "expect": True})
            cases.append({"why": f"{c.id}: other value", "tool": c.tool, "args": {**base, c.param: "not_" + c.values[0]}, "expect": False})
        elif c.kind == "param_equals_session" and c.param and c.session_key:
            cases.append({"why": f"{c.id}: session value", "tool": c.tool, "args": {**base, c.param: session.get(c.session_key, "")}, "expect": True})
            cases.append({"why": f"{c.id}: other value", "tool": c.tool, "args": {**base, c.param: "someone.else@example.com"}, "expect": False})
        elif c.kind == "param_like" and c.param and c.values:
            cases.append({"why": f"{c.id}: matching path", "tool": c.tool, "args": {**base, c.param: c.values[0].replace("*", "x")}, "expect": True})
            cases.append({"why": f"{c.id}: outside", "tool": c.tool, "args": {**base, c.param: "/elsewhere/outside.txt"}, "expect": False})
        elif c.kind == "param_not_like" and c.param and c.values:
            cases.append({"why": f"{c.id}: denied pattern", "tool": c.tool, "args": {**base, c.param: c.values[0].replace("*", "x")}, "expect": False})
    constrained = {c.tool for c in spec.constraints}
    for t in spec.tools:
        if t.name not in constrained:
            cases.append({"why": f"{t.name}: no rule at all", "tool": t.name, "args": {p.name: 1 for p in t.params}, "expect": False})
    return cases


def gateway_decision(url: str, token: str, target: str, tool: str, args: dict, session: dict) -> tuple[bool, str]:
    """True when the Gateway executed the call, False when its policy engine denied it."""
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream", "authorization": f"Bearer {token}"}
    name = f"{target}___{tool}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": {**args, "_session": session}}}
    r = httpx.post(url, headers=headers, json=body, timeout=30)
    text = r.text
    if r.status_code in (401, 403):
        return False, f"http {r.status_code}"
    try:
        data = r.json()
    except ValueError:
        data = {}
    err = (data.get("error") or {}).get("message", "") if isinstance(data, dict) else ""
    result = data.get("result") if isinstance(data, dict) else None
    denied = "denied" in (err + text).lower() or "policy" in err.lower() or (isinstance(result, dict) and result.get("isError") and "denied" in json.dumps(result).lower())
    return (not denied and result is not None), (err or (json.dumps(result)[:80] if result is not None else text[:80]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", default="backend/examples/supportbot.spec.json")
    ap.add_argument("--policy", default=None, help="Cedar text to use locally (default: compiled from the spec)")
    ap.add_argument("--gateway-url", required=True)
    ap.add_argument("--gateway-token", required=True)
    ap.add_argument("--target", default="SupportTools", help="Gateway target name (actions are <target>___<tool>)")
    ap.add_argument("--local-only", action="store_true", help="print the local decisions without calling the Gateway")
    a = ap.parse_args()

    spec = AgentSpec.load(a.spec)
    policy = CedarPolicy(Path(a.policy).read_text() if a.policy else CedarPolicy.from_spec(spec).text, spec)
    cases = battery(spec)
    agree = 0
    print(f"{'case':46} {'expect':7} {'local':7} {'gateway':8} note")
    for c in cases:
        local = policy.evaluate(c["tool"], c["args"], spec.session).allowed
        if a.local_only:
            gw, note = local, "(skipped)"
        else:
            gw, note = gateway_decision(a.gateway_url, a.gateway_token, a.target, c["tool"], c["args"], spec.session)
        ok = local == gw == c["expect"]
        agree += ok
        print(f"{c['why'][:46]:46} {str(c['expect']):7} {str(local):7} {str(gw):8} {'OK' if ok else 'MISMATCH'} {note[:60]}")
    print(f"\n{agree}/{len(cases)} cases agree (expected == local == gateway)")
    return 0 if agree == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
