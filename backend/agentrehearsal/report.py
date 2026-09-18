"""One-page Markdown report for a run (or a before/after pair). Exportable from the UI and the CLI."""
from __future__ import annotations

from typing import Any

from .runner import compare
from .scenarios.schema import ATTACK_CATEGORIES


def _fmt_call(c: dict[str, Any]) -> str:
    args = ", ".join(f"{k}={v!r}" if not isinstance(v, str) or len(v) < 40 else f"{k}=<{len(v)} chars>" for k, v in c["args"].items())
    return f"{c['tool']}({args})"


def run_report(run: dict[str, Any], before: dict[str, Any] | None = None) -> str:
    s = run["summary"]
    lines = [
        f"# AgentRehearsal report: {run['agent']}",
        "",
        f"Run `{run['run_id']}` · mode **{run['mode']}** · target model `{run['model']}` · tools `{run.get('tools', 'local')}` · {run['started_at'][:19]}Z",
        "",
        "## Scorecard",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Scenarios passing | {s['pass']} / {s['total']} |",
        f"| Attack scenarios unsafe | {s['attacks_unsafe']} / {s['attacks_total']} |",
        f"| Attacks blocked by policy | {s['attacks_blocked']} |",
        f"| Legitimate tasks passing | {s['legit_pass']} / {s['legit_total']} |",
        f"| Intermittent | {s['intermittent']} |",
        "",
        "| Category | Pass | Total |",
        "| --- | --- | --- |",
    ]
    for cat, b in s["by_category"].items():
        lines.append(f"| {cat} | {b['pass']} | {b['total']} |")

    if before:
        c = compare(before, run)
        lines += [
            "",
            "## Before and after",
            "",
            "| | Before (log-only) | After (enforced) |",
            "| --- | --- | --- |",
            f"| Passing | {c['before']['pass']} / {c['before']['total']} | {c['after']['pass']} / {c['after']['total']} |",
            f"| Unsafe actions | {c['before']['unsafe']} succeeded | {c['after']['blocked']} blocked, {c['after']['unsafe']} still unsafe |",
            f"| Legitimate tasks | {c['before']['legit_pass']} / {c['before']['legit_total']} | {c['after']['legit_pass']} / {c['after']['legit_total']} |",
        ]

    lines += ["", "## Findings", ""]
    findings = [x for x in run["scenarios"] if x["verdict"] != "PASS"]
    if not findings:
        lines.append("No failing scenarios.")
    for x in findings:
        lines += [f"### {x['id']} · {x['title']} · **{x['verdict']}**", "", f"Category: {x['category']}. {x['rationale']}", "", f"Verdict: {x['reason']}", ""]
        worst = next((a for a in x["attempts"] if a["verdict"] != "PASS"), x["attempts"][0])
        lines.append("Tool calls in the failing attempt:")
        lines.append("")
        for call in worst["calls"]:
            mark = "DENIED" if not call["allowed"] else "ok"
            mark += ", blocked" if call["blocked"] else ""
            lines.append(f"- `{_fmt_call(call)}` — {mark}{(': ' + ', '.join(call['violated'])) if call['violated'] else ''}")
        lines.append("")

    lines += ["## Scenarios", "", "| ID | Category | Scenario | Verdict | Why |", "| --- | --- | --- | --- | --- |"]
    for x in run["scenarios"]:
        why = x["reason"].replace("|", "\\|")
        lines.append(f"| {x['id']} | {x['category']} | {x['title']} | {x['verdict']} | {why} |")

    lines += ["", "## Policy", "", "```cedar", run["policy_cedar"].rstrip(), "```", ""]
    attacks = sum(1 for x in run["scenarios"] if x["category"] in ATTACK_CATEGORIES)
    lines.append(f"_{attacks} attack scenarios, each run {max(len(x['attempts']) for x in run['scenarios'])} times. Verdicts are computed from recorded tool calls checked against the Cedar policy; no model graded another model._")
    return "\n".join(lines) + "\n"
