import { useState } from 'react'
import type { AgentSpec, Attempt, ScenarioResult } from '../types'
import { Button, Card, Category, VerdictBadge, fmtArgs } from './ui'

function ruleFor(spec: AgentSpec, ids: string[]): string {
  return ids.map((id) => {
    if (id.startsWith('no-permit:')) return `no rule permits ${id.split(':')[1]}`
    const c = spec.constraints.find((x) => x.id === id)
    return c?.description ?? c?.rule ?? id
  }).join('; ')
}

function Step({ label, children, tone = 'default' }: { label: string; children: React.ReactNode; tone?: 'default' | 'pass' | 'fail' | 'warn' }) {
  const dot = { default: 'bg-muted', pass: 'bg-pass', fail: 'bg-fail', warn: 'bg-warn' }[tone]
  return (
    <li className="relative pl-6">
      <span className={`absolute left-0 top-1.5 h-2.5 w-2.5 rounded-full ${dot}`} />
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-0.5">{children}</div>
    </li>
  )
}

export function Trace({ scenario, spec, mode, onBack }: { scenario: ScenarioResult; spec: AgentSpec; mode: string; onBack: () => void }) {
  const [i, setI] = useState(0)
  const a: Attempt = scenario.attempts[i]
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Button kind="ghost" onClick={onBack}>← Back to scorecard</Button>
        <span className="font-mono text-xs text-muted">{scenario.id}</span>
        <Category c={scenario.category} />
        <span className="ml-auto" />
        {scenario.attempts.length > 1 && (
          <div className="flex items-center gap-1 text-xs text-muted">
            attempt
            {scenario.attempts.map((x, k) => (
              <button key={k} onClick={() => setI(k)} className={`rounded border px-2 py-0.5 font-mono ${k === i ? 'border-accent text-accent' : 'border-line text-muted'}`}>{x.attempt}<span className={x.verdict === 'PASS' ? 'text-pass' : 'text-fail'}> ●</span></button>
            ))}
          </div>
        )}
        <VerdictBadge v={scenario.verdict} size="lg" />
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card title={scenario.title} className="lg:col-span-2">
          <div className="text-[11px] uppercase tracking-wider text-muted">Why this scenario exists</div>
          <p className="mt-1 text-sm text-muted">{scenario.rationale}</p>
          <div className="mt-3 text-[11px] uppercase tracking-wider text-muted">Expected</div>
          <div className="mt-1 text-sm">{scenario.expected === 'deny' ? 'The agent must not perform a denied action.' : `The agent must complete the task${scenario.must_call ? ` by calling ${scenario.must_call}` : ''}, within policy.`}</div>
          <div className="mt-3 text-[11px] uppercase tracking-wider text-muted">Verdict</div>
          <div className="mt-1 text-sm">{a.reason}</div>
          {a.final_text && (<>
            <div className="mt-3 text-[11px] uppercase tracking-wider text-muted">Agent's final reply</div>
            <pre className="mt-1 max-h-36 overflow-auto rounded bg-ink p-2 text-xs text-muted">{a.final_text}</pre>
          </>)}
        </Card>

        <Card title={`Reasoning path · ${mode === 'enforce' ? 'policy ENFORCED' : 'policy LOG-ONLY'}`} className="lg:col-span-3">
          <ol className="space-y-4 border-l border-line pl-0 [&>li]:ml-2">
            <Step label="Input">
              <pre className="rounded bg-ink p-2 text-xs">{a.prompt}</pre>
            </Step>
            {a.calls.map((c) => {
              const denied = !c.allowed
              const tone = denied ? (c.blocked ? 'warn' : 'fail') : 'pass'
              return (
                <Step key={c.seq} label={`Agent decides · call #${c.seq}`} tone={tone}>
                  <code className="text-sm text-accent">{c.tool}({fmtArgs(c.args)})</code>
                  <div className="mt-1.5 flex items-start gap-2 text-sm">
                    <span className="text-[11px] uppercase tracking-wider text-muted">Policy</span>
                    {denied ? (
                      <span className={c.blocked ? 'text-warn' : 'text-fail'}>
                        {c.blocked ? '⛔ DENIED and blocked' : '❌ VIOLATION (allowed through in rehearse mode)'} — {ruleFor(spec, c.violated)}
                      </span>
                    ) : (<span className="text-pass">✓ permitted{c.reasons.length ? ` by ${c.reasons.join(', ')}` : ''}</span>)}
                  </div>
                </Step>
              )
            })}
            {a.calls.length === 0 && <Step label="Agent decides">No tools were called.</Step>}
            <Step label="Outcome" tone={a.verdict === 'PASS' ? 'pass' : 'fail'}>
              <VerdictBadge v={a.verdict} /> <span className="ml-2 text-sm text-muted">{a.duration_s}s</span>
            </Step>
          </ol>
        </Card>
      </div>
    </div>
  )
}
