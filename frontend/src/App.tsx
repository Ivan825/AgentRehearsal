import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, session } from './api'
import type { AgentSpec, Comparison, Job, Run, RunListItem, ScenarioResult } from './types'
import { Define } from './components/Define'
import { Scorecard } from './components/Scorecard'
import { Trace } from './components/Trace'
import { Protect } from './components/Protect'
import { Replay } from './components/Replay'
import { LiveRun } from './components/LiveRun'
import { Landing } from './components/Landing'
import { Button, Card } from './components/ui'
import { Logo, useTheme } from './site/Shell'

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
  const [models, setModels] = useState<{ id: string; label: string; note?: string }[]>([])
  const [modelId, setModelId] = useState<string>(() => { try { return localStorage.getItem('ar-model') || '' } catch { return '' } })
  useEffect(() => { try { localStorage.setItem('ar-model', modelId) } catch { /* ignore */ } }, [modelId])
  const [runs, setRuns] = useState<RunListItem[]>([])
  const [before, setBefore] = useState<Run | null>(null)
  const [after, setAfter] = useState<Run | null>(null)
  const [cmp, setCmp] = useState<Comparison | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [selected, setSelected] = useState<ScenarioResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const poll = useRef<number | null>(null)
  const { theme, toggle } = useTheme()
  const nav = useNavigate()
  const user = session.user

  const refreshRuns = useCallback(() => api.runs().then((r) => setRuns(r.runs)).catch(() => {}), [])

  useEffect(() => {
    api.spec().then(setSpec).catch((e) => setErr(String(e)))
    api.policy().then((p) => setCedar(p.cedar)).catch(() => {})
    api.models().then((m) => { setModels(m.models); setModelId((cur) => cur || m.default) }).catch(() => {})
    refreshRuns()
  }, [refreshRuns])

  function watch(j: Job, onDone: (run: Run) => void) {
    setJob(j)
    if (poll.current) window.clearInterval(poll.current)
    poll.current = window.setInterval(async () => {
      let cur: Job
      try { cur = await api.job(j.job_id) } catch (e) {
        window.clearInterval(poll.current!); poll.current = null
        setJob(null); setErr('The API restarted while this run was in progress, so the run was lost. Start it again.')
        return
      }
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
      const j = await api.startRun({ mode: 'rehearse', model, model_id: model === 'bedrock' ? (spec?.model_id || modelId || null) : null, attack_runs: 3, workers: 1 })
      setStage('rehearse')
      watch(j, (r) => setBefore(r))
    } catch (e) { setErr(String(e)) }
  }

  async function replay() {
    if (!before) return
    setErr(null)
    try {
      const j = await api.startRun({ mode: 'enforce', model, model_id: model === 'bedrock' ? (spec?.model_id || modelId || null) : null, attack_runs: 3, workers: 1, base_run_id: before.run_id, cedar })
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
          <Link to="/" className="flex items-center gap-2.5">
            <Logo />
            <div>
              <div className="text-base font-bold tracking-tight">AgentRehearsal</div>
              <div className="hidden text-[11px] text-muted xl:block">{user ? user.email : 'Crash-test your AI agent before your users do.'}</div>
            </div>
          </Link>
          <nav className="flex items-center gap-1">
            {STAGES.map((s) => (
              <button key={s.id} onClick={() => setStage(s.id)} className={`rounded-md px-3 py-1.5 text-sm font-medium ${stage === s.id ? 'bg-panel-2 text-text' : 'text-muted hover:text-text'}`}>
                <span className="mr-1.5 font-mono text-[10px] text-muted">{s.n}</span>{s.label}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <Link to="/guides" className="hidden px-2 text-xs text-muted hover:text-text lg:block">Guides</Link>
            <button onClick={toggle} title="Toggle theme" className="rounded-md border border-line px-2.5 py-1.5 text-xs text-muted hover:text-text">
              {theme === 'dark' ? '☀' : '☾'}
            </button>
            {user && <button onClick={() => { session.clear(); nav('/') }} className="rounded-md border border-line px-2.5 py-1.5 text-xs text-muted hover:text-text">Sign out</button>}
            <div className="hidden items-center gap-2 rounded border border-line bg-panel-2 px-2 py-1.5 text-xs md:flex" title="Set on the Define tab">
              <span className="text-muted">Agent</span><span className="font-semibold">{spec?.name ?? '…'}</span>
              <span className="text-muted">on</span>
              <span className="font-mono">{spec?.target?.kind === 'http' ? 'external · HTTP' : spec?.target?.kind === 'agentcore_runtime' ? 'external · AgentCore' : (models.find((m) => m.id === (spec?.model_id || modelId))?.label ?? spec?.model_id ?? modelId ?? 'default')}</span>
            </div>
            <label className="flex items-center gap-1.5 rounded border border-line px-2 py-1.5 text-xs text-muted" title="Offline simulation of a naive agent (no AWS)">
              <input type="checkbox" checked={model === 'scripted'} onChange={(e) => setModel(e.target.checked ? 'scripted' : 'bedrock')} /> offline sim
            </label>
            <Button onClick={rehearse} disabled={running || !spec}>{running && job?.mode === 'rehearse' ? 'Rehearsing…' : '▶ Run Rehearsal'}</Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-4 px-4 py-5">
        {err && <div className="rounded border border-fail/40 bg-fail/10 p-3 text-sm text-fail">{err}</div>}
        {running && job && <LiveRun job={job} />}

        {stage === 'define' && spec && <Define spec={spec} onSpec={(s) => { setSpec(s); api.policy().then((p) => setCedar(p.cedar)) }} cedar={cedar} />}

        {stage === 'rehearse' && (before ? <Scorecard run={before} onOpen={(s) => { setSelected(s); setStage('diagnose') }} /> : !running && (
          <Landing agent={spec?.name ?? 'the agent'} onRun={rehearse} runs={runs} onLoad={loadRun} />
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
