import { useEffect, useState } from 'react'
import type { Analysis, Constraint, Run, Surface } from '../types'
import { lineDiff } from '../diff'
import { api } from '../api'
import { Button, Card, Stat, fmtArgs } from './ui'

export interface Hardened { system_prompt: string; changes: string[]; run: Run | null }

interface Props {
  run: Run | null; after: Run | null; cedar: string; compiledCedar: string; onCedar: (s: string) => void; onReplay: () => void; busy: boolean
  hardened: Hardened | null; onHarden: () => void; onApplyPrompt: (p: string) => Promise<void>; onAddConstraint: (c: Constraint) => Promise<void>
}

export function Protect({ run, after, cedar, compiledCedar, onCedar, onReplay, busy, hardened, onHarden, onApplyPrompt, onAddConstraint }: Props) {
  const [problems, setProblems] = useState<string[]>([])
  const [surface, setSurface] = useState<Surface | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [afterAnalysis, setAfterAnalysis] = useState<Analysis | null>(null)
  const [applied, setApplied] = useState(false)
  const [showPrompt, setShowPrompt] = useState(false)
  useEffect(() => { api.validatePolicy(cedar).then((r) => setProblems(r.problems)).catch(() => {}) }, [cedar])
  useEffect(() => { setSurface(null); setAnalysis(null); if (run) { api.surface(run.run_id).then(setSurface).catch(() => {}); api.analysis(run.run_id).then(setAnalysis).catch(() => {}) } }, [run])
  useEffect(() => { setAfterAnalysis(null); if (after) api.analysis(after.run_id).then(setAfterAnalysis).catch(() => {}) }, [after])
  const diff = compiledCedar && cedar !== compiledCedar ? lineDiff(compiledCedar, cedar) : null
  const overBlocking = afterAnalysis?.over_blocking ?? []

  const findings = run?.scenarios.filter((s) => s.verdict !== 'PASS') ?? []
  const fixes = new Map<string, { rule: string; tool: string; findings: string[] }>()
  for (const s of findings) {
    const ids = new Set<string>()
    for (const a of s.attempts) for (const c of a.calls) if (!c.allowed) for (const v of c.violated) ids.add(v + '|' + c.tool)
    for (const key of ids) {
      const [v, tool] = key.split('|')
      const con = run!.spec.constraints.find((x) => x.id === v)
      const cur = fixes.get(v) ?? { rule: con?.description ?? con?.rule ?? v, tool, findings: [] }
      cur.findings.push(s.id)
      fixes.set(v, cur)
    }
  }
  const total = run?.scenarios.length ?? 0
  const b = run?.summary, h = hardened?.run?.summary, a = after?.summary

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-5">
        <Card title="Suggested protection" className="lg:col-span-2">
          {!run && <p className="text-sm text-muted">Run a rehearsal first. Each failure maps to a constraint; the policy below enforces all of them outside the model.</p>}
          {run && findings.length === 0 && <p className="text-sm text-pass">No failures in this run. The policy below keeps it that way.</p>}
          <ul className="space-y-2">
            {(analysis?.constraints ?? []).map((c) => {
              const f = fixes.get(c.id)
              return (
                <li key={c.id} className={`rounded border p-2.5 text-sm ${c.denied.length ? 'border-fail/30 bg-fail/5' : 'border-line bg-panel-2'}`}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium">{c.text}</div>
                    {c.denied.length > 0 && <span className="shrink-0 rounded bg-fail/15 px-1.5 py-0.5 font-mono text-[10px] text-fail">caught {c.denied.length}</span>}
                  </div>
                  <div className="mt-0.5 text-xs text-muted">
                    {c.rule && <span>from “{c.rule}” · </span>}
                    {c.denied.length ? <span>denies {c.denied.join(', ')}</span> : <span>denied nothing in this run</span>}
                    {c.allowed_calls > 0 && <span> · let {c.allowed_calls} legitimate call{c.allowed_calls === 1 ? '' : 's'} through</span>}
                    {f && f.findings.length !== c.denied.length ? null : null}
                    <span className="font-mono"> · {c.id}</span>
                  </div>
                </li>
              )
            })}
            {!analysis && run && <li className="text-xs text-muted">Analysing…</li>}
          </ul>
          {overBlocking.length > 0 && (
            <div className="mt-3 rounded border border-warn/40 bg-warn/10 p-3 text-xs">
              <div className="font-semibold text-warn">Over-blocking in the replay: {overBlocking.length} legitimate task{overBlocking.length === 1 ? '' : 's'} denied</div>
              <ul className="mt-1 space-y-1.5">
                {overBlocking.map((o, i) => (
                  <li key={i}><span className="font-mono text-muted">{o.scenario}</span> {o.title}: <code className="text-accent">{o.tool}({fmtArgs(o.args)})</code><div className="text-muted">{o.hint}</div></li>
                ))}
              </ul>
            </div>
          )}
          {afterAnalysis && afterAnalysis.legit_failures_not_blocked.length > 0 && (
            <div className="mt-3 rounded border border-line bg-panel-2 p-3 text-xs text-muted">
              <div className="font-semibold text-text">Legitimate tasks that failed for another reason (not the policy)</div>
              <ul className="mt-1 space-y-0.5">{afterAnalysis.legit_failures_not_blocked.map((x) => <li key={x.scenario}><span className="font-mono">{x.scenario}</span> {x.title}: {x.reason}</li>)}</ul>
            </div>
          )}
          <div className="mt-4 flex items-center gap-3 rounded border border-line bg-ink p-3">
            <div className="text-[11px] uppercase tracking-wider text-muted">Policy mode</div>
            <span className="rounded border border-warn/40 bg-warn/15 px-2 py-0.5 font-mono text-xs text-warn">LOG_ONLY</span>
            <span className="text-muted">→</span>
            <span className={`rounded border px-2 py-0.5 font-mono text-xs ${busy ? 'border-pass/40 bg-pass/15 text-pass' : 'border-line text-muted'}`}>ENFORCE</span>
            <span className="ml-auto text-[11px] text-muted">{run?.tools === 'gateway' ? 'AgentCore Gateway' : 'Strands hook'}</span>
          </div>
          <div className="mt-3 rounded border border-line bg-ink p-3 text-xs text-muted">
            <div className="font-semibold text-text">How enforcement works</div>
            <p className="mt-1">Every tool call passes through a policy decision point before it runs. Locally that is a Strands hook evaluating this Cedar policy; on AWS it is AgentCore Gateway with Policy in ENFORCE mode. Same policy text, same decision, and the model never gets a vote.</p>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button onClick={onReplay} disabled={busy || problems.length > 0 || !run}>{busy ? 'Working…' : `Apply protection & replay all ${total || ''} scenarios`}</Button>
            {run && <a href={api.fixpackUrl(run.run_id, after?.run_id, hardened?.run?.run_id)} className="text-xs text-accent hover:underline">Download fix pack ↗</a>}
          </div>
        </Card>
        <Card title="Cedar policy" className="lg:col-span-3" right={problems.length ? <span className="text-xs text-fail">does not parse</span> : <span className="text-xs text-pass">parses ✓</span>}>
          <textarea value={cedar} onChange={(e) => onCedar(e.target.value)} rows={22} spellCheck={false} className="w-full rounded border border-line bg-ink p-3 font-mono text-xs text-text outline-none focus:border-accent" />
          {problems.map((p, i) => <div key={i} className="mt-2 text-xs text-fail">{p}</div>)}
          {diff && (
            <div className="mt-3 rounded border border-line bg-ink p-2 text-[11px]">
              <div className="mb-1 flex items-center justify-between text-muted"><span>Your edits vs the compiled policy ({diff.filter((d) => d.kind !== 'same').length} lines)</span><button onClick={() => onCedar(compiledCedar)} className="text-accent">revert to compiled</button></div>
              <pre className="max-h-48 overflow-auto font-mono">{diff.filter((d) => d.kind !== 'same').map((d, i) => <div key={i} className={d.kind === 'add' ? 'text-pass' : 'text-fail'}>{d.kind === 'add' ? '+ ' : '- '}{d.text}</div>)}</pre>
            </div>
          )}
        </Card>
      </div>

      <Card title="Fix the agent itself" right={<span className="text-xs text-muted">the policy is the control; these make the agent need it less</span>}>
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted">1 · Harden the system prompt</div>
            <p className="mt-1 text-sm text-muted">Bedrock rewrites the agent's own instructions from the findings (limits with numbers, documents are data, session identity wins, when to hand off), then the same scenarios run again with the new prompt and <em>no</em> policy. That measures what the prompt alone buys.</p>
            {b && (
              <div className="mt-3 grid grid-cols-3 gap-2">
                <Stat label="Original prompt" value={`${b.attacks_unsafe} / ${b.attacks_total}`} tone={b.attacks_unsafe ? 'fail' : 'pass'} sub={`unsafe · legit ${b.legit_pass}/${b.legit_total}`} />
                <Stat label="Hardened prompt only" value={h ? `${h.attacks_unsafe} / ${h.attacks_total}` : '—'} tone={h ? (h.attacks_unsafe ? 'warn' : 'pass') : 'default'} sub={h ? `unsafe · legit ${h.legit_pass}/${h.legit_total}` : 'not run yet'} />
                <Stat label="With policy enforced" value={a ? `${a.attacks_unsafe} / ${a.attacks_total}` : '—'} tone={a ? (a.attacks_unsafe ? 'fail' : 'pass') : 'default'} sub={a ? `unsafe · legit ${a.legit_pass}/${a.legit_total}` : 'replay first'} />
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button kind="ghost" onClick={onHarden} disabled={busy || !run}>{busy ? 'Working…' : hardened ? 'Harden again' : 'Harden prompt & re-test'}</Button>
              {hardened && <Button onClick={async () => { await onApplyPrompt(hardened.system_prompt); setApplied(true) }} disabled={busy || applied}>{applied ? 'Applied to the agent ✓' : 'Apply hardened prompt to the agent'}</Button>}
              {hardened && <button onClick={() => setShowPrompt(!showPrompt)} className="text-xs text-accent">{showPrompt ? 'hide prompt' : 'show prompt'}</button>}
            </div>
            {hardened && (
              <div className="mt-3 rounded border border-line bg-panel-2 p-3 text-xs">
                <div className="font-semibold text-text">What changed</div>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted">{hardened.changes.map((c, i) => <li key={i}>{c}</li>)}</ul>
                {showPrompt && <pre className="mt-2 whitespace-pre-wrap rounded bg-ink p-2 font-mono text-[11px] text-text">{hardened.system_prompt}</pre>}
              </div>
            )}
          </div>
          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted">2 · Shrink the tool surface</div>
            <p className="mt-1 text-sm text-muted">From the recorded calls: which tools legitimate work actually needed, which only attacks reached, and which denied calls no rule covers yet.</p>
            {surface && (
              <table className="mt-3 w-full text-xs">
                <thead className="text-left text-[10px] uppercase tracking-wider text-muted"><tr><th className="pb-1">Tool</th><th className="pb-1">Legit calls</th><th className="pb-1">Attack calls</th><th className="pb-1">Rule</th></tr></thead>
                <tbody>
                  {surface.tools.map((t) => (
                    <tr key={t.name} className="border-t border-line">
                      <td className="py-1 font-mono text-accent">{t.name}{t.destructive ? <span className="ml-1 text-[9px] text-fail">irreversible</span> : null}</td>
                      <td className={`py-1 font-mono ${t.legit_calls ? '' : 'text-warn'}`}>{t.legit_calls}</td>
                      <td className={`py-1 font-mono ${t.attack_calls ? 'text-fail' : 'text-muted'}`}>{t.attack_calls}</td>
                      <td className="py-1">{t.constrained ? <span className="text-pass">yes</span> : <span className="text-fail">none (default deny)</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <ul className="mt-3 space-y-2">
              {surface?.suggestions.map((s, i) => (
                <li key={i} className="rounded border border-line bg-panel-2 p-2.5 text-xs">
                  <div className="flex items-start justify-between gap-2">
                    <div><span className="font-mono text-accent">{s.tool}</span> <span className="text-muted">· {s.kind.replace('_', ' ')}</span><div className="mt-0.5 text-text">{s.why}</div></div>
                    {s.constraint && <Button kind="ghost" onClick={() => onAddConstraint(s.constraint!)} disabled={busy}>Add rule</Button>}
                  </div>
                </li>
              ))}
              {surface && surface.suggestions.length === 0 && <li className="text-xs text-muted">Nothing to shrink: every tool is used by legitimate work and every denied call is covered by an explicit rule.</li>}
            </ul>
          </div>
        </div>
      </Card>
    </div>
  )
}
