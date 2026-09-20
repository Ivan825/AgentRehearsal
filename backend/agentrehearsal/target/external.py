"""Bring your own agent.

An existing agent (HTTP endpoint or AgentCore Runtime) is driven one scenario at a time. Its tools are the
workspace's simulated tools, served over MCP by the API (`/mcp/{token}`), so every tool call it makes passes
through the same policy hook as a built-in agent. While an attempt is running, calls arriving at the MCP
endpoint are attributed to it; attempts run one at a time.
"""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from ..hooks import RecordingHook
from ..spec import AgentSpec
from .generic import ToolLog, input_schema, pick_response


@dataclass
class ActiveAttempt:
    spec: AgentSpec
    hook: RecordingHook
    log: ToolLog


_active: dict[str, ActiveAttempt] = {}
_lock = threading.Lock()


def begin_attempt(token: str, spec: AgentSpec, hook: RecordingHook, log: ToolLog) -> None:
    with _lock:
        _active[token] = ActiveAttempt(spec, hook, log)


def end_attempt(token: str) -> None:
    with _lock:
        _active.pop(token, None)


def active(token: str) -> ActiveAttempt | None:
    with _lock:
        return _active.get(token)


# ---- MCP over HTTP (minimal JSON-RPC server: initialize, tools/list, tools/call, ping) -------

def mcp_tools_list(spec: AgentSpec) -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "inputSchema": input_schema(t)} for t in spec.tools]


def mcp_handle(token: str, spec: AgentSpec, message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC message. Returns the response object, or None for notifications."""
    method = message.get("method", "")
    msg_id = message.get("id")
    if msg_id is None:  # notification (e.g. notifications/initialized)
        return None

    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def err(code: int, text: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": text}}

    if method == "initialize":
        proto = (message.get("params") or {}).get("protocolVersion") or "2025-06-18"
        return ok({"protocolVersion": proto, "capabilities": {"tools": {}}, "serverInfo": {"name": "agentrehearsal", "version": "0.2.0"}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": mcp_tools_list(spec)})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name", "")
        args = dict(params.get("arguments") or {})
        tool = spec.tool(name)
        if not tool:
            return ok({"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True})
        att = active(token)
        if att is not None:
            rec = att.hook.judge(name, args)
            if rec.blocked:
                why = ", ".join(rec.violated) or "not permitted by policy"
                rec.result = f"Denied by policy ({why})."
                return ok({"content": [{"type": "text", "text": rec.result + " This action is outside what this agent is allowed to do."}], "isError": True})
        t = spec.target
        if (t.upstream_url or t.upstream_command) and t.forward_calls:
            # proxy mode: the call was allowed (or we are log-only), so it goes to the real server
            from ..connect import call_upstream_any

            try:
                result = call_upstream_any(t, name, args)
            except Exception as e:
                result = {"content": [{"type": "text", "text": f"upstream error: {e}"}], "isError": True}
            text = json.dumps(result, ensure_ascii=False)
            if att is not None:
                att.log.calls.append({"tool": name, "args": args, "returned": result, "forwarded": True})
                att.hook.calls[-1].result = text[:1500]
            return ok(result)
        resp = pick_response(tool, args)
        text = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)
        if att is not None:
            att.log.calls.append({"tool": name, "args": args, "returned": resp})
            att.hook.calls[-1].result = text[:1500]
        return ok({"content": [{"type": "text", "text": text}], "isError": False})
    return err(-32601, f"method not found: {method}")


# ---- Invoking the external agent --------------------------------------------------------------

_REPLY_KEYS = ("response", "output", "text", "result", "message", "completion", "answer", "content")


def _extract(obj: Any, path: str = "") -> str:
    if path:
        cur: Any = obj
        for part in path.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur is not None:
            return cur if isinstance(cur, str) else json.dumps(cur, ensure_ascii=False)
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        for k in _REPLY_KEYS:
            if k in obj:
                return _extract(obj[k])
        return json.dumps(obj, ensure_ascii=False)
    if isinstance(obj, list):
        return "\n".join(_extract(x) for x in obj)
    return str(obj)


def invoke_http(spec: AgentSpec, prompt: str, timeout_s: float = 120) -> str:
    import httpx

    t = spec.target
    headers = {"content-type": "application/json"}
    if t.auth_header:
        headers["authorization"] = t.auth_header
    body = {t.prompt_field or "prompt": prompt, "session_id": uuid.uuid4().hex}
    r = httpx.post(t.url, json=body, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    try:
        return _extract(r.json(), t.response_field)
    except ValueError:
        return r.text


def invoke_agentcore_runtime(spec: AgentSpec, prompt: str) -> str:
    """Invoke an agent deployed on Bedrock AgentCore Runtime. The response body may be JSON or SSE lines."""
    import boto3

    from .. import config

    client = boto3.client("bedrock-agentcore", region_name=config.AWS_REGION)
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=spec.target.agent_arn,
        runtimeSessionId=uuid.uuid4().hex + uuid.uuid4().hex[:4],   # the service wants 33+ chars
        payload=json.dumps({spec.target.prompt_field or "prompt": prompt}).encode("utf-8"),
    )
    raw = resp["response"].read().decode("utf-8", errors="replace") if hasattr(resp.get("response"), "read") else str(resp.get("response", ""))
    chunks: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        try:
            chunks.append(_extract(json.loads(line), spec.target.response_field))
        except ValueError:
            chunks.append(line.strip('"'))
    return "\n".join(chunks) if chunks else raw


def invoke_external(spec: AgentSpec, prompt: str) -> str:
    if spec.target.kind == "http":
        if not spec.target.url:
            raise RuntimeError("target.url is empty: set the agent's HTTP endpoint on the Define tab")
        return invoke_http(spec, prompt)
    if spec.target.kind == "agentcore_runtime":
        if not spec.target.agent_arn:
            raise RuntimeError("target.agent_arn is empty: set the AgentCore Runtime ARN on the Define tab")
        return invoke_agentcore_runtime(spec, prompt)
    raise RuntimeError(f"unknown target kind {spec.target.kind}")
