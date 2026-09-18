import type { RunListItem } from '../types'
import { Button } from './ui'

const STEPS = [
  ['Rehearse', 'Generated scenarios run against your agent with the policy in log-only mode. Every tool call and its arguments are recorded.'],
  ['Diagnose', 'Verdicts come from the calls, not from an AI opinion. Each failure shows the input, the decision, and the rule it broke.'],
  ['Protect', 'Findings compile into a least-privilege Cedar policy: one permit per tool, parameter conditions, default deny.'],
  ['Replay', 'The same scenarios run again with the policy enforced. Attacks blocked, legitimate work still passing.'],
]

export function Landing({ agent, onRun, runs, onLoad }: { agent: string; onRun: () => void; runs: RunListItem[]; onLoad: (id: string) => void }) {
  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-line bg-panel p-8">
        <div className="text-[11px] uppercase tracking-wider text-muted">Behavioural safety tests for tool-using agents</div>
        <h2 className="mt-2 text-3xl font-bold tracking-tight">Crash-test <span className="text-accent">{agent}</span> before your users do.</h2>
        <p className="mt-3 max-w-2xl text-sm text-muted">An agent with a refund tool is one convincing message away from a ₹50,000 refund, and one poisoned invoice away from emailing a customer's record to a stranger. AgentRehearsal finds those paths, then proves the fix.</p>
        <div className="mt-6 grid gap-3 md:grid-cols-4">
          {STEPS.map(([t, d], i) => (
            <div key={t} className="rounded border border-line bg-panel-2 p-3">
              <div className="font-mono text-[10px] text-muted">{i + 1}</div>
              <div className="mt-0.5 font-semibold">{t}</div>
              <div className="mt-1 text-xs text-muted">{d}</div>
            </div>
          ))}
        </div>
        <div className="mt-6"><Button onClick={onRun}>▶ Run Rehearsal</Button></div>
      </section>
      {runs.length > 0 && (
        <section>
          <div className="mb-2 text-[11px] uppercase tracking-wider text-muted">Or open a stored run</div>
          <ul className="divide-y divide-line rounded border border-line bg-panel">
            {runs.map((r) => (
              <li key={r.run_id} className="flex cursor-pointer items-center gap-3 px-3 py-2 text-xs hover:bg-panel-2" onClick={() => onLoad(r.run_id)}>
                <span className="font-mono text-muted">{r.run_id}</span>
                <span className={`rounded px-1.5 py-0.5 font-mono ${r.mode === 'enforce' ? 'bg-pass/15 text-pass' : 'bg-warn/15 text-warn'}`}>{r.mode}</span>
                <span className="text-muted">{r.model}</span>
                <span className="ml-auto font-mono">{r.summary.pass}/{r.summary.total} pass</span>
                {r.example && <span className="rounded bg-panel-2 px-1.5 py-0.5 text-[10px] text-muted">example</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
