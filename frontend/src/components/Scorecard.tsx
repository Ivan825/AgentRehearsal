import { useState } from 'react'
import type { Run, ScenarioResult } from '../types'
import { api } from '../api'
import { Card, Category, Stat, VerdictBadge } from './ui'

const ORDER: Record<string, number> = { FAIL: 0, INTERMITTENT: 1, ERROR: 2, PASS: 3 }

export function AttemptDots({ s }: { s: ScenarioResult }) {
  return (
    <span className="inline-flex gap-1 align-middle">
      {s.attempts.map((a) => (
        <span key={a.attempt} title={`attempt ${a.attempt}: ${a.verdict}`} className={`h-2 w-2 rounded-full ${a.verdict === 'PASS' ? 'bg-pass' : a.verdict === 'FAIL' ? 'bg-fail' : a.verdict === 'ERROR' ? 'bg-fuchsia-400' : 'bg-warn'}`} />
      ))}
    </span>
  )
}

export function Scorecard({ run, onOpen }: { run: Run; onOpen: (s: ScenarioResult) => void }) {
  const [onlyFailures, setOnlyFailures] = useState(false)
  const s = run.summary
  const critical = run.scenarios.filter((x) => x.verdict === 'FAIL' || x.verdict === 'INTERMITTENT')
  const enforced = run.mode === 'enforce'
  const rows = [...run.scenarios]
    .filter((x) => !onlyFailures || x.verdict !== 'PASS')
    .sort((a, b) => (ORDER[a.verdict] ?? 9) - (ORDER[b.verdict] ?? 9) || a.id.localeCompare(b.id))

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Overall" value={`${s.pass} / ${s.total}`} tone={s.pass === s.total ? 'pass' : 'warn'} sub="scenarios passing" />
        {enforced
          ? <Stat label="Attacks blocked" value={`${s.attacks_blocked} / ${s.attacks_total}`} tone="pass" sub="denied by policy at the tool boundary" />
          : <Stat label="Exploitable paths" value={s.attacks_unsafe} tone={s.attacks_unsafe ? 'fail' : 'pass'} sub={`of ${s.attacks_total} attack scenarios`} />}
        <Stat label="Legitimate tasks" value={`${s.legit_pass} / ${s.legit_total}`} tone={s.legit_pass === s.legit_total ? 'pass' : 'fail'} sub="still working" />
        <Stat label="Intermittent" value={s.intermittent} tone={s.intermittent ? 'warn' : 'default'} sub="fails in some attempts only" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="By category" className="lg:col-span-1">
          <ul className="space-y-2">
            {Object.entries(s.by_category).map(([cat, b]) => (
              <li key={cat} className="flex items-center gap-3 text-sm">
                <div className="w-40 shrink-0"><Category c={cat} /></div>
                <div className="h-2 flex-1 overflow-hidden rounded bg-panel-2">
                  <div className={`h-full ${b.pass === b.total ? 'bg-pass' : 'bg-fail'}`} style={{ width: `${Math.max(4, (b.pass / b.total) * 100)}%`, opacity: b.pass ? 1 : 0.0 }} />
                </div>
                <div className={`w-14 text-right font-mono text-xs ${b.pass === b.total ? 'text-muted' : 'text-fail'}`}>{b.pass} / {b.total}</div>
              </li>
            ))}
          </ul>
          <div className="mt-4 rounded border border-line bg-ink p-3 text-xs text-muted">
            <div className="font-semibold text-text">{run.agent} · {run.mode === 'enforce' ? 'policy enforced' : 'policy log-only'}</div>
            <div className="mt-1 font-mono">{run.model}</div>
            <div className="mt-1">{run.scenarios.reduce((n, x) => n + x.attempts.length, 0)} attempts · attacks run {Math.max(...run.scenarios.map((x) => x.attempts.length))}× each</div>
          </div>
        </Card>

        <Card
          title={enforced ? 'Results' : `Critical findings: ${critical.length}`}
          className="lg:col-span-2"
          right={
            <div className="flex items-center gap-3">
              <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted">
                <input type="checkbox" checked={onlyFailures} onChange={(e) => setOnlyFailures(e.target.checked)} /> failures only
              </label>
              <a href={api.reportUrl(run.run_id)} target="_blank" rel="noreferrer" className="text-xs text-accent hover:underline">Export report ↗</a>
            </div>
          }
        >
          <table className="w-full text-sm">
            <thead className="text-left text-[11px] uppercase tracking-wider text-muted">
              <tr><th className="pb-2">ID</th><th className="pb-2">Category</th><th className="pb-2">Scenario</th><th className="pb-2 pr-4">Attempts</th><th className="pb-2">Verdict</th></tr>
            </thead>
            <tbody>
              {rows.map((x) => (
                <tr key={x.id} onClick={() => onOpen(x)} className="cursor-pointer border-t border-line hover:bg-panel-2">
                  <td className="py-2 pr-2 font-mono text-xs text-muted">{x.id}</td>
                  <td className="py-2 pr-2"><Category c={x.category} /></td>
                  <td className="py-2 pr-2">
                    <div>{x.title}</div>
                    <div className="mt-0.5 line-clamp-1 font-mono text-xs text-muted">{x.reason}</div>
                  </td>
                  <td className="py-2 pr-4"><AttemptDots s={x} /></td>
                  <td className="py-2"><VerdictBadge v={x.verdict} /></td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={5} className="py-6 text-center text-sm text-muted">No failures in this run.</td></tr>}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  )
}
