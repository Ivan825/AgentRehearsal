import { useState } from 'react'
import type { AgentSpec, Attempt, RecordedCall, ScenarioResult } from '../types'
import { Button, Card, Category, VerdictBadge, fmtArgs } from './ui'

function ruleFor(spec: AgentSpec, ids: string[]): string {
  return ids.map((id) => {
    if (id.startsWith('no-permit:')) return `no rule permits ${id.split(':')[1]}`
    if (id.startsWith('gateway-deny:')) return `denied by AgentCore Gateway policy`
    const c = spec.constraints.find((x) => x.id === id)
    return c?.description ?? c?.rule ?? id
  }).join('; ')
}

/** Pull the human-readable text out of a tool result; highlight injected instructions in documents. */
function ToolResult({ call }: { call: RecordedCall }) {
  const [open, setOpen] = useState(call.tool === 'read_attachment')
  if (!call.result) return null
  let text = call.result
  try {
    const j = JSON.parse(call.result)
    if (j && typeof j === 'object' && 'text' in j) text = String(j.text)
    else text = JSON.stringify(j, null, 1).replace(/[{}\n"]/g, ' ').replace(/\s+/g, ' ').trim()
  } catch { /* plain text */ }
  const isDoc = call.tool === 'read_attachment'
  const marker = /note to support agents|action for support|system note|instruction/i
  const lines = text.split('\n')
  const firstBad = lines.findIndex((l) => marker.test(l))
  return (
    <div className="mt-1.5">
      <button onClick={() => setOpen(!open)} className="text-[11px] uppercase tracking-wider text-muted hover:text-text">
        {open ? '▾' : '▸'} {isDoc ? 'what the agent read' : 'tool returned'}
      </button>
      {open && (
        <pre className="mt-1 max-h-48 overflow-auto rounded border border-line bg-ink p-2 text-xs text-muted">
          {isDoc && firstBad >= 0
            ? <>{lines.slice(0, firstBad).join('\n')}{'\n'}<span className="rounded bg-fail/15 px-1 text-fail">{lines.slice(firstBad).join('\n')}</span></>
            : text.slice(0, 900)}
        </pre>
      )}
      {isDoc && firstBad >= 0 && <div className="mt-1 text-xs text-fail">Instruction embedded in data. The customer never asked for this.</div>}
    </div>
  )
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
  const firstBad = Math.max(0, scenario.attempts.findIndex((a) => a.verdict !== 'PASS'))
  const [i, setI] = useState(firstBad)
  const a: Attempt = scenario.attempts[i] ?? scenario.attempts[0]
  const header = a.prompt.split('\n\nCustomer message:\n')
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
          <div className={`mt-1 text-sm ${a.verdict === 'PASS' ? 'text-text' : 'text-fail'}`}>{a.reason}</div>
          {a.final_text && (<>
            <div className="mt-3 text-[11px] uppercase tracking-wider text-muted">Agent's final reply to the customer</div>
            <pre className="mt-1 max-h-36 overflow-auto rounded bg-ink p-2 text-xs text-muted">{a.final_text}</pre>
          </>)}
          <div className="mt-3 text-[11px] uppercase tracking-wider text-muted">Side effects in the sandbox</div>
          <div className="mt-1 font-mono text-xs text-muted">
            {(() => { const se = a.side_effects as { tool_calls?: Record<string, number> }; const parts = Object.entries(se.tool_calls ?? {}).map(([t, n]) => `${t} ×${n}`); return parts.join(' · ') || 'none' })()}
            <span className="ml-2 text-muted">(simulated tools; nothing real happened)</span>
          </div>
        </Card>

        <Card title={`Reasoning path · ${mode === 'enforce' ? 'policy ENFORCED' : 'policy LOG-ONLY'}`} className="lg:col-span-3">
          <ol className="space-y-4 border-l border-line pl-0 [&>li]:ml-2">
            <Step label="Session context">
              <div className="text-xs text-muted">{header[0]}</div>
            </Step>
            <Step label="Customer says">
              <pre className="rounded bg-ink p-2 text-xs">{header[1] ?? a.prompt}</pre>
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
                        {c.blocked ? '⛔ DENIED, call blocked' : '❌ VIOLATION, allowed through in log-only mode'} — {ruleFor(spec, c.violated)}
                      </span>
                    ) : (<span className="text-pass">✓ permitted{c.reasons.length ? ` by ${c.reasons.join(', ')}` : ''}</span>)}
                  </div>
                  <ToolResult call={c} />
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
