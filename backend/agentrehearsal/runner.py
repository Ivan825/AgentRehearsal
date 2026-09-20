"""Run scenarios against the target agent and produce a run record.

A run record is plain JSON: everything the UI shows (scorecard, traces, policy) comes from it, and
a replay reuses the exact scenario list it holds.
"""
from __future__ import annotations

import json
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import config
from .hooks import Mode, RecordingHook
from .policy.cedar import CedarPolicy
from .scenarios.schema import ATTACK_CATEGORIES, Scenario
from .spec import AgentSpec
from .target import external
from .target.generic import ToolLog
from .target.supportbot import build_target_agent
from .verdict import combine, judge_attempt

ProgressFn = Callable[[dict[str, Any]], None]

# Bedrock occasionally aborts a stream ("Model produced invalid sequence as part of ToolUse") or throttles.
# Those are retried with a fresh tool log so one hiccup never costs a scenario.
MODEL_RETRIES = 2
_TRANSIENT = ("modelStreamErrorException", "ThrottlingException", "ServiceUnavailable", "invalid sequence", "Too many requests", "timed out")


def _is_transient(e: Exception) -> bool:
    msg = f"{type(e).__name__}: {e}"
    return any(t.lower() in msg.lower() for t in _TRANSIENT)


def _session_for(spec: AgentSpec, scenario: Scenario) -> dict[str, Any]:
    """Session facts the policy can see: spec defaults, overridden by the scenario."""
    session = dict(spec.session)
    session.update(scenario.session or {})
    if scenario.customer_id and "customer_id" not in (scenario.session or {}):
        session["customer_id"] = scenario.customer_id
    return session


def compose_prompt(spec: AgentSpec, scenario: Scenario, session: dict[str, Any]) -> str:
    """What the target agent actually receives: a context header plus the user's message."""
    header = spec.session_header or "Session: " + ", ".join(f"{k}={v}" for k, v in session.items())
    try:
        header = header.format(**session)
    except (KeyError, IndexError):
        pass
    if scenario.attachment_id:
        header += f" Attachment on this ticket: {scenario.attachment_id}."
    return f"{header}\n\nCustomer message:\n{scenario.prompt}"


def run_attempt(spec: AgentSpec, scenario: Scenario, model: Any, policy: CedarPolicy, mode: Mode, attempt_no: int, tools: str = "local") -> dict[str, Any]:
    log = ToolLog()
    session = _session_for(spec, scenario)
    # With Gateway tools, AgentCore Policy makes the deny; the local hook only observes and records.
    hook = RecordingHook(policy=policy, mode="observe" if tools == "gateway" else mode, session=session)
    prompt = compose_prompt(spec, scenario, session)
    started = time.time()
    error = None
    final_text = ""
    is_external = spec.target.kind != "simulated"
    agent = None if is_external else build_target_agent(spec, model, hook, log, tools=tools)
    for try_no in range(1, MODEL_RETRIES + 2):
        try:
            if is_external:
                external.begin_attempt(spec.target.token, spec, hook, log)
                try:
                    final_text = external.invoke_external(spec, prompt).strip()
                finally:
                    external.end_attempt(spec.target.token)
            else:
                result = agent(prompt)
                final_text = str(result).strip()
            error = None
            break
        except Exception as e:  # keep the run going; retry transient model errors, else report ERROR
            error = f"{type(e).__name__}: {e}"
            if try_no <= MODEL_RETRIES and _is_transient(e):
                hook.calls.clear()
                log = ToolLog()
                if not is_external:
                    agent = build_target_agent(spec, model, hook, log, tools=tools)
                time.sleep(1.5 * try_no)
                continue
            traceback.print_exc()
    v = judge_attempt(spec, scenario, hook.calls, mode, error)
    return {
        "attempt": attempt_no,
        "prompt": prompt,
        "calls": [c.as_dict() for c in hook.calls],
        "side_effects": log.side_effects(),
        "final_text": final_text[:2000],
        "error": error,
        "verdict": v.verdict,
        "reason": v.reason,
        "attempted_denied": v.attempted_denied,
        "blocked": v.blocked,
        # did the denied call match what the author was aiming at? (None when the scenario states no expected call)
        "on_target": _on_target(scenario, hook.calls),
        "duration_s": round(time.time() - started, 2),
    }


def _on_target(scenario: Scenario, calls: list[Any]) -> bool | None:
    exp = scenario.expected_call or {}
    if not exp.get("tool"):
        return None
    denied = [c for c in calls if not c.allowed]
    if not denied:
        return None
    return any(c.tool == exp["tool"] for c in denied)


def run_scenarios(
    spec: AgentSpec,
    scenarios: list[Scenario],
    model: Any,
    mode: Mode,
    policy: CedarPolicy | None = None,
    *,
    attack_runs: int = 3,
    workers: int = 1,
    model_label: str = "",
    on_progress: ProgressFn | None = None,
    tools: str = "local",
) -> dict[str, Any]:
    policy = policy or CedarPolicy.from_spec(spec)
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
    started = datetime.now(timezone.utc).isoformat()

    jobs: list[tuple[Scenario, int]] = []
    for s in scenarios:
        n = max(s.runs, attack_runs if s.category in ATTACK_CATEGORIES else 1)
        jobs.extend((s, i + 1) for i in range(n))

    results: dict[str, list[dict[str, Any]]] = {s.id: [] for s in scenarios}

    def work(job: tuple[Scenario, int]) -> tuple[str, dict[str, Any]]:
        s, i = job
        r = run_attempt(spec, s, model, policy, mode, i, tools=tools)
        if on_progress:
            on_progress({"scenario_id": s.id, "attempt": i, "verdict": r["verdict"], "reason": r["reason"]})
        return s.id, r

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for sid, r in pool.map(work, jobs):
            results[sid].append(r)

    label = model_label or (f"external:{spec.target.kind}" if spec.target.kind != "simulated" else getattr(model, "get_config", lambda: {})().get("model_id", "unknown"))
    return assemble_run(spec, mode, policy, [(s, results[s.id]) for s in scenarios], label, run_id=run_id, started=started, tools=tools)


def assemble_run(spec: AgentSpec, mode: Mode, policy: CedarPolicy, results: list[tuple[Scenario, list[dict[str, Any]]]], model_label: str, *, run_id: str | None = None, started: str | None = None, tools: str = "local") -> dict[str, Any]:
    """Turn per-scenario attempt records into a run record with verdicts and a summary. Used by the runner and by
    live sessions (an MCP-client agent driven by hand)."""
    scenario_records = []
    for s, atts in results:
        attempts = sorted(atts, key=lambda a: a["attempt"])
        if not attempts:
            continue
        verdict = combine([a["verdict"] for a in attempts])
        worst = next((a for a in attempts if a["verdict"] == "FAIL"), attempts[0])
        scenario_records.append({**s.model_dump(), "verdict": verdict, "reason": worst["reason"], "attempts": attempts})
    record = {
        "run_id": run_id or f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}",
        "mode": mode,
        "agent": spec.name,
        "model": model_label,
        "tools": tools,
        "started_at": started or datetime.now(timezone.utc).isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "policy_cedar": policy.text,
        "spec": spec.model_dump(),
        "scenarios": scenario_records,
    }
    record["summary"] = summarize(record)
    return record


def summarize(record: dict[str, Any]) -> dict[str, Any]:
    scs = record["scenarios"]
    by_cat: dict[str, dict[str, int]] = {}
    for s in scs:
        b = by_cat.setdefault(s["category"], {"total": 0, "pass": 0, "fail": 0, "intermittent": 0, "error": 0})
        b["total"] += 1
        b[s["verdict"].lower()] += 1
    attacks = [s for s in scs if s["category"] in ATTACK_CATEGORIES]
    legit = [s for s in scs if s["category"] not in ATTACK_CATEGORIES]
    return {
        "total": len(scs),
        "pass": sum(1 for s in scs if s["verdict"] == "PASS"),
        "fail": sum(1 for s in scs if s["verdict"] == "FAIL"),
        "intermittent": sum(1 for s in scs if s["verdict"] == "INTERMITTENT"),
        "error": sum(1 for s in scs if s["verdict"] == "ERROR"),
        "attacks_total": len(attacks),
        "attacks_unsafe": sum(1 for s in attacks if s["verdict"] in ("FAIL", "INTERMITTENT")),
        # how many of those failed on EVERY attempt: the headline number should not hinge on a 2-of-3 flip
        "attacks_unsafe_consistent": sum(1 for s in attacks if s["verdict"] == "FAIL"),
        "attacks_intermittent": sum(1 for s in attacks if s["verdict"] == "INTERMITTENT"),
        # of the attacks that reached a denied call, how many hit the call the author aimed at
        "attacks_on_target": sum(1 for s in attacks if any(a.get("on_target") for a in s["attempts"])),
        "attacks_off_target": sum(1 for s in attacks if any(a.get("on_target") is False for a in s["attempts"]) and not any(a.get("on_target") for a in s["attempts"])),
        "attacks_attempted": sum(1 for s in attacks if any(a["attempted_denied"] for a in s["attempts"])),
        "attacks_blocked": sum(1 for s in attacks if any(a["blocked"] for a in s["attempts"]) and s["verdict"] == "PASS"),
        "legit_total": len(legit),
        "legit_pass": sum(1 for s in legit if s["verdict"] == "PASS"),
        "by_category": by_cat,
    }


def save_run(record: dict[str, Any], runs_dir: Path | None = None, user_id: str = "cli", strict: bool = False) -> Path:
    """Write the run as JSON and into the store. strict=True (the API) raises when the store rejects it, so a job
    never reports a run id that cannot be opened."""
    d = runs_dir or config.RUNS_DIR
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{record['run_id']}.json"
    p.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    try:
        from .store import put_run

        put_run(record, user_id=user_id)
    except Exception as e:  # for the CLI the store is best effort
        print(f"[store] skipped: {e}")
        if strict:
            raise RuntimeError(f"run finished but could not be stored: {type(e).__name__}: {str(e)[:200]}") from e
    return p



def load_run(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def scenarios_from_run(record: dict[str, Any]) -> list[Scenario]:
    keys = set(Scenario.model_fields)
    return [Scenario.model_validate({k: v for k, v in s.items() if k in keys}) for s in record["scenarios"]]


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Before/after view for the Replay screen."""
    b, a = before["summary"], after["summary"]
    per = []
    after_by_id = {s["id"]: s for s in after["scenarios"]}
    for s in before["scenarios"]:
        t = after_by_id.get(s["id"])
        per.append({"id": s["id"], "title": s["title"], "category": s["category"], "before": s["verdict"], "after": t["verdict"] if t else None})
    return {
        "before_run": before["run_id"],
        "after_run": after["run_id"],
        "before": {"pass": b["pass"], "total": b["total"], "unsafe": b["attacks_unsafe"], "legit_pass": b["legit_pass"], "legit_total": b["legit_total"]},
        "after": {"pass": a["pass"], "total": a["total"], "unsafe": a["attacks_unsafe"], "blocked": a["attacks_blocked"], "legit_pass": a["legit_pass"], "legit_total": a["legit_total"]},
        "scenarios": per,
    }
