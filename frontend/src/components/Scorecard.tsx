import type { Run, ScenarioResult } from '../types'
import { api } from '../api'
import { Card, Category, Stat, VerdictBadge } from './ui'

export function Scorecard({ run, onOpen }: { run: Run; onOpen: (s: ScenarioResult) => void }) {
  const s = run.summary
  const critical = run.scenarios.filter((x) => x.verdict === 'FAIL' || x.verdict === 'INTERMITTENT')
  const enforced = run.mode === 'enforce'
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
                  <div className="h-full bg-pass" style={{ width: `${(b.pass / b.total) * 100}%` }} />
                </div>
                <div className="w-14 text-right font-mono text-xs text-muted">{b.pass} / {b.total}</div>
              </li>
            ))}
          </ul>
        </Card>

        <Card title={enforced ? 'Results' : `Critical findings: ${critical.length}`} className="lg:col-span-2"
          right={<a href={api.reportUrl(run.run_id)} target="_blank" rel="noreferrer" className="text-xs text-accent hover:underline">Export report ↗</a>}>
          <table className="w-full text-sm">
            <thead className="text-left text-[11px] uppercase tracking-wider text-muted">
              <tr><th className="pb-2">ID</th><th className="pb-2">Category</th><th className="pb-2">Scenario</th><th className="pb-2">Verdict</th></tr>
            </thead>
            <tbody>
              {run.scenarios.map((x) => (
                <tr key={x.id} onClick={() => onOpen(x)} className="cursor-pointer border-t border-line hover:bg-panel-2">
                  <td className="py-2 pr-2 font-mono text-xs text-muted">{x.id}</td>
                  <td className="py-2 pr-2"><Category c={x.category} /></td>
                  <td className="py-2 pr-2">
                    <div>{x.title}</div>
                    <div className="mt-0.5 line-clamp-1 font-mono text-xs text-muted">{x.reason}</div>
                  </td>
                  <td className="py-2"><VerdictBadge v={x.verdict} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  )
}
