import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { AgentSpec, Comparison, Job, Run, RunListItem, ScenarioResult } from './types'
import { Define } from './components/Define'
import { Scorecard } from './components/Scorecard'
import { Trace } from './components/Trace'
import { Protect } from './components/Protect'
import { Replay } from './components/Replay'
import { Button, Card, VerdictBadge } from './components/ui'

type Stage = 'define' | 'rehearse' | 'diagnose' | 'protect' | 'replay'
const STAGES: { id: Stage; label: string; n: number }[] = [
  { id: 'define', label: 'Define', n: 0 },
  { id: 'rehearse', label: 'Rehearse', n: 1 },
  { id: 'diagnose', label: 'Diagnose', n: 2 },
  { id: 'protect', label: 'Protect', n: 3 },
  { id: 'replay', label: 'Replay', n: 4 },
]

export default function App() {
  const [stage, setStage] = useState<Stage>('define')
  const [spec, setSpec] = useState<AgentSpec | null>(null)
  const [cedar, setCedar] = useState('')
  const [model, setModel] = useState<'bedrock' | 'scripted'>('bedrock')
  const [runs, setRuns] = useState<RunListItem[]>([])
  const [before, setBefore] = useState<Run | null>(null)
  const [after, setAfter] = useState<Run | null>(null)
  const [cmp, setCmp] = useState<Comparison | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [selected, setSelected] = useState<ScenarioResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const poll = useRef<number | null>(null)

  const refreshRuns = useCallback(() => api.runs().then((r) => setRuns(r.runs)).catch(() => {}), [])

  useEffect(() => {
    api.spec().then(setSpec).catch((e) => setErr(String(e)))
    api.policy().then((p) => setCedar(p.cedar)).catch(() => {})
    refreshRuns()
  }, [refreshRuns])

  function watch(j: Job, onDone: (run: Run) => void) {
    setJob(j)
    if (poll.current) window.clearInterval(poll.current)
    poll.current = window.setInterval(async () => {
      const cur = await api.job(j.job_id)
      setJob(cur)
      if (cur.status !== 'running') {
        window.clearInterval(poll.current!)
        poll.current = null
        if (cur.status === 'done' && cur.run_id) { onDone(await api.run(cur.run_id)); refreshRuns() }
        if (cur.status === 'error') setErr(cur.error)
      }
    }, 700)
  }

  async function rehearse() {
    setErr(null); setAfter(null); setCmp(null); setSelected(null)
    try {
      const j = await api.startRun({ mode: 'rehearse', model, attack_runs: 3, workers: 4 })
      setStage('rehearse')
      watch(j, (r) => setBefore(r))
    } catch (e) { setErr(String(e)) }
  }

  async function replay() {
    if (!before) return
    setErr(null)
    try {
      const j = await api.startRun({ mode: 'enforce', model, attack_runs: 3, workers: 4, base_run_id: before.run_id, cedar })
      setStage('replay')
      watch(j, async (r) => { setAfter(r); setCmp(await api.compare(before.run_id, r.run_id)) })
    } catch (e) { setErr(String(e)) }
  }

  async function loadRun(id: string) {
    const r = await api.run(id)
    setSelected(null)
    if (r.mode === 'rehearse') { setBefore(r); setAfter(null); setCmp(null); setCedar(r.policy_cedar); setStage('rehearse') }
    else { setAfter(r); if (r.base_run_id) { const b = await api.run(r.base_run_id); setBefore(b); setCmp(await api.compare(b.run_id, r.run_id)) } setStage('replay') }
  }

  const running = job?.status === 'running'
  const shownRun = stage === 'replay' && after ? after : before

  return (
    <div className="min-h-full">
      <header className="border-b border-line bg-panel/60 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
          <div>
            <div className="text-base font-bold tracking-tight">AgentRehearsal</div>
            <div className="text-[11px] text-muted">Crash-test your AI agent before your users do.</div>
          </div>
          <nav className="flex items-center gap-1">
            {STAGES.map((s) => (
              <button key={s.id} onClick={() => setStage(s.id)} className={`rounded-md px-3 py-1.5 text-sm font-medium ${stage === s.id ? 'bg-panel-2 text-text' : 'text-muted hover:text-text'}`}>
                <span className="mr-1.5 font-mono text-[10px] text-muted">{s.n}</span>{s.label}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <select value={model} onChange={(e) => setModel(e.target.value as 'bedrock' | 'scripted')} className="rounded border border-line bg-panel-2 px-2 py-1.5 text-xs">
              <option value="bedrock">Target model: Bedrock</option>
              <option value="scripted">Target model: scripted (offline sim)</option>
            </select>
            <Button onClick={rehearse} disabled={running || !spec}>{running && job?.mode === 'rehearse' ? 'Rehearsing…' : '▶ Run Rehearsal'}</Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-4 px-4 py-5">
        {err && <div className="rounded border border-fail/40 bg-fail/10 p-3 text-sm text-fail">{err}</div>}
        {running && job && (
          <Card title={`${job.mode === 'enforce' ? 'Replaying with enforcement' : 'Rehearsing'} · ${job.progress.length} attempts complete`}>
            <div className="flex flex-wrap gap-1.5">
              {job.progress.map((p, i) => <span key={i} title={p.reason} className={`h-4 w-4 rounded-sm ${p.verdict === 'PASS' ? 'bg-pass' : p.verdict === 'FAIL' ? 'bg-fail' : 'bg-warn'}`} />)}
              <span className="h-4 w-4 animate-pulse rounded-sm bg-panel-2" />
            </div>
            <ul className="mt-3 max-h-40 space-y-1 overflow-auto font-mono text-xs text-muted">
              {[...job.progress].reverse().slice(0, 30).map((p, i) => <li key={i}><VerdictBadge v={p.verdict} /> <span className="text-text">{p.scenario_id}#{p.attempt}</span> {p.reason}</li>)}
            </ul>
          </Card>
        )}

        {stage === 'define' && spec && <Define spec={spec} onSpec={(s) => { setSpec(s); api.policy().then((p) => setCedar(p.cedar)) }} cedar={cedar} />}

        {stage === 'rehearse' && (before ? <Scorecard run={before} onOpen={(s) => { setSelected(s); setStage('diagnose') }} /> : !running && (
          <Card title="Rehearse">
            <p className="text-sm text-muted">Press <b>Run Rehearsal</b> to generate and run scenarios against {spec?.name ?? 'the agent'} with the policy in log-only mode. Or open a stored run:</p>
            <RunList runs={runs} onLoad={loadRun} />
          </Card>
        ))}

        {stage === 'diagnose' && (selected && shownRun ? <Trace scenario={selected} spec={shownRun.spec} mode={shownRun.mode} onBack={() => setStage(shownRun.mode === 'enforce' ? 'replay' : 'rehearse')} /> : (
          <Card title="Diagnose"><p className="text-sm text-muted">Pick a scenario from a scorecard to see its full reasoning path.</p></Card>
        ))}

        {stage === 'protect' && <Protect run={before} cedar={cedar} onCedar={setCedar} onReplay={replay} busy={running} />}

        {stage === 'replay' && (after ? (
          <div className="space-y-4">
            <Replay cmp={cmp} />
            <Scorecard run={after} onOpen={(s) => { setSelected(s); setStage('diagnose') }} />
          </div>
        ) : !running && <Replay cmp={null} />)}

        {stage !== 'define' && runs.length > 0 && !running && (
          <details className="text-xs text-muted"><summary className="cursor-pointer">Stored runs ({runs.length})</summary><RunList runs={runs} onLoad={loadRun} /></details>
        )}
      </main>
    </div>
  )
}

function RunList({ runs, onLoad }: { runs: RunListItem[]; onLoad: (id: string) => void }) {
  return (
    <ul className="mt-3 divide-y divide-line rounded border border-line">
      {runs.map((r) => (
        <li key={r.run_id} className="flex cursor-pointer items-center gap-3 px-3 py-2 text-xs hover:bg-panel-2" onClick={() => onLoad(r.run_id)}>
          <span className="font-mono text-muted">{r.run_id}</span>
          <span className={`rounded px-1.5 py-0.5 font-mono ${r.mode === 'enforce' ? 'bg-pass/15 text-pass' : 'bg-warn/15 text-warn'}`}>{r.mode}</span>
          <span className="text-muted">{r.model}</span>
          <span className="ml-auto font-mono">{r.summary.pass}/{r.summary.total} pass</span>
          {r.example && <span className="rounded bg-panel-2 px-1.5 py-0.5 text-[10px] text-muted">example</span>}
        </li>
      ))}
    </ul>
  )
}
