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
from .target.sandbox import Sandbox
from .target.supportbot import build_target_agent
from .verdict import combine, judge_attempt

ProgressFn = Callable[[dict[str, Any]], None]


def _session_for(scenario: Scenario, sandbox: Sandbox) -> dict[str, Any]:
    cust = sandbox.customers.get(scenario.customer_id, {})
    return {"customer_id": scenario.customer_id, "customer_email": cust.get("email", "")}


def compose_prompt(scenario: Scenario, session: dict[str, Any]) -> str:
    """What the target agent actually receives: a normal support-desk context line plus the message."""
    header = f"[Support session] Verified customer: {session['customer_id']} <{session['customer_email']}>."
    if scenario.attachment_id:
        header += f" Attachment on this ticket: {scenario.attachment_id}."
    return f"{header}\n\nCustomer message:\n{scenario.prompt}"


def run_attempt(spec: AgentSpec, scenario: Scenario, model: Any, policy: CedarPolicy, mode: Mode, attempt_no: int, tools: str = "local") -> dict[str, Any]:
    sandbox = Sandbox()
    session = _session_for(scenario, sandbox)
    # With Gateway tools, AgentCore Policy makes the deny; the local hook only observes and records.
    hook = RecordingHook(policy=policy, mode="observe" if tools == "gateway" else mode, session=session)
    agent = build_target_agent(spec, model, hook, sandbox, tools=tools)
    prompt = compose_prompt(scenario, session)
    started = time.time()
    error = None
    final_text = ""
    try:
        result = agent(prompt)
        final_text = str(result).strip()
    except Exception as e:  # keep the run going; report the attempt as ERROR
        error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    v = judge_attempt(spec, scenario, hook.calls, mode, error)
    return {
        "attempt": attempt_no,
        "prompt": prompt,
        "calls": [c.as_dict() for c in hook.calls],
        "side_effects": sandbox.side_effects(),
        "final_text": final_text[:2000],
        "error": error,
        "verdict": v.verdict,
        "reason": v.reason,
        "attempted_denied": v.attempted_denied,
        "blocked": v.blocked,
        "duration_s": round(time.time() - started, 2),
    }


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

    scenario_records = []
    for s in scenarios:
        attempts = sorted(results[s.id], key=lambda a: a["attempt"])
        verdict = combine([a["verdict"] for a in attempts])
        worst = next((a for a in attempts if a["verdict"] == "FAIL"), attempts[0])
        scenario_records.append({
            **s.model_dump(),
            "verdict": verdict,
            "reason": worst["reason"],
            "attempts": attempts,
        })

    record = {
        "run_id": run_id,
        "mode": mode,
        "agent": spec.name,
        "model": model_label or getattr(model, "get_config", lambda: {})().get("model_id", "unknown"),
        "tools": tools,
        "started_at": started,
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
        "attacks_attempted": sum(1 for s in attacks if any(a["attempted_denied"] for a in s["attempts"])),
        "attacks_blocked": sum(1 for s in attacks if any(a["blocked"] for a in s["attempts"]) and s["verdict"] == "PASS"),
        "legit_total": len(legit),
        "legit_pass": sum(1 for s in legit if s["verdict"] == "PASS"),
        "by_category": by_cat,
    }


def save_run(record: dict[str, Any], runs_dir: Path | None = None) -> Path:
    d = runs_dir or config.RUNS_DIR
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{record['run_id']}.json"
    p.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    try:
        from .store import put_run

        put_run(record)
    except Exception as e:  # DynamoDB is optional; never fail a run over it
        print(f"[store] skipped: {e}")
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
