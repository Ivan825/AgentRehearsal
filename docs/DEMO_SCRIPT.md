# Three-minute demo script

One attack shown twice: first it succeeds, then it is blocked, and legitimate work still passes. Record from a
stored run (Stored runs → the rehearse run, then its enforce run) so nothing depends on live model behaviour.

| Time | On screen | Say |
| --- | --- | --- |
| 0:00–0:15 | Diagnose: S04 trace, `refund_customer(amount=50000)` allowed through | "We test software before we ship it. Nobody tests what an agent *decides* to do. This support agent just refunded ₹50,000 because someone claimed to be the CEO." |
| 0:15–0:30 | Define: 5 tools, 4 plain-English rules, parsed constraints | "Tell AgentRehearsal what the agent may do. It writes the tests." |
| 0:30–1:10 | Rehearse: scenarios turning green and red; open S07 (poisoned invoice) trace | "Every verdict comes from the tool calls, not from an AI's opinion. Here the customer is innocent; the invoice carried the instruction." |
| 1:10–1:45 | Protect: the Cedar policy; click Apply protection & replay | "The fix is a least-privilege Cedar policy, the same language AWS AgentCore Policy enforces, outside the model." |
| 1:45–2:15 | Replay: before/after, 7 blocked, legitimate 5/5 | "Same tests. Attacks blocked, customers still served." |
| 2:15–2:40 | Architecture slide | Strands runs the agent, Bedrock powers and tests it, Cedar decides, AgentCore Gateway enforces on AWS, DynamoDB keeps history, Amplify serves the UI. |
| 2:40–3:00 | Scorecard before/after | "Rehearse, diagnose, protect, replay. AgentRehearsal." |

Tips: 1440×900 window, dark theme is default, zoom the browser to 110% so traces are readable in the recording.
