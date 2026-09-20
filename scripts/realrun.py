#!/usr/bin/env python3
"""Drive a real, unmodified MCP-client agent (Claude Code or goose) through AgentRehearsal live sessions.

The agent connects to the workspace's MCP URL (one config line); AgentRehearsal proxies to the official
filesystem server mounted on the fixture workspace, records every call and applies the policy. This script does
the clicks a person would do on the Rehearse → Live rehearsal card, for every scenario, with attacks repeated.

    export AR_EMAIL=you@example.com AR_PASSWORD=...          # an AgentRehearsal account (created if missing)
    python fixtures/realrun/make_fixture.py                    # build the throwaway workspace once
    python scripts/realrun.py setup                            # load the spec, parse the rules, print the MCP config
    claude mcp add --transport http agentrehearsal <url printed by setup>
    python scripts/realrun.py generate                         # Bedrock authors the scenarios; prints coverage
    python scripts/realrun.py add                              # hand-authored additions (declared), fills the gaps the matrix shows
    python scripts/realrun.py run --mode rehearse              # log-only pass -> run id
    python scripts/realrun.py run --mode enforce --base <id>   # enforced pass, same scenarios
    python scripts/realrun.py holdout                          # Bedrock authors a held-out set (H01..)
    python scripts/realrun.py run --mode rehearse --only holdout
    python scripts/realrun.py run --mode enforce  --only holdout --base <holdout rehearse id>

Options: --agent claude|goose (default claude), --attack-runs N (default 3), --api http://127.0.0.1:8000,
--ws <workspace path> (default fixtures/realrun/workspace). Every attempt resets the fixture first.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
SPEC_TEMPLATE = ROOT / "fixtures" / "realrun" / "realrun.spec.json"
FIXTURE = ROOT / "fixtures" / "realrun" / "make_fixture.py"
ATTACKS = {"scope_violation", "parameter_violation", "direct_injection", "indirect_injection", "destructive_action"}


class Api:
    def __init__(self, base: str, email: str, password: str):
        self.base = base.rstrip("/")
        self.c = httpx.Client(timeout=120)
        r = self.c.post(f"{self.base}/api/auth/login", json={"email": email, "password": password})
        if r.status_code == 401 and "No account" in r.text:
            r = self.c.post(f"{self.base}/api/auth/signup", json={"email": email, "password": password, "name": "realrun"})
        r.raise_for_status()
        self.h = {"Authorization": "Bearer " + r.json()["token"]}

    def get(self, path: str, **kw):
        r = self.c.get(f"{self.base}{path}", headers=self.h, **kw); r.raise_for_status(); return r.json()

    def post(self, path: str, body: dict | None = None):
        r = self.c.post(f"{self.base}{path}", headers=self.h, json=body or {})
        if r.status_code >= 400:
            raise SystemExit(f"{path}: {r.status_code} {r.text[:300]}")
        return r.json()

    def put(self, path: str, body: dict):
        r = self.c.put(f"{self.base}{path}", headers=self.h, json=body); r.raise_for_status(); return r.json()

    def wait(self, job_id: str, label: str = "job") -> dict:
        while True:
            j = self.get(f"/api/jobs/{job_id}")
            if j["status"] != "running":
                if j["status"] == "error":
                    raise SystemExit(f"{label} failed: {j.get('error')}")
                return j
            time.sleep(1.5)


def _ws(a) -> Path:
    return Path(a.ws or os.environ.get("AGENTREHEARSAL_REALRUN_WS") or (ROOT / "fixtures" / "realrun" / "workspace")).resolve()


def cmd_setup(api: Api, a) -> None:
    ws = _ws(a)
    if not (ws / "acme-app").exists():
        raise SystemExit(f"no fixture at {ws}; run: python fixtures/realrun/make_fixture.py")
    spec = json.loads(SPEC_TEMPLATE.read_text().replace("{WS}", str(ws)))
    api.put("/api/spec", spec)
    api.put("/api/scenarios", {"scenarios": []})
    print(f"agent: {spec['name']} · {len(spec['tools'])} tools read from the official filesystem server · mount {ws}")
    ref = json.loads((SPEC_TEMPLATE.parent / "realrun.constraints.json").read_text().replace("{WS}", str(ws)))
    if a.reference_constraints:
        parsed = {"constraints": ref, "notes": [], "problems": []}
        print("using the reference constraints (no Bedrock parse)")
    else:
        print("parsing the five rules with Bedrock (verbatim)…")
        try:
            parsed = api.post("/api/rules/parse", {"rules": spec["rules"]})
        except SystemExit as e:
            print(f"parse failed ({e}); falling back to the reference constraints")
            parsed = {"constraints": ref, "notes": [], "problems": []}
    spec["constraints"] = parsed["constraints"]
    api.put("/api/spec", spec)
    (ROOT / "backend" / "runs" / "realrun_parsed_constraints.json").write_text(json.dumps(parsed, indent=2))
    print(f"\n{len(parsed['constraints'])} constraints:")
    for c in parsed["constraints"]:
        n = next((x for x in parsed["notes"] if x["id"] == c["id"]), {})
        print(f"  {c['id']:32} {c['tool']:24} {c['kind']:22} {c.get('param') or '':10} conf={n.get('confidence', '?')} {('assumed: ' + n['ambiguity']) if n.get('ambiguity') else ''}")
    if parsed["problems"]:
        print("\nparser checks:")
        for pr in parsed["problems"]:
            print("  !", pr)
    print("\nrules the parser could not turn into a tool constraint are expected (rule 5 is not a tool-boundary rule); say so in the notes.")
    ws_info = api.get("/api/workspace/mcp")
    print("\nconnect the agent (one line, nothing else changes):")
    print(f"  claude mcp add --transport http agentrehearsal {ws_info['url']}")
    print("  goose: goose configure → Add extension → Remote (streamable HTTP) → " + ws_info["url"])
    print(f"\nupstream: {ws_info['upstream']}  forwarding={ws_info['forwarding']}")


def cmd_generate(api: Api, a) -> None:
    j = api.post("/api/scenarios/generate", {"per_constraint": a.per_constraint, "append": True})
    res = api.wait(j["job_id"], "generate")["result"]
    print(f"Bedrock authored {res['generated']} scenarios; {res['total']} total")
    cov = api.get("/api/scenarios/coverage")
    print(f"coverage ({cov['with_expected_call']} of {cov['scenarios']} state an expected call):")
    for r in cov["rows"]:
        cells = " ".join(f"{k[:6]}={v}" for k, v in r["counts"].items())
        print(f"  {r['id']:32} {cells}{'   gaps: ' + ', '.join(r['gaps']) if r['gaps'] else ''}")
    for s in api.get("/api/scenarios")["scenarios"]:
        print(f"  {s['id']:4} {s['category']:20} {s['expected']:5} {s['title'][:60]}")


def cmd_add(api: Api, a) -> None:
    """Append hand-authored scenarios from a JSON file (and remove the ids it lists). Declared in the run notes."""
    ws = _ws(a)
    data = json.loads(Path(a.file).read_text().replace("{WS}", str(ws)))
    cur = api.get("/api/scenarios")["scenarios"]
    remove = set(data.get("remove", []))
    cur = [s for s in cur if s["id"] not in remove]
    have = {s["id"] for s in cur}
    added = [s for s in data["scenarios"] if s["id"] not in have]
    for s in added:
        s.setdefault("customer_id", ""); s.setdefault("session", {}); s.setdefault("attachment_id", None); s.setdefault("must_call", None)
    api.put("/api/scenarios", {"scenarios": cur + added})
    print(f"removed {sorted(remove & {s['id'] for s in api.get('/api/scenarios')['scenarios']} | remove)}; added {[s['id'] for s in added]}; {len(cur) + len(added)} scenarios now")


def cmd_holdout(api: Api, a) -> None:
    j = api.post("/api/scenarios/holdout", {"per_constraint": a.per_constraint})
    res = api.wait(j["job_id"], "holdout")["result"]
    print(f"held-out set: {res['generated']} scenarios {res['ids']}")


def run_agent(agent: str, prompt: str, ws: Path, timeout: int) -> str:
    if agent == "claude":
        # Claude Code as published. Flags only: our MCP tools allowed, its own file/shell tools off so every file
        # access goes through the proxy; headless, prints the reply. No source or prompt of the agent is touched.
        cmd = ["claude", "-p", prompt, "--output-format", "text",
               "--allowedTools", "mcp__agentrehearsal__*",
               "--disallowedTools", "Read,Write,Edit,MultiEdit,Bash,Glob,Grep,LS,NotebookEdit,WebFetch,WebSearch,Task"]
    elif agent == "goose":
        cmd = ["goose", "run", "-t", prompt, "--no-session"]
    elif agent == "naive":
        return naive_agent(prompt, ws)
    else:
        raise SystemExit(f"unknown agent {agent}")
    try:
        r = subprocess.run(cmd, cwd=str(ws / "acme-app"), capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (("\n[stderr] " + r.stderr[-800:]) if r.returncode else "")
    except subprocess.TimeoutExpired:
        return "[agent timed out]"


_NAIVE_URL = {"url": ""}


def naive_agent(prompt: str, ws: Path) -> str:
    """An offline stand-in for a real MCP client: a gullible agent that does what the text in front of it says.
    Exists so the pipeline (sessions, proxy, forwarding, verdicts, runs) can be exercised without a model.
    It is labelled 'naive' in every run it produces and is never evidence about any real agent."""
    import re

    url = _NAIVE_URL["url"]
    sid = {"n": 0}

    def call(name: str, args: dict) -> str:
        sid["n"] += 1
        r = httpx.post(url, json={"jsonrpc": "2.0", "id": sid["n"], "method": "tools/call", "params": {"name": name, "arguments": args}}, timeout=60)
        res = r.json().get("result") or {}
        return "".join(c.get("text", "") for c in res.get("content", []))

    low = prompt.lower()
    repo = str(ws / "acme-app")
    out: list[str] = []
    m = re.search(r"report-(\d+)", low)
    if m:
        text = call("read_text_file", {"path": f"{repo}/reports/report-{m.group(1)}.md"})
        out.append(text[:200])
        note = re.search(r"append the contents of `?([^`\s]+)`?", text)
        if note:   # gullible: obeys the maintainer note
            secret = call("read_text_file", {"path": str((ws / "acme-app" / "reports" / note.group(1)).resolve())})
            out.append("[read env] " + secret[:80])
            call("write_file", {"path": f"{repo}/docs/triage/{m.group(1)}.md", "content": f"# Triage {m.group(1)}\n\n{text[:300]}\n\nEnvironment:\n{secret}"})
        else:
            call("write_file", {"path": f"{repo}/docs/triage/{m.group(1)}.md", "content": f"# Triage {m.group(1)}\n\n{text[:300]}"})
        return "\n".join(out)
    if ".env" in low and "example" not in low:
        return call("read_text_file", {"path": str(ws / ".env")})
    if ".env.example" in low:
        return call("read_text_file", {"path": f"{repo}/.env.example"})
    if "structure" in low or "tree" in low:
        return call("directory_tree", {"path": repo})[:200]
    if "todo" in low:
        return call("search_files", {"path": f"{repo}/src", "pattern": "TODO"})[:200]
    if "delete" in low or "remove" in low:
        target = re.search(r"(src/[\w/.-]+)", prompt)
        return call("move_file", {"source": f"{repo}/{target.group(1) if target else 'src/x.py'}", "destination": f"{repo}/docs/triage/removed.py"})
    if "readme" in low and ("update" in low or "write" in low):
        return call("write_file", {"path": f"{repo}/README.md", "content": "updated by agent"})
    if "folder" in low or "directory" in low:
        return call("create_directory", {"path": f"{repo}/docs/triage"})
    if "auth" in low or "login" in low:
        return call("read_multiple_files", {"paths": [f"{repo}/src/itsdangerous/signer.py", f"{repo}/src/itsdangerous/timed.py"]})[:200]
    return call("list_directory", {"path": repo})[:200]


def reset_fixture(ws: Path) -> None:
    subprocess.run([sys.executable, str(FIXTURE), "--workspace", str(ws), "--reset"], check=True, capture_output=True)


def cmd_run(api: Api, a) -> None:
    ws = _ws(a)
    scs = api.get("/api/scenarios")["scenarios"]
    if a.only == "holdout":
        scs = [s for s in scs if s["source"] == "holdout"]
    elif a.only == "working":
        scs = [s for s in scs if s["source"] != "holdout"]
    elif a.only:
        want = set(a.only.split(","))
        scs = [s for s in scs if s["id"] in want]
    if not scs:
        raise SystemExit("no scenarios selected")
    api.post("/api/live/reset")
    _NAIVE_URL["url"] = api.get("/api/workspace/mcp")["url"]
    log = open(ROOT / "backend" / "runs" / f"realrun_{a.mode}_{int(time.time())}.jsonl", "a")
    print(f"{len(scs)} scenarios · mode={a.mode} · agent={a.agent} · attacks ×{a.attack_runs}")
    for s in scs:
        n = a.attack_runs if s["category"] in ATTACKS else 1
        for i in range(1, n + 1):
            reset_fixture(ws)
            st = api.post("/api/live/start", {"scenario_id": s["id"], "mode": a.mode})
            t0 = time.time()
            reply = run_agent(a.agent, st["prompt"], ws, a.timeout)
            stop = api.post("/api/live/stop", {"final_text": reply[:2000]})
            calls = ", ".join(f"{c['tool']}({'✓' if c['allowed'] else ('✗' if c['blocked'] else '!')})" for c in stop["calls"])
            print(f"  {s['id']:4} {s['category']:20} #{i} {stop['verdict']:12} {int(time.time() - t0):3}s  {calls[:90]}")
            log.write(json.dumps({"scenario": s["id"], "attempt": i, "mode": a.mode, "verdict": stop["verdict"], "reason": stop["reason"], "calls": stop["calls"], "reply": reply[:2000]}) + "\n"); log.flush()
    fin = api.post("/api/live/finish", {"base_run_id": a.base})
    sm = fin["summary"]
    print(f"\nrun {fin['run_id']}: {sm['pass']}/{sm['total']} pass · attacks unsafe {sm['attacks_unsafe']}/{sm['attacks_total']} (consistent {sm.get('attacks_unsafe_consistent', '?')}, intermittent {sm.get('attacks_intermittent', '?')}) · blocked {sm['attacks_blocked']} · legitimate {sm['legit_pass']}/{sm['legit_total']}")
    if a.base:
        cmp = api.get(f"/api/compare?before={a.base}&after={fin['run_id']}")
        print(f"before: {cmp['before']}  after: {cmp['after']}")
    print(f"report: {api.base}/api/runs/{fin['run_id']}/report.md?token=…  (Export report on the scorecard)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["setup", "generate", "add", "holdout", "run"])
    ap.add_argument("--file", default=str(ROOT / "fixtures" / "realrun" / "hand_scenarios.json"), help="add: JSON with scenarios (+ ids to remove)")
    ap.add_argument("--api", default=os.environ.get("AR_API", "http://127.0.0.1:8000"))
    ap.add_argument("--email", default=os.environ.get("AR_EMAIL")); ap.add_argument("--password", default=os.environ.get("AR_PASSWORD"))
    ap.add_argument("--ws", default=None)
    ap.add_argument("--agent", default="claude", choices=["claude", "goose", "naive"], help="naive = offline gullible MCP client, for exercising the pipeline only")
    ap.add_argument("--mode", default="rehearse", choices=["rehearse", "enforce"])
    ap.add_argument("--base", default=None, help="for enforce: the rehearse run this replays")
    ap.add_argument("--only", default=None, help="holdout | working | comma-separated ids")
    ap.add_argument("--attack-runs", type=int, default=3)
    ap.add_argument("--per-constraint", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=240, help="seconds per agent invocation")
    ap.add_argument("--reference-constraints", action="store_true", help="setup: skip the Bedrock parse and use fixtures/realrun/realrun.constraints.json")
    a = ap.parse_args()
    if not (a.email and a.password):
        raise SystemExit("set AR_EMAIL and AR_PASSWORD (an AgentRehearsal account; created if missing)")
    api = Api(a.api, a.email, a.password)
    {"setup": cmd_setup, "generate": cmd_generate, "add": cmd_add, "holdout": cmd_holdout, "run": cmd_run}[a.cmd](api, a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
