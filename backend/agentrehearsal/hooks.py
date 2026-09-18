"""The interception hook: sees every tool call before it runs, records it, and judges it.

rehearse mode: the call is judged and logged, then allowed through to the sandbox tool, so we can
see what the agent would have done.
enforce mode: a denied call is cancelled. The agent gets a refusal message as the tool result.

This is the local twin of AgentCore Policy's LOG_ONLY and ENFORCE modes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

from .policy.cedar import CedarPolicy

Mode = Literal["rehearse", "enforce", "observe"]
# observe: record and judge locally but never cancel; used when an external boundary (AgentCore Gateway) enforces.


@dataclass
class RecordedCall:
    seq: int
    tool: str
    args: dict[str, Any]
    allowed: bool
    blocked: bool               # True only in enforce mode when denied
    violated: list[str]
    reasons: list[str]
    t: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "tool": self.tool,
            "args": self.args,
            "allowed": self.allowed,
            "blocked": self.blocked,
            "violated": self.violated,
            "reasons": self.reasons,
        }


@dataclass
class RecordingHook(HookProvider):
    policy: CedarPolicy
    mode: Mode = "rehearse"
    session: dict[str, Any] = field(default_factory=dict)
    calls: list[RecordedCall] = field(default_factory=list)

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool_call)
        registry.add_callback(AfterToolCallEvent, self.after_tool_call)

    def before_tool_call(self, event: BeforeToolCallEvent) -> None:
        tool = event.tool_use["name"]
        args = dict(event.tool_use.get("input") or {})
        decision = self.policy.evaluate(tool, args, self.session)
        blocked = self.mode == "enforce" and not decision.allowed
        self.calls.append(
            RecordedCall(
                seq=len(self.calls) + 1,
                tool=tool,
                args=args,
                allowed=decision.allowed,
                blocked=blocked,
                violated=decision.violated,
                reasons=decision.reasons,
                t=time.time(),
            )
        )
        if blocked:
            why = ", ".join(decision.violated) or "not permitted by policy"
            event.cancel_tool = f"Denied by policy ({why}). This action is outside what this agent is allowed to do."

    def after_tool_call(self, event: AfterToolCallEvent) -> None:
        """In observe mode an external policy engine (AgentCore Gateway) may have denied the call. Detect it."""
        if self.mode != "observe" or not self.calls:
            return
        rec = self.calls[-1]
        text = ""
        try:
            text = " ".join(str(b.get("text", "")) for b in event.result.get("content", []) if isinstance(b, dict))
            status = event.result.get("status", "")
        except Exception:
            status = ""
        if status == "error" or "denied" in text.lower() or "not authorized" in text.lower() or "accessdenied" in text.lower().replace(" ", ""):
            rec.blocked = True
            rec.allowed = False if rec.allowed else rec.allowed
            if not rec.violated:
                rec.violated = ["gateway-deny:" + rec.tool]

    def denied(self) -> list[RecordedCall]:
        return [c for c in self.calls if not c.allowed]
