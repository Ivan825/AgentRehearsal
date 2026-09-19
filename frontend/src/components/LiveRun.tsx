import type { Job } from '../types'
import { Card, Category, VerdictBadge } from './ui'

/** The run as it happens: one row per scenario, attempt dots filling in, verdicts arriving. */
export function LiveRun({ job }: { job: Job }) {
  const done = job.progress.length
  const total = job.total_attempts || 1
  const byId = new Map<string, Job['progress']>()
  for (const p of job.progress) byId.set(p.scenario_id, [...(byId.get(p.scenario_id) ?? []), p])
  const enforce = job.mode === 'enforce'
  if (job.kind === 'validate' && job.phase === 'authoring') {
    return (
      <Card title="Authoring held-out scenarios" right={<span className="text-xs text-muted">author model · Bedrock</span>}>
        <div className="mb-3 h-1.5 w-full overflow-hidden rounded bg-panel-2"><div className="h-full w-1/3 animate-pulse bg-accent" /></div>
        <p className="text-sm text-muted">Bedrock is writing attacks and legitimate tasks the policy has never seen, told to avoid every scenario it was built from. They will run twice: policy log-only, then enforced.</p>
      </Card>
    )
  }
  const heading = job.kind === 'validate'
    ? (enforce ? 'Held-out set · policy ENFORCED (2 of 2)' : 'Held-out set · policy LOG-ONLY (1 of 2)')
    : (enforce ? 'Replaying with policy ENFORCED' : 'Rehearsing with policy LOG-ONLY')
  return (
    <Card
      title={`${heading} · ${done} / ${total} attempts`}
      right={<span className="text-xs text-muted">{job.model === 'scripted' ? 'scripted offline simulation' : `live Bedrock target · ${job.model_id ?? ''}`}</span>}
    >
      <div className="mb-3 h-1.5 w-full overflow-hidden rounded bg-panel-2">
        <div className="h-full bg-accent transition-all" style={{ width: `${(done / total) * 100}%` }} />
      </div>
      <table className="w-full text-sm">
        <tbody>
          {job.plan.map((s) => {
            const got = byId.get(s.id) ?? []
            const active = got.length > 0 && got.length < s.attempts
            const first = job.plan.findIndex((x) => (byId.get(x.id)?.length ?? 0) < x.attempts)
            const running = got.length < s.attempts && (active || job.plan[first]?.id === s.id)
            const finalV = got.length === s.attempts ? (got.every((g) => g.verdict === 'PASS') ? 'PASS' : got.every((g) => g.verdict === 'FAIL') ? 'FAIL' : got.some((g) => g.verdict === 'ERROR') && got.every((g) => g.verdict !== 'FAIL') ? 'PASS' : 'INTERMITTENT') : null
            const last = got[got.length - 1]
            return (
              <tr key={s.id} className={`border-t border-line ${running ? 'bg-panel-2/60' : ''}`}>
                <td className="w-12 py-2 pr-2 font-mono text-xs text-muted">{s.id}</td>
                <td className="w-40 py-2 pr-2"><Category c={s.category} /></td>
                <td className="py-2 pr-2">
                  <div className={running ? 'text-text' : got.length ? 'text-text' : 'text-muted'}>{s.title}</div>
                  {last && <div className="mt-0.5 line-clamp-1 font-mono text-xs text-muted">{last.reason}</div>}
                </td>
                <td className="w-20 py-2 pr-2">
                  <div className="flex gap-1">
                    {Array.from({ length: s.attempts }).map((_, i) => {
                      const g = got[i]
                      const cls = g ? (g.verdict === 'PASS' ? 'bg-pass' : g.verdict === 'FAIL' ? 'bg-fail' : 'bg-warn') : running && i === got.length ? 'animate-pulse bg-accent' : 'bg-panel-2'
                      return <span key={i} className={`h-2.5 w-2.5 rounded-full ${cls}`} title={g?.reason} />
                    })}
                  </div>
                </td>
                <td className="w-28 py-2 text-right">{finalV ? <VerdictBadge v={finalV} /> : running ? <span className="font-mono text-xs text-accent">running…</span> : <span className="font-mono text-xs text-muted">queued</span>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Card>
  )
}
