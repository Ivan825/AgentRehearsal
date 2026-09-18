"""Build the target agent for one scenario attempt."""
from __future__ import annotations

from typing import Any

from strands import Agent

from ..hooks import RecordingHook
from ..spec import AgentSpec
from .generic import ToolLog, make_generic_tools


def build_target_agent(spec: AgentSpec, model: Any, hook: RecordingHook, log: ToolLog, tools: str = "local") -> Agent:
    """A fresh agent: fresh tool log, fresh conversation, the same system prompt every time.

    tools="local"   -> simulated tools built from the spec (Path A)
    tools="gateway" -> the same tools served by an AgentCore Gateway over MCP (Path B); requires
                       AGENTREHEARSAL_GATEWAY_URL. The caller must keep the MCP client open (see gateway_client()).
    """
    if tools == "gateway":
        client = gateway_client()
        toolset = client.list_tools_sync()
    else:
        toolset = make_generic_tools(spec, log)
    return Agent(
        model=model,
        system_prompt=spec.system_prompt,
        tools=toolset,
        hooks=[hook],
        callback_handler=None,
    )


_gateway_client = None


def gateway_client():
    """A shared MCP client for the AgentCore Gateway. Tools are listed once per process."""
    global _gateway_client
    if _gateway_client is None:
        from .. import config
        from strands.tools.mcp import MCPClient

        if not config.GATEWAY_URL:
            raise RuntimeError("AGENTREHEARSAL_GATEWAY_URL is not set; see infra/README.md")
        headers = {"Authorization": f"Bearer {config.GATEWAY_TOKEN}"} if config.GATEWAY_TOKEN else None
        _gateway_client = MCPClient(url=config.GATEWAY_URL, headers=headers, prefix=None)
        _gateway_client.__enter__()
    return _gateway_client
