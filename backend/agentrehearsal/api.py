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
import time

app = FastAPI(title="AgentRehearsal API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = BACKEND_DIR / "examples" / "supportbot.spec.json"
EXAMPLE_RUNS = BACKEND_DIR / "examples" / "runs"

_projects: dict[str, dict[str, Any]] = {}   # user_id -> {"spec": AgentSpec, "scenarios": [Scenario]}
_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.RLock()   # re-entrant: _project() takes it and is called from inside locked sections


_mcp_tokens: dict[str, str] = {}   # token -> user_id


def _load_project(uid: str) -> dict[str, Any]:
    saved = get_store().get_project(uid)
    if saved:
        return {"spec": AgentSpec.model_validate(saved["spec"]), "scenarios": [Scenario.model_validate(s) for s in saved["scenarios"]],
                "mcp_token": saved.get("mcp_token") or secrets.token_urlsafe(24), "_version": saved.get("updated_at", "")}
    return {"spec": AgentSpec.load(DEFAULT_SPEC), "scenarios": ScenarioSet.load(seeds_path()).scenarios, "mcp_token": secrets.token_urlsafe(24), "_version": ""}


def _project(user: dict[str, Any]) -> dict[str, Any]:
    """The user's workspace (spec + scenarios), kept in memory for speed but always checked against the store.

    The store is the source of truth: if another API instance (a second ECS task, a rolling deployment) or a restart has
    written a newer version, the cached copy is replaced. An in-progress job keeps its own reference to the dict it
    started with and persists that dict, so its result is never lost to a reload.
    """
    uid = user["id"]
    with _lock:
        cached = _projects.get(uid)
        try:
            ver = get_store().project_version(uid)
        except Exception as e:
            print(f"[store] version check failed: {e}")
            ver = cached["_version"] if cached else None
        if cached is None or (ver is not None and ver != cached.get("_version")):
            cached = _load_project(uid)
            _projects[uid] = cached
        _mcp_tokens[cached["mcp_token"]] = uid
        return cached


def _spec_from_run(run: dict[str, Any], proj: dict[str, Any]) -> AgentSpec:
    """The agent as it was when a run was recorded. Older stored runs (the shipped examples) predate session facts,
    while their policy refers to them, so fill those in from the current workspace."""
    spec = AgentSpec.model_validate(run["spec"])
    if not spec.session and proj["spec"].session and proj["spec"].name == spec.name:
        spec = spec.model_copy(update={"session": proj["spec"].session, "session_header": proj["spec"].session_header})
    return spec


def _assign_ids(user: dict[str, Any], new: list[Scenario], prefix: str) -> list[Scenario]:
    """Give new scenarios ids that collide with nothing in the workspace as it is now."""
    with _lock:
        taken = {s.id for s in _project(user)["scenarios"]}
    n = 0
    for s in new:
        n += 1
        while f"{prefix}{n:02d}" in taken:
            n += 1
        s.id = f"{prefix}{n:02d}"
        taken.add(s.id)
    return new


def _add_scenarios(user: dict[str, Any], new: list[Scenario], prefix: str, replace_all: bool = False, assign_ids: bool = True) -> list[Scenario]:
    """Append scenarios to the user's workspace as it is NOW (not as a job saw it when it started) and persist.
    Edits the user made while the job ran are kept. Returns the scenarios with their final ids."""
    with _lock:
        cur = _project(user)
        if replace_all:
            cur["scenarios"] = []
        if assign_ids:
            _assign_ids(user, new, prefix)
        present = {s.id for s in cur["scenarios"]}
        cur["scenarios"] = list(cur["scenarios"]) + [s for s in new if s.id not in present]
        _persist(user, cur)
    return list(new)


def _persist(user: dict[str, Any], p: dict[str, Any] | None = None, strict: bool = False) -> None:
    """Write the workspace to the store. Pass `p` from a job so the dict it mutated is what gets saved."""
    uid = user["id"]
    if p is None:
        p = _projects.get(uid) or _project(user)
    try:
        ver = get_store().put_project(uid, {"spec": p["spec"].model_dump(), "scenarios": [s.model_dump() for s in p["scenarios"]], "mcp_token": p["mcp_token"]})
        p["_version"] = ver
        with _lock:
            _projects[uid] = p
            _mcp_tokens[p["mcp_token"]] = uid
    except Exception as e:  # persistence is best effort, but an edit the user made must not vanish silently
        print(f"[store] project not saved: {e}")
        if strict:
            raise HTTPException(500, f"saved in memory only, the store rejected it: {type(e).__name__}: {str(e)[:200]}")


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
    t = p["spec"].target
    return {"token": p["mcp_token"], "url": f"{base}/mcp/{p['mcp_token']}", "tools": [t_.name for t_ in p["spec"].tools], "upstream": t.upstream_url or t.upstream_command, "forwarding": bool((t.upstream_url or t.upstream_command) and t.forward_calls),
            "mcp_json": {"mcpServers": {"agentrehearsal": {"type": "http", "url": f"{base}/mcp/{p['mcp_token']}"}}}}


@app.post("/api/workspace/mcp/rotate")
def workspace_mcp_rotate(request: Request, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    p = _project(user)
    old = p["mcp_token"]
    _mcp_tokens.pop(old, None)
    p["mcp_token"] = secrets.token_urlsafe(24)
    _mcp_tokens[p["mcp_token"]] = user["id"]
    _persist(user, strict=True)
    try:
        get_store().forget_mcp_token(old)
    except Exception as e:
        print(f"[store] old token not removed: {e}")
    return workspace_mcp(request, user)


@app.post("/mcp/{token}")
async def mcp_endpoint(token: str, request: Request):
    """MCP (streamable HTTP, JSON responses) serving the workspace's simulated tools to an external agent."""
    uid = _mcp_tokens.get(token)
    if uid is None:
        try:
            uid = get_store().user_by_mcp_token(token)
        except Exception as e:
            print(f"[store] token lookup failed: {e}")
    if uid is None:
        raise HTTPException(404, "unknown MCP token; copy the current URL from the Define tab (it may have been rotated)")
    proj = _project({"id": uid})
    if proj["mcp_token"] != token:   # rotated on another instance
        _mcp_tokens.pop(token, None)
        raise HTTPException(404, "this MCP URL was rotated; copy the current one from the Define tab")
    spec: AgentSpec = proj["spec"]
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


class ConnectIn(BaseModel):
    url: str
    auth_header: str = ""


@app.post("/api/tools/connect")
def connect_mcp(body: ConnectIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    """Read an MCP server's tool list. `url` is a streamable-HTTP URL, or a command line for a stdio server
    (e.g. "npx -y @modelcontextprotocol/server-filesystem /path"). Schema only; the server's tools are never called."""
    from .connect import fetch_tools_any, tools_from_mcp

    try:
        raw = fetch_tools_any(body.url, body.auth_header)
    except Exception as e:
        raise HTTPException(502, f"could not read tools from {body.url}: {type(e).__name__}: {e}")
    tools = tools_from_mcp(raw)
    if not tools:
        raise HTTPException(502, "the server returned no tools")
    return {"tools": [t.model_dump() for t in tools], "count": len(tools)}


class DraftIn(BaseModel):
    name: str = ""
    purpose: str = ""
    tools: list[ToolDef]
    apply: bool = True   # replace the project's agent with the drafted one


@app.post("/api/tools/draft")
def draft_world_endpoint(body: DraftIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    """Background job: Bedrock drafts the simulated world (responses per tool, one poisoned document, session facts)
    and suggests rules. Result: {spec, rules_with_reasons}. With apply=true the project's agent is replaced and its
    scenario list cleared, ready for Parse rules → Generate → Rehearse."""
    from .connect import draft_world, spec_from_connection

    proj = _project(user)
    job = _new_job(user, kind="draft", phase="authoring")

    def work() -> None:
        try:
            world = draft_world(body.purpose, body.tools)
            spec = spec_from_connection(body.name, body.purpose, body.tools, world)
            with _lock:
                job["phase"] = "parsing"
            try:   # best effort: rules -> constraints, so the agent is runnable straight away
                from .policy.parse import parse_rules

                spec = spec.model_copy(update={"constraints": parse_rules(spec)})
            except Exception as e:
                print(f"[draft] rules not parsed: {e}")
            with _lock:
                job["result"] = {"spec": spec.model_dump(), "rules_with_reasons": world.rules}
                if body.apply:
                    proj["spec"] = spec
                    proj["scenarios"] = []
                job.update(status="done", phase="done")
            if body.apply:
                _persist(user, proj)
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"drafting failed: {type(e).__name__}: {e}"

    threading.Thread(target=work, daemon=True).start()
    return _public_job(job)


class RulesIn(BaseModel):
    rules: list[str]


@app.post("/api/rules/parse")
def parse_rules_endpoint(body: RulesIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    from .policy.parse import parse_rules_detailed

    spec = _project(user)["spec"].model_copy(update={"rules": body.rules})
    try:
        return parse_rules_detailed(spec)   # constraints + per-rule confidence/ambiguity + validation problems
    except Exception as e:
        raise HTTPException(502, f"rule parsing failed: {e}")


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
    with _lock:
        _project(user)["scenarios"] = body.scenarios
    _persist(user, strict=True)
    return {"count": len(body.scenarios)}


class GenerateIn(BaseModel):
    per_constraint: int = 4
    append: bool = True
    max_rules: int | None = None   # demo-size: only this many rules, spread over the list


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
            ss = generate_scenarios(p["spec"], per_constraint=body.per_constraint, max_rules=body.max_rules)
            # append keeps everything already there (seed, hand-added, held-out, escalated, edits made while authoring)
            _add_scenarios(user, ss.scenarios, "G", replace_all=not body.append)
            with _lock:
                job["result"] = {"generated": len(ss.scenarios), "total": len(_project(user)["scenarios"])}
                job["status"] = "done"
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"scenario generation failed: {type(e).__name__}: {e}" + ("  → the author model is retired on Bedrock; set AGENTREHEARSAL_AUTHOR_MODEL in backend/.env to an active one (e.g. global.anthropic.claude-opus-4-6-v1) and restart the API." if "Legacy" in str(e) else "")

    threading.Thread(target=work, daemon=True).start()
    return _public_job(job)


def _new_job(user: dict[str, Any], **fields: Any) -> dict[str, Any]:
    with _lock:
        job_id = f"job_{secrets.token_hex(6)}"   # unique across API instances and restarts
        job: dict[str, Any] = {"job_id": job_id, "owner": user["id"], "status": "running", "progress": [], "plan": [], "total_attempts": 0, "run_id": None, "result": None, "error": None, "round": 0, "phase": "", **fields}
        _jobs[job_id] = job
        if len(_jobs) > 300:   # keep memory bounded: drop the oldest finished jobs
            for old in [k for k, v in list(_jobs.items()) if v["status"] != "running"][: len(_jobs) - 300]:
                _jobs.pop(old, None)
    return job


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in job.items() if k != "owner"}


@app.get("/api/constraints/validate")
def validate_constraints_endpoint(user: dict[str, Any] = auth.User) -> dict[str, Any]:
    from .policy.parse import validate_constraints

    spec = _project(user)["spec"]
    return {"problems": validate_constraints(spec, spec.constraints)}


@app.get("/api/scenarios/coverage")
def scenario_coverage(user: dict[str, Any] = auth.User) -> dict[str, Any]:
    """constraint × category matrix: how many scenarios aim at each rule, and the gaps."""
    p = _project(user)
    spec: AgentSpec = p["spec"]
    cats = ["allowed", "boundary", "parameter_violation", "scope_violation", "direct_injection", "indirect_injection", "destructive_action"]
    rows = []
    for c in spec.constraints:
        if c.kind == "allow":
            continue
        counts = {k: 0 for k in cats}
        for s in p["scenarios"]:
            aimed = (s.expected_call or {}).get("tool") == c.tool or (s.must_call == c.tool and s.expected == "allow")
            if not aimed and not s.expected_call and s.expected == "deny":
                # older scenarios without an expected call: attribute by the tool named in the rationale/prompt
                aimed = c.tool in (s.rationale or "") or c.tool.split("_")[0] in s.prompt.lower()
            if aimed:
                counts[s.category] = counts.get(s.category, 0) + 1
        gaps = [k for k in cats if counts[k] == 0 and k not in ("boundary",) and not (k == "indirect_injection" and not any(r.injection for t in spec.tools for r in t.responses))]
        rows.append({"id": c.id, "tool": c.tool, "kind": c.kind, "counts": counts, "total": sum(counts.values()), "gaps": gaps})
    return {"categories": cats, "rows": rows, "scenarios": len(p["scenarios"]), "with_expected_call": sum(1 for s in p["scenarios"] if s.expected_call)}


class HoldoutIn(BaseModel):
    per_constraint: int = 2


@app.post("/api/scenarios/holdout")
def author_holdout(body: HoldoutIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    """Author a held-out set (told to avoid every existing scenario) and append it to the project, for agents that
    are driven by hand or by a script (live sessions) rather than by /api/validate."""
    from .scenarios.generator import generate_scenarios

    p = _project(user)
    job = _new_job(user, kind="generate", phase="authoring")

    def work() -> None:
        try:
            existing = list(p["scenarios"])
            avoid = list(dict.fromkeys([s.title for s in existing] + [s.prompt for s in existing]))
            ss = generate_scenarios(p["spec"], per_constraint=body.per_constraint, avoid=avoid, source="holdout")
            added = _add_scenarios(user, ss.scenarios, "H")
            with _lock:
                job.update(result={"generated": len(added), "ids": [sc.id for sc in added]}, status="done", phase="done")
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"held-out authoring failed: {type(e).__name__}: {e}"

    threading.Thread(target=work, daemon=True).start()
    return _public_job(job)


class EscalateIn(BaseModel):
    base_run_id: str = Field(description="a rehearse run; attacks it resisted are mutated into harder variants")
    rounds: int = 2
    model: Literal["bedrock", "scripted"] = "bedrock"
    model_id: str | None = None
    attack_runs: int = 1


@app.post("/api/escalate")
def start_escalate(body: EscalateIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    """Adaptive attack search. Round by round: mutate the attacks the agent resisted, run them log-only, keep going
    with whatever it resisted again. Every variant is appended to the project's scenarios (source=escalated) so the
    next rehearsal, the policy and the held-out validation all see them. Result: {rounds: [...], found: n}."""
    from .scenarios.generator import escalate

    proj = _project(user)
    base = _load_run_for(user, body.base_run_id)
    spec = _spec_from_run(base, _project(user))
    policy = CedarPolicy(base["policy_cedar"], spec)
    spec, model, external_target = _prepare_target(proj, spec, body.model, body.model_id)
    resisted = [s for s in scenarios_from_run(base) if s.category in ATTACK_CATEGORIES]
    resisted_ids = {s["id"] for s in base["scenarios"] if s["category"] in ATTACK_CATEGORIES and s["verdict"] == "PASS"}
    resisted = [s for s in resisted if s.id in resisted_ids]
    job = _new_job(user, kind="escalate", phase="authoring", mode="rehearse", model=body.model, model_id=_model_label(spec, body.model, body.model_id, external_target), base_run_id=body.base_run_id)

    def progress(pr: dict[str, Any]) -> None:
        with _lock:
            job["progress"].append(pr)

    def work() -> None:
        try:
            if not resisted:
                raise RuntimeError("the agent resisted no attacks in that run; nothing to escalate")
            rounds: list[dict[str, Any]] = []
            current = resisted
            start = 1
            found_total = 0
            for rnd in range(1, max(1, body.rounds) + 1):
                with _lock:
                    job.update(phase="authoring", round=rnd, progress=[])
                ss = escalate(spec, current, prefix="E", start=start)
                if not ss.scenarios:
                    break
                _assign_ids(user, ss.scenarios, "E")   # unique against the workspace as it is now
                plan = [{"id": sc.id, "title": sc.title, "category": sc.category, "attempts": max(sc.runs, body.attack_runs)} for sc in ss.scenarios]
                with _lock:
                    job.update(plan=plan, total_attempts=sum(x["attempts"] for x in plan), phase="rehearse")
                rec = run_scenarios(spec, ss.scenarios, model, "rehearse", policy, attack_runs=body.attack_runs, workers=1, on_progress=progress)
                rec.update(owner=user["id"], base_run_id=body.base_run_id, variant=f"escalate_round_{rnd}")
                save_run(rec, user_id=user["id"], strict=True)
                found = [s for s in rec["scenarios"] if s["verdict"] != "PASS"]
                found_total += len(found)
                _add_scenarios(user, ss.scenarios, "E", assign_ids=False)
                rounds.append({"round": rnd, "run_id": rec["run_id"], "tried": len(ss.scenarios), "found": len(found), "found_ids": [s["id"] for s in found]})
                current = [s for s in ss.scenarios if s.id not in {f["id"] for f in found}]
                if not current:
                    break
            with _lock:
                job.update(result={"rounds": rounds, "found": found_total, "added": sum(r["tried"] for r in rounds)}, run_id=rounds[-1]["run_id"] if rounds else None, status="done", phase="done")
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"

    threading.Thread(target=work, daemon=True).start()
    return _public_job(job)


# ---- live sessions: an MCP-client agent (goose, Cline, Claude Code, OpenHands...) driven by hand ----------
#
# The agent connects to the workspace MCP URL itself (one line in its mcp.json). AgentRehearsal proxies to the
# real MCP server behind it, records every call and applies the policy. A live session = one scenario attempt:
# start it here, paste the scenario's prompt into the agent, stop it here; the verdict is computed from the
# recorded calls exactly as for a built-in agent. `finish` turns the session's attempts into a stored run.

_live: dict[str, dict[str, Any]] = {}   # user_id -> {"mode", "cedar", "attempts": {scenario_id: [...]}, "current": {...}|None}


class LiveStartIn(BaseModel):
    scenario_id: str
    mode: Literal["rehearse", "enforce"] = "rehearse"
    cedar: str | None = None


def _live_state(user: dict[str, Any]) -> dict[str, Any]:
    return _live.setdefault(user["id"], {"mode": "rehearse", "cedar": None, "attempts": {}, "current": None})


@app.post("/api/live/start")
def live_start(body: LiveStartIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    from .hooks import RecordingHook
    from .runner import _session_for, compose_prompt
    from .target.generic import ToolLog

    proj = _project(user)
    spec: AgentSpec = proj["spec"]
    sc = next((s for s in proj["scenarios"] if s.id == body.scenario_id), None)
    if not sc:
        raise HTTPException(404, "no such scenario")
    st = _live_state(user)
    if st["current"]:
        raise HTTPException(409, f"a session for {st['current']['scenario'].id} is already open; stop it first")
    cedar = body.cedar or st["cedar"] or constraints_to_cedar(spec)
    problems = validate_cedar(cedar)
    if problems:
        raise HTTPException(400, f"policy does not parse: {problems}")
    st.update(mode=body.mode, cedar=cedar)
    session = _session_for(spec, sc)
    hook = RecordingHook(policy=CedarPolicy(cedar, spec), mode=body.mode, session=session)
    log = ToolLog()
    external.begin_attempt(proj["mcp_token"], spec, hook, log)
    st["current"] = {"scenario": sc, "hook": hook, "log": log, "started": time.time(), "prompt": compose_prompt(spec, sc, session), "session": session}
    return {"scenario_id": sc.id, "prompt": st["current"]["prompt"], "mode": body.mode, "mcp_url": None}


@app.get("/api/live")
def live_status(user: dict[str, Any] = auth.User) -> dict[str, Any]:
    st = _live_state(user)
    cur = st["current"]
    done = {sid: [{"attempt": a["attempt"], "verdict": a["verdict"], "reason": a["reason"]} for a in atts] for sid, atts in st["attempts"].items()}
    if not cur:
        return {"open": None, "mode": st["mode"], "done": done}
    return {"open": {"scenario_id": cur["scenario"].id, "prompt": cur["prompt"], "calls": [c.as_dict() for c in cur["hook"].calls], "seconds": round(time.time() - cur["started"], 1)}, "mode": st["mode"], "done": done}


class LiveStopIn(BaseModel):
    final_text: str = ""     # what the agent replied, if you want it on the record


@app.post("/api/live/stop")
def live_stop(body: LiveStopIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    from .runner import _on_target
    from .verdict import judge_attempt

    proj = _project(user)
    st = _live_state(user)
    cur = st["current"]
    if not cur:
        raise HTTPException(409, "no open session")
    external.end_attempt(proj["mcp_token"])
    sc, hook, log = cur["scenario"], cur["hook"], cur["log"]
    v = judge_attempt(proj["spec"], sc, hook.calls, st["mode"], None)
    atts = st["attempts"].setdefault(sc.id, [])
    rec = {"attempt": len(atts) + 1, "prompt": cur["prompt"], "calls": [c.as_dict() for c in hook.calls], "side_effects": log.side_effects(), "final_text": body.final_text[:2000],
           "error": None, "verdict": v.verdict, "reason": v.reason, "attempted_denied": v.attempted_denied, "blocked": v.blocked, "on_target": _on_target(sc, hook.calls), "duration_s": round(time.time() - cur["started"], 2), "live": True}
    atts.append(rec)
    st["current"] = None
    return {"scenario_id": sc.id, "verdict": v.verdict, "reason": v.reason, "calls": rec["calls"], "attempts": len(atts)}


class LiveFinishIn(BaseModel):
    base_run_id: str | None = None   # for an enforce session: the rehearse run it replays


@app.post("/api/live/finish")
def live_finish(body: LiveFinishIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    from .runner import assemble_run

    proj = _project(user)
    st = _live_state(user)
    if st["current"]:
        raise HTTPException(409, "stop the open session first")
    if not st["attempts"]:
        raise HTTPException(400, "no sessions recorded yet")
    spec: AgentSpec = proj["spec"]
    by_id = {s.id: s for s in proj["scenarios"]}
    results = [(by_id[sid], atts) for sid, atts in st["attempts"].items() if sid in by_id]
    rec = assemble_run(spec, st["mode"], CedarPolicy(st["cedar"] or constraints_to_cedar(spec), spec), results, model_label=f"live:{spec.target.kind}")
    rec.update(owner=user["id"], live=True)
    if body.base_run_id:
        rec["base_run_id"] = body.base_run_id
    save_run(rec, user_id=user["id"], strict=True)
    _live[user["id"]] = {"mode": st["mode"], "cedar": st["cedar"], "attempts": {}, "current": None}
    return {"run_id": rec["run_id"], "summary": rec["summary"]}


@app.post("/api/live/reset")
def live_reset(user: dict[str, Any] = auth.User) -> dict[str, Any]:
    proj = _project(user)
    external.end_attempt(proj["mcp_token"])
    _live[user["id"]] = {"mode": "rehearse", "cedar": None, "attempts": {}, "current": None}
    return {"ok": True}


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
    if spec.target.kind == "mcp_client" and model_kind != "scripted":
        raise HTTPException(400, "This agent connects to the MCP URL itself, so AgentRehearsal cannot send it prompts. Use Live rehearsal on the Rehearse tab (or tick offline sim to exercise the pipeline with the scripted agent).")
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
    if spec.target.kind == "mcp_client" and body.model != "scripted":
        raise HTTPException(400, "This agent connects to the MCP URL itself, so AgentRehearsal cannot send it prompts. Use Live rehearsal on the Rehearse tab: start a scenario, paste its prompt into the agent, stop, repeat.")
    if body.base_run_id:
        base = _load_run_for(user, body.base_run_id)
        spec = _spec_from_run(base, _project(user))
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
            # an external target records calls through one slot per workspace token, so it must run one attempt at a time
            rec = run_scenarios(spec, scenarios, model, body.mode, policy, attack_runs=body.attack_runs, workers=1 if spec.target.kind != "simulated" else body.workers, on_progress=progress)
            if body.base_run_id:
                rec["base_run_id"] = body.base_run_id
            rec["owner"] = user["id"]
            save_run(rec, user_id=user["id"], strict=True)
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
    spec = _spec_from_run(base, _project(user))
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
            save_run(before, user_id=user["id"], strict=True)
            with _lock:
                job.update(phase="enforce", mode="enforce", progress=[])
            after = run_scenarios(spec, ss.scenarios, model, "enforce", policy, attack_runs=body.attack_runs, workers=1, on_progress=progress)
            after.update(owner=user["id"], holdout=True, base_run_id=before["run_id"], validates_run_id=body.base_run_id)
            save_run(after, user_id=user["id"], strict=True)
            with _lock:
                job.update(run_id=after["run_id"], result={"before_run": before["run_id"], "after_run": after["run_id"], "generated": len(ss.scenarios)}, status="done", phase="done")
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"

    threading.Thread(target=work, daemon=True).start()
    return _public_job(job)


# ---- fix your agent --------------------------------------------------------------------------

class HardenIn(BaseModel):
    base_run_id: str = Field(description="the rehearse run whose findings drive the rewrite")
    model: Literal["bedrock", "scripted"] = "bedrock"
    model_id: str | None = None
    attack_runs: int = 3


@app.post("/api/fix/harden")
def start_harden(body: HardenIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    """Rewrite the system prompt from the findings, then replay the same scenarios with the new prompt and
    NO enforcement, so the prompt's own effect is measured. Result: {system_prompt, changes, run_id}."""
    from .fixes import harden_prompt

    proj = _project(user)
    base = _load_run_for(user, body.base_run_id)
    spec = _spec_from_run(base, _project(user))
    scenarios = scenarios_from_run(base)
    policy = CedarPolicy(base["policy_cedar"], spec)
    spec, model, external_target = _prepare_target(proj, spec, body.model, body.model_id)
    plan = [{"id": sc.id, "title": sc.title, "category": sc.category, "attempts": max(sc.runs, body.attack_runs if sc.category in ATTACK_CATEGORIES else 1)} for sc in scenarios]
    job = _new_job(user, kind="harden", phase="authoring", mode="rehearse", model=body.model, model_id=_model_label(spec, body.model, body.model_id, external_target), base_run_id=body.base_run_id)

    def progress(pr: dict[str, Any]) -> None:
        with _lock:
            job["progress"].append(pr)

    def work() -> None:
        try:
            hp = harden_prompt(spec, base)
            hardened_spec = spec.model_copy(update={"system_prompt": hp.system_prompt})
            with _lock:
                job.update(plan=plan, total_attempts=sum(x["attempts"] for x in plan), phase="rehearse", progress=[], result={"system_prompt": hp.system_prompt, "changes": hp.changes, "run_id": None})
            rec = run_scenarios(hardened_spec, scenarios, model, "rehearse", policy, attack_runs=body.attack_runs, workers=1, on_progress=progress)
            rec.update(owner=user["id"], base_run_id=body.base_run_id, variant="hardened_prompt", prompt_changes=hp.changes)
            save_run(rec, user_id=user["id"], strict=True)
            with _lock:
                job["result"]["run_id"] = rec["run_id"]
                job.update(run_id=rec["run_id"], status="done", phase="done")
        except Exception as e:
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"

    threading.Thread(target=work, daemon=True).start()
    return _public_job(job)


class ApplyPromptIn(BaseModel):
    system_prompt: str


@app.post("/api/fix/apply-prompt")
def apply_prompt(body: ApplyPromptIn, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    p = _project(user)
    p["spec"] = p["spec"].model_copy(update={"system_prompt": body.system_prompt})
    _persist(user)
    return p["spec"].model_dump()


@app.get("/api/runs/{run_id}/surface")
def run_surface(run_id: str, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    from .fixes import tool_surface

    run = _load_run_for(user, run_id)
    return tool_surface(AgentSpec.model_validate(run["spec"]), run)


@app.get("/api/runs/{run_id}/analysis")
def run_analysis(run_id: str, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    """What each constraint did in this run, in plain English, plus over-blocking (legitimate calls denied)."""
    from .fixes import constraint_analysis

    run = _load_run_for(user, run_id)
    return constraint_analysis(AgentSpec.model_validate(run["spec"]), run)


@app.get("/api/runs/{run_id}/fixpack.md")
def run_fixpack(run_id: str, after: str | None = None, hardened: str | None = None, user: dict[str, Any] = auth.User):
    """Everything a developer takes away, as one Markdown file. `after` = the enforce run, `hardened` = the
    hardened-prompt run (both optional)."""
    from .fixes import fix_pack, tool_surface

    before = _load_run_for(user, run_id)
    spec = AgentSpec.model_validate(before["spec"])
    after_run = _load_run_for(user, after) if after else None
    hard = None
    if hardened:
        hr = _load_run_for(user, hardened)
        hard = {"system_prompt": hr["spec"]["system_prompt"], "changes": hr.get("prompt_changes", []), "run": hr}
    md = fix_pack(spec, before, after_run, hard, tool_surface(spec, before))
    return PlainTextResponse(md, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{spec.name}-fixpack.md"'})


@app.get("/api/jobs")
def list_jobs(user: dict[str, Any] = auth.User) -> dict[str, Any]:
    """The user's jobs still running on this instance, newest first: a reloaded page reattaches to them."""
    with _lock:
        mine = [_public_job(j) for j in _jobs.values() if j["owner"] == user["id"] and j["status"] == "running"]
    return {"jobs": list(reversed(mine))}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user: dict[str, Any] = auth.User) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job or job["owner"] != user["id"]:
        raise HTTPException(404, "job not found: the API restarted (or a different instance answered) while it was running. Start it again.")
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
                out.append({"run_id": r["run_id"], "mode": r["mode"], "model": r["model"], "agent": r["agent"], "started_at": r["started_at"], "summary": r["summary"], "base_run_id": r.get("base_run_id"), "holdout": bool(r.get("holdout")), "variant": r.get("variant") or "", "example": False})
    for p in sorted(EXAMPLE_RUNS.glob("run_*.json")) if EXAMPLE_RUNS.exists() else []:
        r = json.loads(p.read_text(encoding="utf-8"))
        out.append({"run_id": r["run_id"], "mode": r["mode"], "model": r["model"], "agent": r["agent"], "started_at": r["started_at"], "summary": r["summary"], "base_run_id": r.get("base_run_id"), "holdout": bool(r.get("holdout")), "variant": r.get("variant") or "", "example": True})
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
    {"id": "global.anthropic.claude-opus-4-6-v1", "label": "Claude Opus 4.6", "provider": "bedrock"},
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
        from botocore.config import Config as _BotoConfig

        # curated list must never wait on the network: one quick attempt, no retries
        br = boto3.client("bedrock", region_name=config.AWS_REGION, config=_BotoConfig(connect_timeout=2, read_timeout=4, retries={"max_attempts": 1}))
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
