import { useEffect, useState } from 'react'
import type { Run } from '../types'
import { api } from '../api'
import { Button, Card } from './ui'

export function Protect({ run, cedar, onCedar, onReplay, busy }: { run: Run | null; cedar: string; onCedar: (s: string) => void; onReplay: () => void; busy: boolean }) {
  const [problems, setProblems] = useState<string[]>([])
  useEffect(() => { api.validatePolicy(cedar).then((r) => setProblems(r.problems)).catch(() => {}) }, [cedar])

  const findings = run?.scenarios.filter((s) => s.verdict !== 'PASS') ?? []
  const fixes = new Map<string, { rule: string; tool: string; finding: string }>()
  for (const s of findings) for (const a of s.attempts) for (const c of a.calls) if (!c.allowed) for (const v of c.violated) {
    const con = run!.spec.constraints.find((x) => x.id === v)
    fixes.set(v, { rule: con?.description ?? con?.rule ?? v, tool: c.tool, finding: s.title })
  }

  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <Card title="Suggested protection" className="lg:col-span-2">
        {!run && <p className="text-sm text-muted">Run a rehearsal first. Each failure maps to a constraint; the policy below enforces all of them outside the model.</p>}
        {run && findings.length === 0 && <p className="text-sm text-pass">No failures in this run. The policy below keeps it that way.</p>}
        <ul className="space-y-2">
          {[...fixes.entries()].map(([id, f]) => (
            <li key={id} className="rounded border border-line bg-panel-2 p-2.5 text-sm">
              <div className="font-medium">{f.rule}</div>
              <div className="mt-0.5 text-xs text-muted">Restrict <code className="text-accent">{f.tool}</code> · found by “{f.finding}” · <span className="font-mono">{id}</span></div>
            </li>
          ))}
        </ul>
        <div className="mt-4 rounded border border-line bg-ink p-3 text-xs text-muted">
          <div className="font-semibold text-text">How enforcement works</div>
          <p className="mt-1">Every tool call passes through a policy decision point before it runs. Locally that is a Strands hook evaluating this Cedar policy; on AWS it is AgentCore Gateway with Policy in ENFORCE mode. Same policy text, same decision, and the model never gets a vote.</p>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button onClick={onReplay} disabled={busy || problems.length > 0 || !run}>{busy ? 'Replaying…' : 'Apply protection & replay failed tests'}</Button>
        </div>
      </Card>
      <Card title="Cedar policy" className="lg:col-span-3" right={problems.length ? <span className="text-xs text-fail">does not parse</span> : <span className="text-xs text-pass">parses ✓</span>}>
        <textarea value={cedar} onChange={(e) => onCedar(e.target.value)} rows={26} spellCheck={false} className="w-full rounded border border-line bg-ink p-3 font-mono text-xs text-text outline-none focus:border-accent" />
        {problems.map((p, i) => <div key={i} className="mt-2 text-xs text-fail">{p}</div>)}
      </Card>
    </div>
  )
}
