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
import os
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

def _public_base(request: Request) -> str:
    """The URL agents outside should use to reach this API.

    Behind a proxy (Amplify rewrites, CloudFront, an ALB) request.base_url is the internal
    address, so deployments set AGENTREHEARSAL_PUBLIC_URL to the address users actually see.
    """
    return (os.environ.get("AGENTREHEARSAL_PUBLIC_URL") or str(request.base_url)).rstrip("/")


@app.get("/api/workspace/mcp")
def workspace_mcp(request: Request, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    p = _project(user)
    base = _public_base(request)
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


EXAMPLES: dict[str, dict[str, Any]] = {
    "supportbot": {
        "name": "SupportBot",
        "blurb": "Electronics-store support agent with refund, email and delete tools. Ships with 15 hand-written seed scenarios; the offline simulation models this agent.",
        "spec": DEFAULT_SPEC,
        "scenarios": seeds_path(),
        "offline": True,
    },
    "traveldesk": {
        "name": "TravelDesk",
        "blurb": "Corporate travel agent with booking, cancellation and itinerary-sharing tools. No seeds: every scenario is authored by Bedrock from the rules, which is how a new agent is tested.",
        "spec": BACKEND_DIR / "examples" / "traveldesk.spec.json",
        "scenarios": BACKEND_DIR / "examples" / "traveldesk.scenarios.json",   # optional, written by `agentrehearsal generate`
        "offline": False,
    },
}


@app.get("/api/examples")
def list_examples() -> dict[str, Any]:
    out = []
    for key, ex in EXAMPLES.items():
        n = len(ScenarioSet.load(ex["scenarios"]).scenarios) if Path(ex["scenarios"]).exists() else 0
        out.append({"id": key, "name": ex["name"], "blurb": ex["blurb"], "scenarios": n, "offline": ex["offline"]})
    return {"examples": out}


@app.get("/api/spec/example")
def get_example_spec(example: str = "supportbot") -> dict[str, Any]:
    """An example preset: a complete agent expressed as data (tools, simulated responses, rules, session)."""
    ex = EXAMPLES.get(example)
    if not ex:
        raise HTTPException(404, f"no example {example!r}")
    return AgentSpec.load(ex["spec"]).model_dump()


class ResetIn(BaseModel):
    example: str = "supportbot"


@app.post("/api/spec/reset")
def reset_to_example(body: ResetIn | None = None, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    ex = EXAMPLES.get((body or ResetIn()).example)
    if not ex:
        raise HTTPException(404, "no such example")
    p = _project(user)
    p["spec"] = AgentSpec.load(ex["spec"])
    p["scenarios"] = ScenarioSet.load(ex["scenarios"]).scenarios if Path(ex["scenarios"]).exists() else []
    _persist(user)
    return {"spec": p["spec"].model_dump(), "scenarios": len(p["scenarios"]), "example": ex["name"]}


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
    """Author scenarios with the author model in the background.

    Returns a job; poll /api/jobs/{job_id} until status is "done" and read `result`.
    (A synchronous call can exceed the 30 s limit of hosted proxies such as Amplify/CloudFront.)
    """
    from .scenarios.generator import generate_scenarios

    p = _project(user)
    job = _new_job(user, kind="generate")

    def work() -> None:
        try:
            ss = generate_scenarios(p["spec"], per_constraint=body.per_constraint)
            with _lock:
                existing = [s for s in p["scenarios"] if s.source == "seed"] if body.append else []
                # renumber generated ids after any that already exist
                start = len([s for s in p["scenarios"] if s.source == "generated"]) if body.append else 0
                kept = [s for s in p["scenarios"] if s.source == "generated"] if body.append else []
                for i, s in enumerate(ss.scenarios):
                    s.id = f"G{start + i + 1:02d}"
                p["scenarios"] = existing + kept + ss.scenarios
                job["result"] = {"generated": len(ss.scenarios), "total": len(p["scenarios"])}
                job["status"] = "done"
            _persist(user)
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"scenario generation failed: {type(e).__name__}: {e}" + ("  → the author model is retired on Bedrock; set AGENTREHEARSAL_AUTHOR_MODEL in backend/.env to an active one (e.g. us.anthropic.claude-sonnet-4-5-20250929-v1:0) and restart the API." if "Legacy" in str(e) else "")

    threading.Thread(target=work, daemon=True).start()
    return _public_job(job)


def _new_job(user: dict[str, Any], **fields: Any) -> dict[str, Any]:
    with _lock:
        job_id = f"job_{len(_jobs) + 1:04d}"
        job: dict[str, Any] = {"job_id": job_id, "owner": user["id"], "status": "running", "progress": [], "plan": [], "total_attempts": 0, "run_id": None, "result": None, "error": None, **fields}
        _jobs[job_id] = job
    return job


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in job.items() if k != "owner"}


# ---- runs --------------------------------------------------------------------------------

class RunIn(BaseModel):
    mode: Literal["rehearse", "enforce"] = "rehearse"
    model: Literal["bedrock", "scripted"] = "bedrock"
    model_id: str | None = None
    attack_runs: int = 3
    workers: int = 1
    base_run_id: str | None = Field(default=None, description="replay the exact scenarios of this run")
    cedar: str | None = Field(default=None, description="override policy text (defaults to the spec's)")


def _prepare_target(proj: dict[str, Any], spec: AgentSpec, model_kind: str, model_id: str | None) -> tuple[AgentSpec, Any, bool]:
    """Resolve where the scenarios run: a simulated agent on a Bedrock model, the scripted stand-in, or the
    user's own agent reached through the workspace MCP endpoint."""
    external_target = spec.target.kind != "simulated" and model_kind != "scripted"
    if external_target:
        spec = spec.model_copy(deep=True)
        spec.target.token = proj["mcp_token"]
    try:
        model = target_model("none" if external_target else model_kind, model_id or spec.model_id or None)
    except Exception as e:
        raise HTTPException(400, str(e))
    return spec, model, external_target


def _model_label(spec: AgentSpec, model_kind: str, model_id: str | None, external_target: bool) -> str:
    if external_target:
        return "external:" + spec.target.kind
    return (model_id or spec.model_id or config.TARGET_MODEL_ID) if model_kind == "bedrock" else "scripted"


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
    spec, model, external_target = _prepare_target(proj, spec, body.model, body.model_id)

    plan = [{"id": sc.id, "title": sc.title, "category": sc.category, "attempts": max(sc.runs, body.attack_runs if sc.category in ATTACK_CATEGORIES else 1)} for sc in scenarios]
    job = _new_job(user, kind="run", plan=plan, total_attempts=sum(x["attempts"] for x in plan), mode=body.mode, model=body.model, model_id=_model_label(spec, body.model, body.model_id, external_target))

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
    return _public_job(job)


class ValidateIn(BaseModel):
    """Held-out validation: author scenarios the policy has never seen, then run them twice —
    without enforcement (do they get through?) and with it (are they blocked, is legitimate work intact?)."""

    base_run_id: str = Field(description="the run whose spec and policy are being validated (usually the enforce run)")
    per_constraint: int = 2
    model: Literal["bedrock", "scripted"] = "bedrock"
    model_id: str | None = None
    attack_runs: int = 3


@app.post("/api/validate")
def start_validation(body: ValidateIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    from .scenarios.generator import generate_scenarios

    proj = _project(user)
    base = _load_run_for(user, body.base_run_id)
    spec = AgentSpec.model_validate(base["spec"])
    cedar = base["policy_cedar"]
    problems = validate_cedar(cedar)
    if problems:
        raise HTTPException(400, f"policy does not parse: {problems}")
    policy = CedarPolicy(cedar, spec)
    spec, model, external_target = _prepare_target(proj, spec, body.model, body.model_id)
    seen_titles = [s["title"] for s in base["scenarios"]] + [s.title for s in proj["scenarios"]]
    seen_prompts = [s["prompt"] for s in base["scenarios"]]
    job = _new_job(user, kind="validate", phase="authoring", mode="rehearse", model=body.model, model_id=_model_label(spec, body.model, body.model_id, external_target), base_run_id=body.base_run_id)

    def progress(p: dict[str, Any]) -> None:
        with _lock:
            job["progress"].append(p)

    def work() -> None:
        try:
            ss = generate_scenarios(spec, per_constraint=body.per_constraint, avoid=list(dict.fromkeys(seen_titles + seen_prompts)), source="holdout")
            if not ss.scenarios:
                raise RuntimeError("the author model produced no usable held-out scenarios; try again")
            plan = [{"id": sc.id, "title": sc.title, "category": sc.category, "attempts": max(sc.runs, body.attack_runs if sc.category in ATTACK_CATEGORIES else 1)} for sc in ss.scenarios]
            with _lock:
                job.update(plan=plan, total_attempts=sum(x["attempts"] for x in plan), phase="rehearse", mode="rehearse", progress=[])
            before = run_scenarios(spec, ss.scenarios, model, "rehearse", policy, attack_runs=body.attack_runs, workers=1, on_progress=progress)
            before.update(owner=user["id"], holdout=True, base_run_id=body.base_run_id)
            save_run(before, user_id=user["id"])
            with _lock:
                job.update(phase="enforce", mode="enforce", progress=[])
            after = run_scenarios(spec, ss.scenarios, model, "enforce", policy, attack_runs=body.attack_runs, workers=1, on_progress=progress)
            after.update(owner=user["id"], holdout=True, base_run_id=before["run_id"], validates_run_id=body.base_run_id)
            save_run(after, user_id=user["id"])
            with _lock:
                job.update(run_id=after["run_id"], result={"before_run": before["run_id"], "after_run": after["run_id"], "generated": len(ss.scenarios)}, status="done", phase="done")
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"

    threading.Thread(target=work, daemon=True).start()
    return _public_job(job)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job or job["owner"] != user["id"]:
        raise HTTPException(404, "no such job")
    with _lock:
        return _public_job(job)


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
                out.append({"run_id": r["run_id"], "mode": r["mode"], "model": r["model"], "agent": r["agent"], "started_at": r["started_at"], "summary": r["summary"], "base_run_id": r.get("base_run_id"), "holdout": bool(r.get("holdout")), "example": False})
    for p in sorted(EXAMPLE_RUNS.glob("run_*.json")) if EXAMPLE_RUNS.exists() else []:
        r = json.loads(p.read_text(encoding="utf-8"))
        out.append({"run_id": r["run_id"], "mode": r["mode"], "model": r["model"], "agent": r["agent"], "started_at": r["started_at"], "summary": r["summary"], "base_run_id": r.get("base_run_id"), "holdout": bool(r.get("holdout")), "example": True})
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
    {"id": "us.amazon.nova-micro-v1:0", "label": "Amazon Nova Micro", "note": "smallest, fails attacks most", "provider": "bedrock"},
    {"id": "us.amazon.nova-lite-v1:0", "label": "Amazon Nova Lite", "note": "default", "provider": "bedrock"},
    {"id": "us.amazon.nova-pro-v1:0", "label": "Amazon Nova Pro", "provider": "bedrock"},
    {"id": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "label": "Claude Haiku 4.5", "provider": "bedrock"},
    {"id": "us.anthropic.claude-sonnet-4-5-20250929-v1:0", "label": "Claude Sonnet 4.5", "provider": "bedrock"},
    {"id": "us.meta.llama3-3-70b-instruct-v1:0", "label": "Llama 3.3 70B", "provider": "bedrock"},
]


@app.get("/api/models")
def list_models(user: dict[str, Any] = auth.User) -> dict[str, Any]:
    """Models the target agent can run on: a curated list, plus the account's active inference profiles when reachable."""
    from .models.factory import PROVIDERS, provider_available, split_model_id

    out = {m["id"]: dict(m) for m in CURATED_MODELS}
    out[config.TARGET_MODEL_ID] = out.get(config.TARGET_MODEL_ID, {"id": config.TARGET_MODEL_ID, "label": config.TARGET_MODEL_ID, "provider": split_model_id(config.TARGET_MODEL_ID)[0]})
    out[config.TARGET_MODEL_ID]["note"] = "default"
    providers = [{"id": "bedrock", "label": PROVIDERS["bedrock"]["label"], "available": True, "env": None}]   # Bedrock only for now
    live = False
    try:
        import boto3

        br = boto3.client("bedrock", region_name=config.AWS_REGION)
        for prof in br.list_inference_profiles(maxResults=100).get("inferenceProfileSummaries", []):
            if prof.get("status") != "ACTIVE":
                continue
            pid = prof["inferenceProfileId"]
            if pid not in out and pid.startswith(("us.", "global.")):
                out[pid] = {"id": pid, "label": prof.get("inferenceProfileName", pid), "provider": "bedrock"}
        live = True
    except Exception as e:
        print(f"[models] live listing unavailable: {e}")
    for m in out.values():
        m.setdefault("provider", "bedrock")
        m["available"] = provider_available(m["provider"])
    return {"models": list(out.values()), "default": config.TARGET_MODEL_ID, "live": live, "providers": providers}


@app.get("/")
def root() -> dict[str, Any]:
    return {"service": "agentrehearsal-api", "ok": True, "docs": "/docs"}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "region": config.AWS_REGION, "target_model": config.TARGET_MODEL_ID, "auth": auth.AUTH_ENABLED, "store": "dynamodb" if config.DDB_TABLE else "file"}
