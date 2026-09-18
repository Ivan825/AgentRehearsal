import { useEffect, useState } from 'react'
import type { AgentSpec } from '../types'
import { api } from '../api'
import { Button, Card } from './ui'

const KIND_TEXT: Record<string, (c: AgentSpec['constraints'][number]) => string> = {
  allow: () => 'always allowed',
  forbid: () => 'never allowed',
  param_max: (c) => `${c.param} ≤ ${c.value}`,
  param_min: (c) => `${c.param} ≥ ${c.value}`,
  param_in: (c) => `${c.param} ∈ {${(c.values ?? []).join(', ')}}`,
  param_equals_session: (c) => `${c.param} must equal session.${c.session_key}`,
}

export function Define({ spec, onSpec, cedar }: { spec: AgentSpec; onSpec: (s: AgentSpec) => void; cedar: string }) {
  const [rules, setRules] = useState(spec.rules.join('\n'))
  const [busy, setBusy] = useState(false)
  const [gen, setGen] = useState(false)
  const [count, setCount] = useState<number | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { api.scenarios().then((r) => setCount(r.scenarios.length)).catch(() => {}) }, [])

  async function generate() {
    setGen(true); setErr(null)
    try { const r = await api.generate(4); setCount(r.total) } catch (e) { setErr(String(e)) } finally { setGen(false) }
  }

  async function reparse() {
    setBusy(true); setErr(null)
    try {
      const lines = rules.split('\n').map((s) => s.trim()).filter(Boolean)
      const { constraints } = await api.parseRules(lines)
      const next = await api.saveSpec({ ...spec, rules: lines, constraints })
      onSpec(next)
    } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="Agent under test" className="lg:col-span-1">
        <div className="text-lg font-semibold">{spec.name}</div>
        <p className="mt-1 text-sm text-muted">{spec.purpose}</p>
        <div className="mt-4 text-[11px] uppercase tracking-wider text-muted">System prompt</div>
        <pre className="mt-1 max-h-40 overflow-auto rounded bg-ink p-3 text-xs text-muted">{spec.system_prompt}</pre>
        <div className="mt-3 rounded border border-warn/30 bg-warn/10 p-2 text-xs text-warn">Labelled “vulnerable demo agent”: broad tool access, no guardrails. That is how most prototypes ship.</div>
      </Card>

      <Card title={`${spec.tools.length} tools connected`} className="lg:col-span-1">
        <ul className="space-y-2">
          {spec.tools.map((t) => (
            <li key={t.name} className="rounded border border-line bg-panel-2 p-2.5">
              <div className="flex items-center justify-between">
                <code className="text-sm text-accent">{t.name}({t.params.map((p) => p.name).join(', ')})</code>
                {t.destructive && <span className="rounded bg-fail/15 px-1.5 py-0.5 text-[10px] font-semibold text-fail">DESTRUCTIVE</span>}
              </div>
              <div className="mt-1 text-xs text-muted">{t.description}</div>
            </li>
          ))}
        </ul>
      </Card>

      <Card title={`${spec.constraints.length} operating constraints`} className="lg:col-span-1" right={<Button kind="ghost" onClick={reparse} disabled={busy}>{busy ? 'Parsing…' : 'Re-parse rules with Bedrock'}</Button>}>
        <div className="text-[11px] uppercase tracking-wider text-muted">Rules, in plain English</div>
        <textarea value={rules} onChange={(e) => setRules(e.target.value)} rows={5} className="mt-1 w-full rounded border border-line bg-ink p-2 text-sm text-text outline-none focus:border-accent" />
        {err && <div className="mt-2 text-xs text-fail">{err}</div>}
        <div className="mt-3 text-[11px] uppercase tracking-wider text-muted">Parsed constraints (what gets enforced)</div>
        <ul className="mt-1 space-y-1.5">
          {spec.constraints.map((c) => (
            <li key={c.id} className="flex items-start gap-2 text-sm">
              <code className="shrink-0 rounded bg-panel-2 px-1.5 py-0.5 text-xs text-accent">{c.tool}</code>
              <span className="text-text">{KIND_TEXT[c.kind]?.(c) ?? c.kind}</span>
              <span className="ml-auto shrink-0 font-mono text-[10px] text-muted">{c.id}</span>
            </li>
          ))}
        </ul>
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-muted">Cedar policy these constraints compile to</summary>
          <pre className="mt-2 rounded bg-ink p-3 text-xs text-muted">{cedar}</pre>
        </details>
        <div className="mt-4 flex items-center justify-between rounded border border-line bg-panel-2 p-2.5">
          <div className="text-sm">{count ?? '…'} scenarios ready <span className="text-xs text-muted">(12 seeds + generated)</span></div>
          <Button kind="ghost" onClick={generate} disabled={gen}>{gen ? 'Authoring with Bedrock…' : 'Generate more with Bedrock'}</Button>
        </div>
      </Card>
    </div>
  )
}
