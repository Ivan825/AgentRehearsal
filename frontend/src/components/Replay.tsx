import type { Comparison } from '../types'
import { Card, Category, Stat, VerdictBadge } from './ui'

export function Replay({ cmp }: { cmp: Comparison | null }) {
  if (!cmp) return <Card title="Replay"><p className="text-sm text-muted">Apply a policy on the Protect stage to replay the same scenarios with enforcement on.</p></Card>
  const { before: b, after: a } = cmp
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Before · policy log-only">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Passing" value={`${b.pass} / ${b.total}`} tone="warn" />
            <Stat label="Unsafe actions succeeded" value={b.unsafe} tone="fail" />
            <Stat label="Legitimate tasks" value={`${b.legit_pass} / ${b.legit_total}`} tone="pass" />
          </div>
        </Card>
        <Card title="After · policy enforced">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Passing" value={`${a.pass} / ${a.total}`} tone={a.pass === a.total ? 'pass' : 'warn'} />
            <Stat label="Unsafe actions blocked" value={a.blocked} tone="pass" sub={a.unsafe ? `${a.unsafe} still unsafe` : 'none still unsafe'} />
            <Stat label="Legitimate tasks" value={`${a.legit_pass} / ${a.legit_total}`} tone={a.legit_pass === a.legit_total ? 'pass' : 'fail'} sub="still working" />
          </div>
        </Card>
      </div>
      <Card title="Same scenarios, before and after">
        <table className="w-full text-sm">
          <thead className="text-left text-[11px] uppercase tracking-wider text-muted"><tr><th className="pb-2">ID</th><th className="pb-2">Category</th><th className="pb-2">Scenario</th><th className="pb-2">Before</th><th className="pb-2">After</th></tr></thead>
          <tbody>
            {cmp.scenarios.map((s) => (
              <tr key={s.id} className="border-t border-line">
                <td className="py-2 pr-2 font-mono text-xs text-muted">{s.id}</td>
                <td className="py-2 pr-2"><Category c={s.category} /></td>
                <td className="py-2 pr-2">{s.title}</td>
                <td className="py-2 pr-2"><VerdictBadge v={s.before} /></td>
                <td className="py-2">{s.after ? <VerdictBadge v={s.after} /> : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
