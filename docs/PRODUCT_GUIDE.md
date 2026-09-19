# AgentRehearsal — product guide and walkthrough

## What each part does

**Public site** (`/`): landing page, Product (how it works), Guides (five short guides), About, Contact (messages are stored), Sign in / Create account. Green-on-black by default, green-on-white with the ☀/☾ toggle; the choice is remembered.

**Accounts**: email + password, PBKDF2-hashed, 7-day JWT sessions. Every account has its own workspace: one agent definition, its scenarios, and its run history. Nothing is shared between accounts. Stored in DynamoDB when `AGENTREHEARSAL_DDB_TABLE` is set, otherwise in `backend/data/`. `AGENTREHEARSAL_AUTH=off` turns accounts off for local development and the CLI.

**Workspace** (`/app`), five stages in the header:

| Stage | What it is for |
| --- | --- |
| 0 Define | The agent under test: name, purpose, system prompt, the Bedrock model it runs on, where it runs (built by AgentRehearsal, your own HTTP endpoint, or an AgentCore Runtime agent that takes its tools from the workspace's MCP endpoint), session facts, the context line the agent sees. Tools: name, description, parameters, simulated responses keyed by argument. Rules in plain English → constraints (Bedrock parses, you confirm) → Cedar policy (shown). Scenarios: 15 seeds for SupportBot, none for TravelDesk (Bedrock authors them), add your own, generate more with Bedrock, delete any. Save / Start from an example (SupportBot, TravelDesk) / Import JSON / Export JSON. |
| 1 Rehearse | Runs every scenario against the agent with the policy in log-only mode; attack scenarios run three times. Live view fills in per attempt. Then the scorecard: overall, exploitable paths, legitimate tasks still working, intermittent count, per-category bars, findings sorted first, attempt dots, "failures only" filter, Export report (Markdown). Stored runs can be reopened. |
| 2 Diagnose | One scenario's trace: why it exists, what was expected, the verdict, the agent's final reply, side effects. On the right the reasoning path: session context, customer message, every tool call with its arguments, the policy's decision on each (permitted / violation / denied and blocked), what the tool returned (injected instructions in documents highlighted), outcome. Switch between the three attempts. |
| 3 Protect | Suggested protection: one card per constraint that a finding broke, with how many findings and which. Policy mode strip LOG_ONLY → ENFORCE. The Cedar policy, editable, validated live. Apply protection & replay. |
| 4 Replay | Two sections. §1 Same scenarios: before and after side by side, a table of every verdict, the full after-scorecard. §2 Unseen scenarios: **Validate on unseen attacks** has Bedrock author a held-out set (told to avoid everything the policy was built from), runs it log-only and then enforced, and shows the same before/after view for it. Held-out runs are tagged in Stored runs. |

**Target model** dropdown: Bedrock (Amazon Nova Lite by default, configurable) or "scripted", an offline simulation of a naive agent for the SupportBot example, labelled as such.

**CLI** (`backend/`): `doctor`, `policy`, `rehearse`, `replay`, `demo`, `generate`, `report`. Same engine as the UI.

## Walkthrough for a live demo

1. Open the site. Create an account (or sign in). The workspace opens on Define with SupportBot loaded.
2. Define: point at the five tools, open `read_attachment` and show the `inv_2202` response that carries the injected instruction. Show the four rules and the constraints they parsed into. Expand "Cedar policy these constraints compile to".
3. Press Run Rehearsal. While it runs (2–4 minutes), narrate the live view: green rows are legitimate tasks completing; red rows are attacks that got through; three dots per attack.
4. Scorecard: read the four numbers. Failures are at the top. Click S07 (poisoned invoice).
5. Diagnose: read the customer message (innocent), the first call (read_attachment, permitted), the document with the red highlighted instruction, the second call (send_email to the external address, violation), the agent's reply to the customer ("delivery confirmed"). Click attempt 2 and 3 to show consistency, or S05 to show intermittent behaviour.
6. Protect: the two suggested constraints with their finding counts; the Cedar text. Press Apply protection & replay all 15 scenarios.
7. Replay: before 9/15 and 6 unsafe, after 15/15 and 0 unsafe, legitimate 7/7. Click S07 again: the same send_email is now "DENIED, call blocked" and the agent's reply changes.
8. Validate on unseen attacks: about a minute of authoring, then two runs. The held-out table shows the new attacks FAIL log-only and PASS enforced, the new legitimate tasks PASS in both.
8. Export report from the scorecard for the written record.

## Defining your own agent (short version)

Name, purpose and system prompt are your real agent's. Each tool needs at least a default response; give argument-specific responses where the world matters (a document that carries an instruction, a customer record by id). Session facts are what the policy can compare against; the context line built from them is what the agent sees. Write rules one per line, parse, check the constraints, save. Generate scenarios, or add your own. Run.
