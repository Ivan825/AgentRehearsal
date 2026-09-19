# AgentRehearsal — submission writeup

> Fill the bracketed parts before submitting. Keep it under one page; judges read many.

## The problem

AI agents now call APIs, send email and change records. We test ordinary software before shipping it, but there is no
equivalent for what an autonomous agent will *decide* to do: an agent with a `refund` tool and a system prompt is one
convincing message away from a ₹50,000 refund, and one poisoned document away from emailing a customer's record to a
stranger. Prompt-based guardrails are advice; the model can be talked out of them.

## What we built

AgentRehearsal turns an agent's stated rules into executable behavioural tests, finds unsafe tool paths, and converts
each finding into a deterministic least-privilege policy, then proves the fix by replaying the same tests.

1. **Define**: tools and plain-English rules → structured constraints (parsed by Bedrock, confirmed by the developer).
2. **Rehearse**: generated scenarios (allowed, boundary, and five attack categories) run against the agent with the
   policy in log-only mode; every tool call and argument is recorded.
3. **Diagnose**: verdicts from facts, not opinions. The trace shows each decision and the rule it broke.
4. **Protect**: findings compile to a Cedar policy, default deny, one permit per tool with parameter conditions.
5. **Replay**: the same scenarios with the policy enforced. Attacks blocked; legitimate tasks still pass.

Every attack runs three times; an agent that fails one in three is marked intermittent. The sample agent under test,
SupportBot, is a real Strands agent on a Bedrock model with deliberately broad permissions. Failures are found, never
scripted. [Result of the live run: X of Y attacks succeeded before protection, 0 after; Z of Z legitimate tasks pass.]

## How AWS is used

| Service | Role |
| --- | --- |
| Strands Agents SDK | Runs the agent under test; its `BeforeToolCallEvent` hook is the interception point |
| Amazon Bedrock | Powers SupportBot ([model]), parses rules, authors scenarios ([model]) |
| Cedar | Policy language for verdicts and enforcement (`cedarpy` locally) |
| Bedrock AgentCore Gateway + Policy | Enforces the same policy at the tool boundary on AWS, LOG_ONLY → ENFORCE [state: deployed / not yet] |
| DynamoDB | Run history [state] |
| Amplify Hosting | Serves the UI [URL] |
| ECS Express Mode | Serves the API [URL] |

## What we learned

[One or two lines per person: e.g. Cedar's default-deny model and why forbid rules are rarely needed; Strands hooks
and cancelling tool calls; how AgentCore Policy exposes tool arguments as `context.input`; building a deterministic
verdict engine so the LLM never grades the LLM.]

## Team

[Names, universities.]

## AI tools used

Claude (Anthropic) was used through the Claude desktop app to draft the plan, scaffold and write code, and review it.
[Add any others: Kiro, Copilot, ChatGPT, etc.] All code was written during the event.

## Links

- Repository: [url]
- Live UI: [url]
- Demo video: [url]
