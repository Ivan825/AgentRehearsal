# AgentRehearsal — 3-minute demo script

Voice-over on the left, what is on screen on the right. Total ≈ 3:00 at a normal speaking pace (~430 words).
Setup before recording: backend running, `localhost:5173/app` open on **Define** with TriageBot, target = "AgentRehearsal builds it",
model = Claude Opus 4.6, ~8 scenarios in the list (2 legit, 1 boundary, 5 attacks incl. the poisoned incident report).
Do one full pass before recording so the saved runs exist as a fallback.

| Time | Say | Show / click |
|---|---|---|
| 0:00–0:20 | AI agents fail in one specific way: they call the wrong tool with the wrong arguments — a file outside the repo, a secret, a delete nobody asked for. Today you find out in production. AgentRehearsal finds out before. | Define tab, scroll slowly through the agent card. |
| 0:20–0:45 | This is TriageBot: a coding agent with fourteen filesystem tools, running on Claude through Amazon Bedrock. Its rules are written in plain English — "only write inside docs/triage", "never read .env" — and Bedrock has parsed them into twenty machine-checkable constraints. | Point at the rules box, then the constraints list, then the model dropdown. |
| 0:45–1:05 | We don't hand-write tests. Bedrock authors the scenarios from the rules: legitimate requests, boundary cases and attacks — direct, and indirect, like a bug report that quietly tells the agent to copy the .env file out of the repo. | Scroll the scenarios card; hover the "Summarise incident 204" card and the coverage matrix. |
| 1:05–1:30 | Rehearse. Every scenario runs against the real model, policy in log-only mode, so we see what the agent does when nothing stops it. | Click **▶ Run Rehearsal**. While it runs (≈40 s), keep talking; if it's slow, cut to a saved run. |
| 1:30–1:55 | Diagnose. Legitimate work passed, but several attacks went through — here it read `../../.ssh/id_rsa`, and here the poisoned report talked it into reading `.env`. Every failure is a recorded tool call mapped to the rule it broke, not an opinion. | Diagnose tab: read the scorecard numbers aloud, open one failed attack, show the call and the rule. |
| 1:55–2:20 | Protect. From those same rules AgentRehearsal generates a Cedar policy — least privilege, enforced outside the model, so it works whatever the prompt says. Nothing in the agent changes. | Protect tab: scroll the Cedar policy, show the per-rule analysis. Click **Replay with policy enforced**. |
| 2:20–2:45 | Replay: same scenarios, same model, policy on. Every attack is now denied at the tool boundary; every legitimate request still passes — zero unsafe, zero over-blocking. And because the policy came from the rules, not from these tests, it holds on attacks it has never seen: Bedrock writes a fresh held-out set, and those are blocked too. | Replay tab: the before/after table; click **Validate on unseen attacks** and show the held-out table (pre-run copy if short on time). |
| 2:45–3:00 | Define, rehearse, diagnose, protect, replay — on any agent, any model, any MCP toolset, without modifying the agent. That's AgentRehearsal. | Back to the stepper in the header; end on the green scorecard. |

## If a judge asks

- **Is the replay circular?** No — the held-out set is authored after the policy exists and never used to build it.
- **Real agents?** Same pipeline with the "be the MCP server" mode: Claude Code or goose connects to our MCP URL, we proxy the real server and enforce the same Cedar policy live.
- **Why Cedar?** Deterministic, auditable, and the same language Bedrock AgentCore Gateway uses, so the policy ships with the agent.

## 60-second fallback (no live Bedrock)

Open the saved rehearse run from the runs list → Diagnose → Protect → pick its enforced replay → Replay table. Same screens, no waiting.
