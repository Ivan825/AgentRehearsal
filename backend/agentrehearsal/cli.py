"""Command line: rehearse, replay, demo, validate, policy, generate."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import config
from .models.factory import target_model
from .policy.cedar import CedarPolicy, constraints_to_cedar, validate_cedar
from .runner import compare, load_run, run_scenarios, save_run, scenarios_from_run
from .scenarios.schema import ScenarioSet, seeds_path
from .spec import AgentSpec

console = Console()
STYLE = {"PASS": "green", "FAIL": "red", "INTERMITTENT": "yellow", "ERROR": "magenta"}


def _print_run(rec: dict) -> None:
    t = Table(title=f"{rec['agent']}  |  mode={rec['mode']}  |  model={rec['model']}  |  {rec['run_id']}")
    t.add_column("ID")
    t.add_column("Category")
    t.add_column("Scenario")
    t.add_column("Verdict")
    t.add_column("Why", overflow="fold")
    for s in rec["scenarios"]:
        v = s["verdict"]
        t.add_row(s["id"], s["category"], s["title"], f"[{STYLE.get(v, 'white')}]{v}[/]", s["reason"])
    console.print(t)
    sm = rec["summary"]
    console.print(
        f"Overall [bold]{sm['pass']}/{sm['total']} PASS[/]   "
        f"attacks unsafe: [red]{sm['attacks_unsafe']}[/]/{sm['attacks_total']}   "
        f"attacks blocked: [green]{sm['attacks_blocked']}[/]   "
        f"legitimate tasks passing: [green]{sm['legit_pass']}[/]/{sm['legit_total']}"
    )


def _print_compare(c: dict) -> None:
    t = Table(title="Before -> After (same scenarios, policy enforced)")
    t.add_column("ID"); t.add_column("Category"); t.add_column("Scenario"); t.add_column("Before"); t.add_column("After")
    for s in c["scenarios"]:
        b, a = s["before"], s["after"] or "-"
        t.add_row(s["id"], s["category"], s["title"], f"[{STYLE.get(b,'white')}]{b}[/]", f"[{STYLE.get(a,'white')}]{a}[/]")
    console.print(t)
    b, a = c["before"], c["after"]
    console.print(f"BEFORE  {b['pass']}/{b['total']} pass, {b['unsafe']} unsafe actions succeeded, legitimate {b['legit_pass']}/{b['legit_total']}")
    console.print(f"AFTER   {a['pass']}/{a['total']} pass, {a['blocked']} unsafe actions blocked, {a['unsafe']} still unsafe, legitimate {a['legit_pass']}/{a['legit_total']}")


def _load_scenarios(path: str | None) -> list:
    return ScenarioSet.load(path or seeds_path()).scenarios


def cmd_policy(a: argparse.Namespace) -> int:
    spec = AgentSpec.load(a.spec)
    text = constraints_to_cedar(spec, a.agentcore_target, a.gateway_arn)
    problems = validate_cedar(text)
    print(text)
    if problems:
        console.print(f"[red]Policy does not parse:[/] {problems}")
        return 1
    console.print("[green]Policy parses.[/]")
    return 0


def cmd_rehearse(a: argparse.Namespace) -> int:
    spec = AgentSpec.load(a.spec)
    scenarios = _load_scenarios(a.scenarios)
    model = target_model(a.model, a.model_id or spec.model_id or None)
    policy = CedarPolicy.from_spec(spec)
    with console.status("Rehearsing..."):
        rec = run_scenarios(spec, scenarios, model, "rehearse", policy, attack_runs=a.runs, workers=a.workers,
                            on_progress=lambda p: console.log(f"{p['scenario_id']} #{p['attempt']} {p['verdict']}"), tools=a.tools)
    p = save_run(rec, Path(a.out) if a.out else None)
    _print_run(rec)
    console.print(f"saved {p}")
    return 0


def cmd_replay(a: argparse.Namespace) -> int:
    before = load_run(a.run)
    spec = AgentSpec.model_validate(before["spec"])
    scenarios = scenarios_from_run(before)
    model = target_model(a.model, a.model_id or spec.model_id or None)
    policy = CedarPolicy(Path(a.policy).read_text() if a.policy else before["policy_cedar"], spec)
    with console.status("Replaying with enforcement..."):
        after = run_scenarios(spec, scenarios, model, "enforce", policy, attack_runs=a.runs, workers=a.workers, tools=a.tools)
    p = save_run(after, Path(a.out) if a.out else None)
    _print_run(after)
    _print_compare(compare(before, after))
    console.print(f"saved {p}")
    return 0


def cmd_demo(a: argparse.Namespace) -> int:
    spec = AgentSpec.load(a.spec)
    scenarios = _load_scenarios(a.scenarios)
    model = target_model(a.model, a.model_id or spec.model_id or None)
    policy = CedarPolicy.from_spec(spec)
    console.rule("REHEARSE (policy in log-only mode)")
    before = run_scenarios(spec, scenarios, model, "rehearse", policy, attack_runs=a.runs, workers=a.workers, tools=a.tools)
    _print_run(before)
    console.rule("PROTECT (generated Cedar policy)")
    console.print(policy.text)
    console.rule("REPLAY (policy enforced, same scenarios)")
    after = run_scenarios(spec, scenarios, model, "enforce", policy, attack_runs=a.runs, workers=a.workers, tools=a.tools)
    _print_run(after)
    _print_compare(compare(before, after))
    out = Path(a.out) if a.out else None
    console.print(f"saved {save_run(before, out)} and {save_run(after, out)}")
    return 0


def cmd_generate(a: argparse.Namespace) -> int:
    from .scenarios.generator import generate_scenarios

    spec = AgentSpec.load(a.spec)
    avoid = [s.title for s in _load_scenarios(a.avoid)] + [s.prompt for s in _load_scenarios(a.avoid)] if a.avoid else []
    ss = generate_scenarios(spec, per_constraint=a.per_constraint, avoid=avoid)
    ss.save(a.out)
    console.print(f"wrote {len(ss.scenarios)} scenarios to {a.out}")
    return 0


def cmd_validate(a: argparse.Namespace) -> int:
    """Held-out validation: author scenarios the policy never saw, run them without and with enforcement.

    The replay proves the pipeline (the policy blocks what it was compiled from). This proves the policy
    generalises: fresh attacks, written after the policy existed, are blocked too, and fresh legitimate
    tasks still go through.
    """
    from .scenarios.generator import generate_scenarios

    base = load_run(a.run)
    spec = AgentSpec.model_validate(base["spec"])
    policy = CedarPolicy(base["policy_cedar"], spec)
    model = target_model(a.model, a.model_id or spec.model_id or None)
    avoid = [s["title"] for s in base["scenarios"]] + [s["prompt"] for s in base["scenarios"]]
    console.rule("AUTHOR held-out scenarios (never used to build the policy)")
    ss = generate_scenarios(spec, per_constraint=a.per_constraint, avoid=avoid, source="holdout")
    if not ss.scenarios:
        console.print("[red]no usable scenarios produced[/]")
        return 1
    for s in ss.scenarios:
        console.print(f"  {s.id}  {s.category:<20} {s.title}")
    console.rule("HELD-OUT, policy log-only")
    before = run_scenarios(spec, ss.scenarios, model, "rehearse", policy, attack_runs=a.runs, workers=a.workers, tools=a.tools)
    before.update(holdout=True, base_run_id=a.run)
    _print_run(before)
    console.rule("HELD-OUT, policy enforced")
    after = run_scenarios(spec, ss.scenarios, model, "enforce", policy, attack_runs=a.runs, workers=a.workers, tools=a.tools)
    after.update(holdout=True, base_run_id=before["run_id"], validates_run_id=a.run)
    _print_run(after)
    _print_compare(compare(before, after))
    out = Path(a.out) if a.out else None
    console.print(f"saved {save_run(before, out)} and {save_run(after, out)}")
    return 0


def cmd_report(a: argparse.Namespace) -> int:
    from .report import run_report

    run = load_run(a.run)
    before = load_run(a.before) if a.before else None
    text = run_report(run, before)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        console.print(f"wrote {a.out}")
    else:
        print(text)
    return 0


def cmd_doctor(a: argparse.Namespace) -> int:
    """Check everything a live run needs, and say exactly what is missing."""
    ok = True

    def row(name: str, good: bool, detail: str) -> None:
        nonlocal ok
        ok = ok and good
        console.print(f"[{'green' if good else 'red'}]{'OK ' if good else 'FAIL'}[/] {name:<28} {detail}")

    try:
        import cedarpy  # noqa: F401
        row("cedarpy", True, "local Cedar evaluation available")
    except Exception as e:
        row("cedarpy", False, str(e))
    try:
        import strands  # noqa: F401
        import importlib.metadata as m
        row("strands-agents", True, m.version("strands-agents"))
    except Exception as e:
        row("strands-agents", False, str(e))

    import boto3
    from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

    try:
        ident = boto3.client("sts", region_name=config.AWS_REGION).get_caller_identity()
        row("AWS credentials", True, f"account {ident['Account']} · region {config.AWS_REGION}")
    except (NoCredentialsError, BotoCoreError, ClientError) as e:
        row("AWS credentials", False, f"{type(e).__name__}: {e}. Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or run `aws configure`.")
        console.print("[yellow]Stopping here; fix credentials first.[/]")
        return 1

    for label, mid in (("target model", config.TARGET_MODEL_ID), ("author model", config.AUTHOR_MODEL_ID)):
        try:
            rt = boto3.client("bedrock-runtime", region_name=config.AWS_REGION)
            rt.converse(modelId=mid, messages=[{"role": "user", "content": [{"text": "Reply with the single word: ready"}]}], inferenceConfig={"maxTokens": 5})
            row(f"Bedrock {label}", True, mid)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            hint = "enable it under Bedrock > Model access, or pick another model id in .env" if code in ("AccessDeniedException", "ResourceNotFoundException", "ValidationException") else ""
            row(f"Bedrock {label}", False, f"{mid}: {code} {hint}")
        except Exception as e:
            row(f"Bedrock {label}", False, f"{mid}: {e}")

    row("Gateway (Path B)", True, config.GATEWAY_URL or "not configured (optional)")
    row("DynamoDB history", True, config.DDB_TABLE or "not configured (optional)")
    console.print("[green]Ready for a live run: python -m agentrehearsal.cli demo --model bedrock[/]" if ok else "[red]Fix the FAIL rows above.[/]")
    return 0 if ok else 1


def cmd_users(a: argparse.Namespace) -> int:
    """Account admin from the terminal: list users, or reset a password."""
    from .auth import hash_password
    from .store import get_store

    store = get_store()
    if a.action == "reset-password":
        if not a.email or not a.password:
            console.print("[red]usage: users reset-password --email you@x.io --password newpass[/]")
            return 1
        user = store.get_user_by_email(a.email)
        if not user:
            console.print(f"[red]no account for {a.email}[/]")
            return 1
        if len(a.password) < 8:
            console.print("[red]password must be at least 8 characters[/]")
            return 1
        user["password"] = hash_password(a.password)
        store.put_user(user)
        console.print(f"[green]password updated for {a.email}[/]")
        return 0
    if a.action == "list":
        if hasattr(store, "_read"):
            for email, u in store._read("users").items():
                console.print(f"{email}  created {u.get('created_at')}")
        else:
            console.print("listing is only available for the file store; use the DynamoDB console for the table")
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agentrehearsal", description="Crash-test your AI agent before your users do.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser, needs_spec: bool = True) -> None:
        if needs_spec:
            p.add_argument("--spec", default="examples/supportbot.spec.json")
        p.add_argument("--model", choices=["bedrock", "scripted"], default="bedrock")
        p.add_argument("--model-id", default=None)
        p.add_argument("--runs", type=int, default=3, help="attempts per attack scenario")
        p.add_argument("--workers", type=int, default=1, help="parallel attempts; keep 1 on macOS")
        p.add_argument("--tools", choices=["local", "gateway"], default="local", help="local mock tools, or the AgentCore Gateway (infra/README.md)")
        p.add_argument("--out", default=None, help=f"runs dir (default {config.RUNS_DIR})")

    p = sub.add_parser("policy", help="print the Cedar policy generated from the spec"); p.add_argument("--spec", default="examples/supportbot.spec.json")
    p.add_argument("--agentcore-target", default=None, help="render in AgentCore form for this Gateway target name"); p.add_argument("--gateway-arn", default=None); p.set_defaults(fn=cmd_policy)
    p = sub.add_parser("rehearse", help="run scenarios in log-only mode"); common(p); p.add_argument("--scenarios", default=None); p.set_defaults(fn=cmd_rehearse)
    p = sub.add_parser("replay", help="re-run a saved run with the policy enforced"); common(p, needs_spec=False); p.add_argument("--run", required=True); p.add_argument("--policy", default=None); p.set_defaults(fn=cmd_replay)
    p = sub.add_parser("demo", help="rehearse, then replay with enforcement, and compare"); common(p); p.add_argument("--scenarios", default=None); p.set_defaults(fn=cmd_demo)
    p = sub.add_parser("generate", help="author scenarios from the spec with Bedrock"); p.add_argument("--spec", default="examples/supportbot.spec.json"); p.add_argument("--out", default="examples/generated.scenarios.json"); p.add_argument("--per-constraint", type=int, default=4); p.add_argument("--avoid", default=None, help="existing scenario file; the author is told to write different ones"); p.set_defaults(fn=cmd_generate)
    p = sub.add_parser("validate", help="author held-out scenarios and run them against a saved run's policy, without and with enforcement"); common(p, needs_spec=False); p.add_argument("--run", required=True, help="the enforce (or rehearse) run whose policy is validated"); p.add_argument("--per-constraint", type=int, default=2); p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("report", help="write a Markdown report for a run"); p.add_argument("--run", required=True); p.add_argument("--before", default=None, help="the rehearse run this enforce run replays"); p.add_argument("--out", default=None); p.set_defaults(fn=cmd_report)
    p = sub.add_parser("doctor", help="check AWS credentials and Bedrock model access"); p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("users", help="list accounts or reset a password"); p.add_argument("action", choices=["list", "reset-password"]); p.add_argument("--email", default=None); p.add_argument("--password", default=None); p.set_defaults(fn=cmd_users)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
