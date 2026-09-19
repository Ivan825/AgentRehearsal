"""HTTP API for the UI. Runs execute in a background thread; the UI polls for progress.

    uvicorn agentrehearsal.api:app --port 8000

Every signed-in user has a workspace: one project (agent spec + scenarios) and their runs.
With AGENTREHEARSAL_AUTH=off there is a single anonymous workspace, which is what the CLI and tests use.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from . import auth, config
from .models.factory import target_model
from .policy.cedar import CedarPolicy, constraints_to_cedar, validate_cedar
from .runner import compare, load_run, run_scenarios, save_run, scenarios_from_run
from .scenarios.schema import ATTACK_CATEGORIES, Scenario, ScenarioSet, seeds_path
from .spec import AgentSpec, ToolDef, ToolParam
from .store import get_store
from .target import external
import secrets

app = FastAPI(title="AgentRehearsal API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = BACKEND_DIR / "examples" / "supportbot.spec.json"
EXAMPLE_RUNS = BACKEND_DIR / "examples" / "runs"

_projects: dict[str, dict[str, Any]] = {}   # user_id -> {"spec": AgentSpec, "scenarios": [Scenario]}
_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


_mcp_tokens: dict[str, str] = {}   # token -> user_id


def _project(user: dict[str, Any]) -> dict[str, Any]:
    uid = user["id"]
    if uid not in _projects:
        saved = get_store().get_project(uid)
        if saved:
            _projects[uid] = {"spec": AgentSpec.model_validate(saved["spec"]), "scenarios": [Scenario.model_validate(s) for s in saved["scenarios"]], "mcp_token": saved.get("mcp_token") or secrets.token_urlsafe(24)}
        else:
            _projects[uid] = {"spec": AgentSpec.load(DEFAULT_SPEC), "scenarios": ScenarioSet.load(seeds_path()).scenarios, "mcp_token": secrets.token_urlsafe(24)}
        _mcp_tokens[_projects[uid]["mcp_token"]] = uid
    return _projects[uid]


def _persist(user: dict[str, Any]) -> None:
    p = _project(user)
    try:
        get_store().put_project(user["id"], {"spec": p["spec"].model_dump(), "scenarios": [s.model_dump() for s in p["scenarios"]], "mcp_token": p["mcp_token"]})
    except Exception as e:  # persistence is best effort
        print(f"[store] project not saved: {e}")


# ---- auth --------------------------------------------------------------------------------

class Credentials(BaseModel):
    email: str
    password: str
    name: str = ""


@app.get("/api/auth/config")
def auth_config() -> dict[str, Any]:
    return {"enabled": auth.AUTH_ENABLED}


@app.post("/api/auth/signup")
def signup(body: Credentials) -> dict[str, Any]:
    user = auth.signup(body.email, body.password, body.name)
    return {"token": auth.issue_token(user), "user": {"id": user["id"], "email": user["email"], "name": user["name"]}}


@app.post("/api/auth/login")
def login(body: Credentials) -> dict[str, Any]:
    user = auth.login(body.email, body.password)
    return {"token": auth.issue_token(user), "user": {"id": user["id"], "email": user["email"], "name": user["name"]}}


@app.get("/api/auth/me")
def me(user: dict[str, Any] = auth.User) -> dict[str, Any]:
    return user


# ---- bring your own agent: the workspace's MCP tool endpoint -------------------------------

@app.get("/api/workspace/mcp")
def workspace_mcp(request: Request, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    p = _project(user)
    base = str(request.base_url).rstrip("/")
    return {"token": p["mcp_token"], "url": f"{base}/mcp/{p['mcp_token']}", "tools": [t.name for t in p["spec"].tools]}


@app.post("/api/workspace/mcp/rotate")
def workspace_mcp_rotate(request: Request, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    p = _project(user)
    _mcp_tokens.pop(p["mcp_token"], None)
    p["mcp_token"] = secrets.token_urlsafe(24)
    _mcp_tokens[p["mcp_token"]] = user["id"]
    _persist(user)
    return workspace_mcp(request, user)


@app.post("/mcp/{token}")
async def mcp_endpoint(token: str, request: Request):
    """MCP (streamable HTTP, JSON responses) serving the workspace's simulated tools to an external agent."""
    uid = _mcp_tokens.get(token)
    if uid is None:
        # Tokens are registered when a workspace is loaded; after an API restart the owner must open the workspace once.
        raise HTTPException(404, "unknown MCP token; open the workspace (Define tab) once, then retry")
    spec: AgentSpec = _projects[uid]["spec"]
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "expected a JSON-RPC message")
    messages = body if isinstance(body, list) else [body]
    responses = [r for r in (external.mcp_handle(token, spec, m) for m in messages if isinstance(m, dict)) if r is not None]
    if not responses:
        return Response(status_code=202)
    return JSONResponse(responses[0] if not isinstance(body, list) else responses)


@app.get("/mcp/{token}")
def mcp_get(token: str):
    return Response(status_code=405)


@app.delete("/mcp/{token}")
def mcp_delete(token: str):
    return Response(status_code=200)


# ---- spec, rules, policy -----------------------------------------------------------------

@app.get("/api/spec")
def get_spec(user: dict[str, Any] = auth.User) -> dict[str, Any]:
    return _project(user)["spec"].model_dump()


@app.put("/api/spec")
def put_spec(spec: AgentSpec, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    _project(user)["spec"] = spec
    _persist(user)
    return spec.model_dump()


@app.get("/api/spec/example")
def get_example_spec() -> dict[str, Any]:
    """The SupportBot preset: a complete agent expressed as data (tools, simulated responses, rules, session)."""
    return AgentSpec.load(DEFAULT_SPEC).model_dump()


@app.post("/api/spec/reset")
def reset_to_example(user: dict[str, Any] = auth.User) -> dict[str, Any]:
    p = _project(user)
    p["spec"] = AgentSpec.load(DEFAULT_SPEC)
    p["scenarios"] = ScenarioSet.load(seeds_path()).scenarios
    _persist(user)
    return {"spec": p["spec"].model_dump(), "scenarios": len(p["scenarios"])}


class ToolsImport(BaseModel):
    tools: list[dict[str, Any]]


@app.post("/api/tools/import")
def import_tools(body: ToolsImport, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    """Convert an MCP-style tool list ({name, description, inputSchema}) into ToolDefs with empty responses."""
    out = []
    for t in body.tools:
        schema = t.get("inputSchema") or t.get("input_schema") or {}
        if "json" in schema:
            schema = schema["json"]
        props = schema.get("properties", {}) or {}
        required = set(schema.get("required", []) or [])
        params = [ToolParam(name=k, type=(v.get("type") if v.get("type") in ("string", "number", "integer", "boolean") else "string"), description=v.get("description", ""), required=k in required) for k, v in props.items()]
        out.append(ToolDef(name=t["name"], description=t.get("description", ""), params=params, destructive=bool((t.get("annotations") or {}).get("destructiveHint", False))).model_dump())
    return {"tools": out}


class RulesIn(BaseModel):
    rules: list[str]


@app.post("/api/rules/parse")
def parse_rules_endpoint(body: RulesIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    from .policy.parse import parse_rules

    spec = _project(user)["spec"].model_copy(update={"rules": body.rules})
    try:
        constraints = parse_rules(spec)
    except Exception as e:
        raise HTTPException(502, f"rule parsing failed: {e}")
    return {"constraints": [c.model_dump() for c in constraints]}


@app.get("/api/policy")
def get_policy(user: dict[str, Any] = auth.User) -> dict[str, Any]:
    text = constraints_to_cedar(_project(user)["spec"])
    return {"cedar": text, "problems": validate_cedar(text)}


class PolicyIn(BaseModel):
    cedar: str


@app.post("/api/policy/validate")
def validate_policy(body: PolicyIn) -> dict[str, Any]:
    return {"problems": validate_cedar(body.cedar)}


# ---- scenarios ---------------------------------------------------------------------------

@app.get("/api/scenarios")
def get_scenarios(user: dict[str, Any] = auth.User) -> dict[str, Any]:
    return {"scenarios": [s.model_dump() for s in _project(user)["scenarios"]]}


@app.put("/api/scenarios")
def put_scenarios(body: ScenarioSet, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    _project(user)["scenarios"] = body.scenarios
    _persist(user)
    return {"count": len(body.scenarios)}


class GenerateIn(BaseModel):
    per_constraint: int = 4
    append: bool = True


@app.post("/api/scenarios/generate")
def generate_endpoint(body: GenerateIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    from .scenarios.generator import generate_scenarios

    p = _project(user)
    try:
        ss = generate_scenarios(p["spec"], per_constraint=body.per_constraint)
    except Exception as e:
        raise HTTPException(502, f"scenario generation failed: {e}")
    existing = [s for s in p["scenarios"] if s.source == "seed"] if body.append else []
    # renumber generated ids after any that already exist
    start = len([s for s in p["scenarios"] if s.source == "generated"]) if body.append else 0
    kept = [s for s in p["scenarios"] if s.source == "generated"] if body.append else []
    for i, s in enumerate(ss.scenarios):
        s.id = f"G{start + i + 1:02d}"
    p["scenarios"] = existing + kept + ss.scenarios
    _persist(user)
    return {"generated": len(ss.scenarios), "total": len(p["scenarios"])}


# ---- runs --------------------------------------------------------------------------------

class RunIn(BaseModel):
    mode: Literal["rehearse", "enforce"] = "rehearse"
    model: Literal["bedrock", "scripted"] = "bedrock"
    model_id: str | None = None
    attack_runs: int = 3
    workers: int = 1
    base_run_id: str | None = Field(default=None, description="replay the exact scenarios of this run")
    cedar: str | None = Field(default=None, description="override policy text (defaults to the spec's)")


def _load_run_for(user: dict[str, Any], run_id: str) -> dict[str, Any]:
    p = EXAMPLE_RUNS / f"{run_id}.json"
    if p.exists():
        return load_run(p)
    rec = get_store().get_run(user["id"], run_id)
    if rec:
        return rec
    p = config.RUNS_DIR / f"{run_id}.json"   # CLI runs on the same machine (local mode only)
    if not auth.AUTH_ENABLED and p.exists():
        return load_run(p)
    raise HTTPException(404, f"run {run_id} not found")


@app.post("/api/runs")
def start_run(body: RunIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    proj = _project(user)
    spec: AgentSpec = proj["spec"]
    if body.base_run_id:
        base = _load_run_for(user, body.base_run_id)
        spec = AgentSpec.model_validate(base["spec"])
        scenarios = scenarios_from_run(base)
        cedar = body.cedar or base["policy_cedar"]
    else:
        scenarios = list(proj["scenarios"])
        cedar = body.cedar or constraints_to_cedar(spec)
    if not scenarios:
        raise HTTPException(400, "No scenarios. Add some on the Define tab or generate them.")
    problems = validate_cedar(cedar)
    if problems:
        raise HTTPException(400, f"policy does not parse: {problems}")
    policy = CedarPolicy(cedar, spec)
    external_target = spec.target.kind != "simulated" and body.model != "scripted"
    if external_target:
        spec = spec.model_copy(deep=True)
        spec.target.token = proj["mcp_token"]
    try:
        model = target_model("none" if external_target else body.model, body.model_id or spec.model_id or None)
    except Exception as e:
        raise HTTPException(400, str(e))

    job_id = f"job_{len(_jobs) + 1:04d}"
    plan = [{"id": sc.id, "title": sc.title, "category": sc.category, "attempts": max(sc.runs, body.attack_runs if sc.category in ATTACK_CATEGORIES else 1)} for sc in scenarios]
    job = {"job_id": job_id, "owner": user["id"], "status": "running", "progress": [], "plan": plan, "total_attempts": sum(x["attempts"] for x in plan), "run_id": None, "error": None, "mode": body.mode, "model": body.model, "model_id": ("external:" + spec.target.kind) if external_target else ((body.model_id or spec.model_id or config.TARGET_MODEL_ID) if body.model == "bedrock" else "scripted")}
    _jobs[job_id] = job

    def progress(p: dict[str, Any]) -> None:
        with _lock:
            job["progress"].append(p)

    def work() -> None:
        try:
            rec = run_scenarios(spec, scenarios, model, body.mode, policy, attack_runs=body.attack_runs, workers=body.workers, on_progress=progress)
            if body.base_run_id:
                rec["base_run_id"] = body.base_run_id
            rec["owner"] = user["id"]
            save_run(rec, user_id=user["id"])
            job["run_id"] = rec["run_id"]
            job["status"] = "done"
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"

    threading.Thread(target=work, daemon=True).start()
    return {k: v for k, v in job.items() if k != "owner"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job or job["owner"] != user["id"]:
        raise HTTPException(404, "no such job")
    with _lock:
        return {k: v for k, v in job.items() if k != "owner"}


@app.get("/api/runs")
def list_runs(user: dict[str, Any] = auth.User) -> dict[str, Any]:
    out = []
    try:
        for r in get_store().list_runs(user["id"]):
            out.append({**r, "example": False})
    except Exception as e:
        print(f"[store] list_runs failed: {e}")
    if not auth.AUTH_ENABLED and config.RUNS_DIR.exists():
        seen = {r["run_id"] for r in out}
        for p in sorted(config.RUNS_DIR.glob("run_*.json"), reverse=True):
            try:
                r = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if r["run_id"] not in seen:
                out.append({"run_id": r["run_id"], "mode": r["mode"], "model": r["model"], "agent": r["agent"], "started_at": r["started_at"], "summary": r["summary"], "base_run_id": r.get("base_run_id"), "example": False})
    for p in sorted(EXAMPLE_RUNS.glob("run_*.json")) if EXAMPLE_RUNS.exists() else []:
        r = json.loads(p.read_text(encoding="utf-8"))
        out.append({"run_id": r["run_id"], "mode": r["mode"], "model": r["model"], "agent": r["agent"], "started_at": r["started_at"], "summary": r["summary"], "base_run_id": r.get("base_run_id"), "example": True})
    return {"runs": out}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    return _load_run_for(user, run_id)


@app.get("/api/runs/{run_id}/report.md")
def run_report_endpoint(run_id: str, user: dict[str, Any] = auth.User):
    from .report import run_report

    run = _load_run_for(user, run_id)
    before = _load_run_for(user, run["base_run_id"]) if run.get("base_run_id") else None
    return PlainTextResponse(run_report(run, before), media_type="text/markdown")


@app.get("/api/compare")
def compare_runs(before: str, after: str, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    return compare(_load_run_for(user, before), _load_run_for(user, after))


# ---- contact + health --------------------------------------------------------------------

class ContactIn(BaseModel):
    name: str
    email: str
    message: str


@app.post("/api/contact")
def contact(body: ContactIn) -> dict[str, Any]:
    if not body.message.strip() or "@" not in body.email:
        raise HTTPException(400, "Please add a valid email and a message.")
    get_store().put_message(body.model_dump())
    return {"ok": True}


CURATED_MODELS = [
    {"id": "us.amazon.nova-micro-v1:0", "label": "Amazon Nova Micro", "note": "smallest, fails attacks most"},
    {"id": "us.amazon.nova-lite-v1:0", "label": "Amazon Nova Lite", "note": "default"},
    {"id": "us.amazon.nova-pro-v1:0", "label": "Amazon Nova Pro"},
    {"id": "us.anthropic.claude-3-5-haiku-20241022-v1:0", "label": "Claude 3.5 Haiku"},
    {"id": "us.anthropic.claude-sonnet-4-20250514-v1:0", "label": "Claude Sonnet 4"},
    {"id": "us.meta.llama3-3-70b-instruct-v1:0", "label": "Llama 3.3 70B"},
]


@app.get("/api/models")
def list_models(user: dict[str, Any] = auth.User) -> dict[str, Any]:
    """Models the target agent can run on: a curated list, plus the account's active inference profiles when reachable."""
    out = {m["id"]: dict(m) for m in CURATED_MODELS}
    out[config.TARGET_MODEL_ID] = out.get(config.TARGET_MODEL_ID, {"id": config.TARGET_MODEL_ID, "label": config.TARGET_MODEL_ID})
    out[config.TARGET_MODEL_ID]["note"] = "default"
    live = False
    try:
        import boto3

        br = boto3.client("bedrock", region_name=config.AWS_REGION)
        for prof in br.list_inference_profiles(maxResults=100).get("inferenceProfileSummaries", []):
            if prof.get("status") != "ACTIVE":
                continue
            pid = prof["inferenceProfileId"]
            if pid not in out and pid.startswith(("us.", "global.")):
                out[pid] = {"id": pid, "label": prof.get("inferenceProfileName", pid)}
        live = True
    except Exception as e:
        print(f"[models] live listing unavailable: {e}")
    return {"models": list(out.values()), "default": config.TARGET_MODEL_ID, "live": live}


@app.get("/")
def root() -> dict[str, Any]:
    return {"service": "agentrehearsal-api", "ok": True, "docs": "/docs"}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "region": config.AWS_REGION, "target_model": config.TARGET_MODEL_ID, "auth": auth.AUTH_ENABLED, "store": "dynamodb" if config.DDB_TABLE else "file"}
