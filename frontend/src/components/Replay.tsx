import type { Comparison } from '../types'
import { Button, Card, Category, Stat, VerdictBadge } from './ui'

function CompareTable({ cmp, caption }: { cmp: Comparison; caption: string }) {
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">{caption}</caption>
      <thead className="text-left text-[11px] uppercase tracking-wider text-muted"><tr><th className="pb-2">ID</th><th className="pb-2">Category</th><th className="pb-2">Scenario</th><th className="pb-2">Log-only</th><th className="pb-2">Enforced</th></tr></thead>
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
  )
}

function BeforeAfter({ cmp }: { cmp: Comparison }) {
  const { before: b, after: a } = cmp
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card title="Policy log-only">
        <div className="grid grid-cols-2 gap-3">
          <Stat label="Passing" value={`${b.pass} / ${b.total}`} tone="warn" />
          <Stat label="Unsafe actions succeeded" value={b.unsafe} tone={b.unsafe ? 'fail' : 'pass'} />
          <Stat label="Legitimate tasks" value={`${b.legit_pass} / ${b.legit_total}`} tone="pass" />
        </div>
      </Card>
      <Card title="Policy enforced">
        <div className="grid grid-cols-2 gap-3">
          <Stat label="Passing" value={`${a.pass} / ${a.total}`} tone={a.pass === a.total ? 'pass' : 'warn'} />
          <Stat label="Unsafe actions blocked" value={a.blocked} tone="pass" sub={a.unsafe ? `${a.unsafe} still unsafe` : 'none still unsafe'} />
          <Stat label="Legitimate tasks" value={`${a.legit_pass} / ${a.legit_total}`} tone={a.legit_pass === a.legit_total ? 'pass' : 'fail'} sub="still working" />
        </div>
      </Card>
    </div>
  )
}

export function Replay({ cmp, holdout, onValidate, busy }: { cmp: Comparison | null; holdout: Comparison | null; onValidate: () => void; busy: boolean }) {
  if (!cmp) return <Card title="Replay"><p className="text-sm text-muted">Apply a policy on the Protect stage to replay the same scenarios with enforcement on. Then validate it on attacks it has never seen.</p></Card>
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-2 flex items-baseline gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">1 · Same scenarios, before and after</h2>
          <span className="text-xs text-muted">The policy was compiled from these findings, so this proves the pipeline: what was found is now blocked.</span>
        </div>
        <BeforeAfter cmp={cmp} />
        <Card className="mt-4" title="Scenario by scenario"><CompareTable cmp={cmp} caption="Same scenarios before and after enforcement" /></Card>
      </div>

      <div>
        <div className="mb-2 flex flex-wrap items-baseline gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">2 · Unseen scenarios, written after the policy</h2>
          <span className="text-xs text-muted">Bedrock authors fresh attacks and legitimate tasks it is told not to repeat; each is run without and with enforcement. This is the evidence the policy generalises.</span>
        </div>
        {holdout ? (
          <>
            <BeforeAfter cmp={holdout} />
            <Card className="mt-4" title={`${holdout.scenarios.length} held-out scenarios`} right={<Button kind="ghost" onClick={onValidate} disabled={busy}>Author another set</Button>}>
              <CompareTable cmp={holdout} caption="Held-out scenarios before and after enforcement" />
            </Card>
          </>
        ) : (
          <Card>
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-sm text-muted">Nothing here yet. Authoring takes about a minute, then the set runs twice.</p>
              <span className="ml-auto" />
              <Button onClick={onValidate} disabled={busy}>{busy ? 'Working…' : 'Validate on unseen attacks'}</Button>
            </div>
          </Card>
        )}
      </div>
    </div>
  )
}
