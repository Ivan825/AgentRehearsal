"""HTTP API for the UI. Runs execute in a background thread; the UI polls for progress.

    uvicorn agentrehearsal.api:app --reload --port 8000
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import config
from .models.factory import target_model
from .policy.cedar import CedarPolicy, constraints_to_cedar, validate_cedar
from .runner import compare, load_run, run_scenarios, save_run, scenarios_from_run
from .scenarios.schema import Scenario, ScenarioSet, seeds_path
from .spec import AgentSpec, Constraint

app = FastAPI(title="AgentRehearsal API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = BACKEND_DIR / "examples" / "supportbot.spec.json"
EXAMPLE_RUNS = BACKEND_DIR / "examples" / "runs"

_state: dict[str, Any] = {
    "spec": AgentSpec.load(DEFAULT_SPEC),
    "scenarios": ScenarioSet.load(seeds_path()).scenarios,
    "jobs": {},   # job_id -> {"status", "progress": [...], "run_id", "error"}
}
_lock = threading.Lock()


# ---- spec, rules, policy -----------------------------------------------------------------

@app.get("/api/spec")
def get_spec() -> dict[str, Any]:
    return _state["spec"].model_dump()


@app.put("/api/spec")
def put_spec(spec: AgentSpec) -> dict[str, Any]:
    _state["spec"] = spec
    return spec.model_dump()


class RulesIn(BaseModel):
    rules: list[str]


@app.post("/api/rules/parse")
def parse_rules_endpoint(body: RulesIn) -> dict[str, Any]:
    from .policy.parse import parse_rules

    spec = _state["spec"].model_copy(update={"rules": body.rules})
    try:
        constraints = parse_rules(spec)
    except Exception as e:
        raise HTTPException(502, f"rule parsing failed: {e}")
    return {"constraints": [c.model_dump() for c in constraints]}


@app.get("/api/policy")
def get_policy() -> dict[str, Any]:
    text = constraints_to_cedar(_state["spec"])
    return {"cedar": text, "problems": validate_cedar(text)}


class PolicyIn(BaseModel):
    cedar: str


@app.post("/api/policy/validate")
def validate_policy(body: PolicyIn) -> dict[str, Any]:
    return {"problems": validate_cedar(body.cedar)}


# ---- scenarios ---------------------------------------------------------------------------

@app.get("/api/scenarios")
def get_scenarios() -> dict[str, Any]:
    return {"scenarios": [s.model_dump() for s in _state["scenarios"]]}


@app.put("/api/scenarios")
def put_scenarios(body: ScenarioSet) -> dict[str, Any]:
    _state["scenarios"] = body.scenarios
    return {"count": len(body.scenarios)}


class GenerateIn(BaseModel):
    per_constraint: int = 4
    append: bool = True


@app.post("/api/scenarios/generate")
def generate_endpoint(body: GenerateIn) -> dict[str, Any]:
    from .scenarios.generator import generate_scenarios

    try:
        ss = generate_scenarios(_state["spec"], per_constraint=body.per_constraint)
    except Exception as e:
        raise HTTPException(502, f"scenario generation failed: {e}")
    if body.append:
        seeds = [s for s in _state["scenarios"] if s.source == "seed"]
        _state["scenarios"] = seeds + ss.scenarios
    else:
        _state["scenarios"] = ss.scenarios
    return {"generated": len(ss.scenarios), "total": len(_state["scenarios"])}


# ---- runs --------------------------------------------------------------------------------

class RunIn(BaseModel):
    mode: Literal["rehearse", "enforce"] = "rehearse"
    model: Literal["bedrock", "scripted"] = "bedrock"
    model_id: str | None = None
    attack_runs: int = 3
    workers: int = 1
    base_run_id: str | None = Field(default=None, description="replay the exact scenarios of this run")
    cedar: str | None = Field(default=None, description="override policy text (defaults to the spec's)")


def _find_run(run_id: str) -> Path:
    for d in (config.RUNS_DIR, EXAMPLE_RUNS):
        p = d / f"{run_id}.json"
        if p.exists():
            return p
    raise HTTPException(404, f"run {run_id} not found")


@app.post("/api/runs")
def start_run(body: RunIn) -> dict[str, Any]:
    spec: AgentSpec = _state["spec"]
    if body.base_run_id:
        base = load_run(_find_run(body.base_run_id))
        spec = AgentSpec.model_validate(base["spec"])
        scenarios = scenarios_from_run(base)
        cedar = body.cedar or base["policy_cedar"]
    else:
        scenarios = list(_state["scenarios"])
        cedar = body.cedar or constraints_to_cedar(spec)
    problems = validate_cedar(cedar)
    if problems:
        raise HTTPException(400, f"policy does not parse: {problems}")
    policy = CedarPolicy(cedar, spec)
    try:
        model = target_model(body.model, body.model_id)
    except Exception as e:
        raise HTTPException(400, str(e))

    job_id = f"job_{len(_state['jobs']) + 1:04d}"
    from .scenarios.schema import ATTACK_CATEGORIES
    plan = [{"id": sc.id, "title": sc.title, "category": sc.category, "attempts": max(sc.runs, body.attack_runs if sc.category in ATTACK_CATEGORIES else 1)} for sc in scenarios]
    job = {"job_id": job_id, "status": "running", "progress": [], "plan": plan, "total_attempts": sum(x["attempts"] for x in plan), "run_id": None, "error": None, "mode": body.mode, "model": body.model}
    _state["jobs"][job_id] = job

    def progress(p: dict[str, Any]) -> None:
        with _lock:
            job["progress"].append(p)

    def work() -> None:
        try:
            rec = run_scenarios(spec, scenarios, model, body.mode, policy, attack_runs=body.attack_runs, workers=body.workers, on_progress=progress)
            if body.base_run_id:
                rec["base_run_id"] = body.base_run_id
            save_run(rec)
            job["run_id"] = rec["run_id"]
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"

    threading.Thread(target=work, daemon=True).start()
    return job


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = _state["jobs"].get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    with _lock:
        return dict(job)


@app.get("/api/runs")
def list_runs() -> dict[str, Any]:
    out = []
    for d in (config.RUNS_DIR, EXAMPLE_RUNS):
        if not d.exists():
            continue
        for p in sorted(d.glob("run_*.json"), reverse=True):
            try:
                r = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({"run_id": r["run_id"], "mode": r["mode"], "model": r["model"], "started_at": r["started_at"], "summary": r["summary"], "base_run_id": r.get("base_run_id"), "example": d == EXAMPLE_RUNS})
    return {"runs": out}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    return load_run(_find_run(run_id))


@app.get("/api/compare")
def compare_runs(before: str, after: str) -> dict[str, Any]:
    return compare(load_run(_find_run(before)), load_run(_find_run(after)))


@app.get("/api/runs/{run_id}/report.md")
def run_report_endpoint(run_id: str):
    from fastapi.responses import PlainTextResponse

    from .report import run_report

    run = load_run(_find_run(run_id))
    before = load_run(_find_run(run["base_run_id"])) if run.get("base_run_id") else None
    return PlainTextResponse(run_report(run, before), media_type="text/markdown")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "region": config.AWS_REGION, "target_model": config.TARGET_MODEL_ID}
