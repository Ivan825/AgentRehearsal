import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, session } from './api'
import type { AgentSpec, Comparison, Constraint, Job, Run, RunListItem, Scenario, ScenarioResult } from './types'
import { Define } from './components/Define'
import { Scorecard } from './components/Scorecard'
import { Trace } from './components/Trace'
import { Protect, type Hardened } from './components/Protect'
import { Replay } from './components/Replay'
import { LiveRun } from './components/LiveRun'
import { Landing } from './components/Landing'
import { Live } from './components/Live'
import { Button, Card } from './components/ui'
import { Logo, useTheme } from './site/Shell'

type Stage = 'define' | 'rehearse' | 'diagnose' | 'protect' | 'replay'
const STAGES: { id: Stage; label: string; n: number; hint: string }[] = [
  { id: 'define', label: 'Define', n: 0, hint: 'the agent, its tools, its rules' },
  { id: 'rehearse', label: 'Rehearse', n: 1, hint: 'run every scenario, policy log-only' },
  { id: 'diagnose', label: 'Diagnose', n: 2, hint: 'the exact call that broke a rule' },
  { id: 'protect', label: 'Protect', n: 3, hint: 'findings → Cedar policy' },
  { id: 'replay', label: 'Replay', n: 4, hint: 'enforce, then validate on unseen attacks' },
]

export default function App() {
  const [stage, setStage] = useState<Stage>('define')
  const [spec, setSpec] = useState<AgentSpec | null>(null)
  const [cedar, setCedar] = useState('')
  const [compiledCedar, setCompiledCedar] = useState('')
  const [model, setModel] = useState<'bedrock' | 'scripted'>('bedrock')
  const [modelId, setModelId] = useState<string>(() => { try { return localStorage.getItem('ar-model') || '' } catch { return '' } })
  useEffect(() => { try { localStorage.setItem('ar-model', modelId) } catch { /* ignore */ } }, [modelId])
  const [runs, setRuns] = useState<RunListItem[]>([])
  const [before, setBefore] = useState<Run | null>(null)
  const [after, setAfter] = useState<Run | null>(null)
  const [cmp, setCmp] = useState<Comparison | null>(null)
  const [holdout, setHoldout] = useState<Comparison | null>(null)
  const [hardened, setHardened] = useState<Hardened | null>(null)
  const [liveScenarios, setLiveScenarios] = useState<Scenario[]>([])
  const [escalated, setEscalated] = useState<{ rounds: { round: number; run_id: string; tried: number; found: number }[]; found: number; added: number } | null>(null)
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
    api.policy().then((p) => { setCedar(p.cedar); setCompiledCedar(p.cedar) }).catch(() => {})
    api.models().then((m) => setModelId((cur) => cur || m.default)).catch(() => {})
    api.scenarios().then((r) => setLiveScenarios(r.scenarios)).catch(() => {})
    refreshRuns()
  }, [refreshRuns])

  const chosenModel = () => (model === 'bedrock' ? (spec?.model_id || modelId || null) : null)

  function watch(j: Job, onDone: (run: Run, job: Job) => void | Promise<void>) {
    setJob(j)
    if (poll.current) window.clearInterval(poll.current)
    poll.current = window.setInterval(async () => {
      let cur: Job
      try { cur = await api.job(j.job_id) } catch {
        window.clearInterval(poll.current!); poll.current = null
        setJob(null); setErr('The API restarted while this run was in progress, so the run was lost. Start it again.')
        return
      }
      setJob(cur)
      if (cur.status !== 'running') {
        window.clearInterval(poll.current!)
        poll.current = null
        if (cur.status === 'done' && cur.run_id) { await onDone(await api.run(cur.run_id), cur); refreshRuns() }
        if (cur.status === 'error') setErr(cur.error)
      }
    }, 700)
  }

  async function rehearse() {
    setErr(null); setAfter(null); setCmp(null); setHoldout(null); setHardened(null); setEscalated(null); setSelected(null)
    try {
      const j = await api.startRun({ mode: 'rehearse', model, model_id: chosenModel(), attack_runs: 3, workers: 1 })
      setStage('rehearse')
      watch(j, (r) => setBefore(r))
    } catch (e) { setErr(String(e)) }
  }

  async function replay() {
    if (!before) return
    setErr(null); setHoldout(null)
    try {
      const j = await api.startRun({ mode: 'enforce', model, model_id: chosenModel(), attack_runs: 3, workers: 1, base_run_id: before.run_id, cedar })
      setStage('replay')
      watch(j, async (r) => { setAfter(r); setCmp(await api.compare(before.run_id, r.run_id)) })
    } catch (e) { setErr(String(e)) }
  }

  async function validate() {
    if (!after) return
    setErr(null)
    try {
      const j = await api.validate({ base_run_id: after.run_id, per_constraint: 2, model, model_id: chosenModel(), attack_runs: 3 })
      setStage('replay')
      watch(j, async (_r, done) => {
        const res = done.result as { before_run: string; after_run: string } | undefined
        if (res) setHoldout(await api.compare(res.before_run, res.after_run))
      })
    } catch (e) { setErr(String(e)) }
  }

  async function harden() {
    if (!before) return
    setErr(null)
    try {
      const j = await api.harden({ base_run_id: before.run_id, model, model_id: chosenModel(), attack_runs: 3 })
      setStage('protect')
      watch(j, async (r, done) => {
        const res = done.result as { system_prompt: string; changes: string[] } | undefined
        if (res) setHardened({ system_prompt: res.system_prompt, changes: res.changes, run: r })
      })
    } catch (e) { setErr(String(e)) }
  }

  async function escalate() {
    if (!before) return
    setErr(null)
    try {
      const j = await api.escalate({ base_run_id: before.run_id, rounds: 2, model, model_id: chosenModel(), attack_runs: 1 })
      setStage('rehearse')
      watch(j, async (_r, done) => {
        const res = done.result as { rounds: { round: number; run_id: string; tried: number; found: number }[]; found: number; added: number } | undefined
        if (res) setErr(null)
        if (res) setEscalated(res)
      })
    } catch (e) { setErr(String(e)) }
  }

  async function applyPrompt(system_prompt: string) {
    try { setSpec(await api.applyPrompt(system_prompt)) } catch (e) { setErr(String(e)) }
  }

  async function addConstraint(c: Constraint) {
    if (!spec) return
    try {
      const next = await api.saveSpec({ ...spec, constraints: [...spec.constraints.filter((x) => x.id !== c.id), c] })
      setSpec(next); const p = await api.policy(); setCedar(p.cedar); setCompiledCedar(p.cedar)
    } catch (e) { setErr(String(e)) }
  }

  async function loadRun(id: string) {
    const r = await api.run(id)
    setSelected(null); setErr(null)
    if (r.holdout) {
      // a held-out validation run: show it under the enforce run it validates
      const enforceHold = r.mode === 'enforce' ? r : null
      const holdBefore = r.mode === 'enforce' && r.base_run_id ? await api.run(r.base_run_id) : r
      if (enforceHold) setHoldout(await api.compare(holdBefore.run_id, enforceHold.run_id))
      const validated = enforceHold?.validates_run_id ? await api.run(enforceHold.validates_run_id) : null
      if (validated) {
        setAfter(validated); setCedar(validated.policy_cedar)
        if (validated.base_run_id) { const b = await api.run(validated.base_run_id); setBefore(b); setCmp(await api.compare(b.run_id, validated.run_id)) }
      }
      setStage('replay')
      return
    }
    setHoldout(null)
    if (r.mode === 'rehearse') { setBefore(r); setAfter(null); setCmp(null); setCedar(r.policy_cedar); setStage('rehearse') }
    else { setAfter(r); setCedar(r.policy_cedar); if (r.base_run_id) { const b = await api.run(r.base_run_id); setBefore(b); setCmp(await api.compare(b.run_id, r.run_id)) } setStage('replay') }
  }

  const running = job?.status === 'running'
  const shownRun = stage === 'replay' && after ? after : before
  const hasConstraints = (spec?.constraints.length ?? 0) > 0
  const done: Record<Stage, boolean> = { define: hasConstraints, rehearse: !!before, diagnose: !!before, protect: !!after || !!hardened, replay: !!holdout }

  // the one thing to do next, so a first-time user is never guessing
  const next = !hasConstraints
    ? { text: 'Define the agent: load an example or parse your own rules into constraints.', action: () => setStage('define'), label: 'Open Define' }
    : !before
      ? (spec?.target?.kind === 'mcp_client'
        ? { text: `Live rehearsal: connect ${spec.name} to the workspace MCP URL, then run scenarios one at a time by pasting their prompts into it.`, action: () => setStage('rehearse'), label: '▶ Live rehearsal' }
        : { text: `Rehearse: run every scenario on the Define tab (seeds plus anything Bedrock authored) against ${spec?.name ?? 'the agent'} with the policy in log-only mode.`, action: rehearse, label: '▶ Run Rehearsal' })
      : !after
        ? { text: `${before.summary.attacks_unsafe} of ${before.summary.attacks_total} attacks got through. Protect compiles the findings into a Cedar policy; replay proves it blocks them.`, action: () => setStage('protect'), label: 'Open Protect' }
        : !holdout
          ? { text: 'The replay used the scenarios the policy was built from. Validate on attacks written after the policy existed to show it generalises.', action: validate, label: 'Validate on unseen attacks' }
          : { text: 'Done: rehearsed, protected, replayed and validated on unseen attacks. Export the reports from any scorecard.', action: () => setStage('replay'), label: 'View results' }

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
          <nav className="flex items-center gap-1" aria-label="Stages">
            {STAGES.map((s) => (
              <button key={s.id} onClick={() => setStage(s.id)} title={s.hint} aria-current={stage === s.id ? 'step' : undefined}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium ${stage === s.id ? 'bg-panel-2 text-text' : 'text-muted hover:text-text'}`}>
                <span className={`inline-flex h-4 w-4 items-center justify-center rounded-full font-mono text-[10px] ${done[s.id] ? 'bg-pass/20 text-pass' : 'bg-panel-2 text-muted'}`}>{done[s.id] ? '✓' : s.n}</span>
                {s.label}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <Link to="/guides" className="hidden px-2 text-xs text-muted hover:text-text lg:block">Guides</Link>
            <button onClick={toggle} title="Toggle theme" className="rounded-md border border-line px-2.5 py-1.5 text-xs text-muted hover:text-text">
              {theme === 'dark' ? '☀' : '☾'}
            </button>
            {user && <button onClick={() => { session.clear(); nav('/') }} className="rounded-md border border-line px-2.5 py-1.5 text-xs text-muted hover:text-text">Sign out</button>}
            <label className="flex items-center gap-1.5 rounded border border-line px-2 py-1.5 text-xs text-muted" title="Offline simulation of a naive agent (no AWS). Models the SupportBot example only.">
              <input type="checkbox" checked={model === 'scripted'} onChange={(e) => setModel(e.target.checked ? 'scripted' : 'bedrock')} /> offline sim
            </label>
            <Button onClick={spec?.target?.kind === 'mcp_client' ? () => setStage('rehearse') : rehearse} disabled={running || !spec}>{running && job?.kind === 'run' && job?.mode === 'rehearse' ? 'Rehearsing…' : spec?.target?.kind === 'mcp_client' ? '▶ Live rehearsal' : '▶ Run Rehearsal'}</Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-4 px-4 py-5">
        {!running && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-accent/30 bg-accent/5 px-4 py-2.5 text-sm">
            <span className="rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-accent">next</span>
            <span className="text-text">{next.text}</span>
            <span className="ml-auto" />
            <Button kind="ghost" onClick={next.action} disabled={!spec}>{next.label}</Button>
          </div>
        )}
        {err && <div className="rounded border border-fail/40 bg-fail/10 p-3 text-sm text-fail">{err}</div>}
        {running && job && <LiveRun job={job} />}

        {stage === 'define' && spec && <Define spec={spec} onSpec={(s) => { setSpec(s); api.policy().then((p) => { setCedar(p.cedar); setCompiledCedar(p.cedar) }); api.scenarios().then((r) => setLiveScenarios(r.scenarios)).catch(() => {}) }} cedar={cedar} />}

        {stage === 'rehearse' && escalated && !running && (
          <div className="rounded-lg border border-accent/30 bg-accent/5 px-4 py-2.5 text-sm">
            <span className="font-semibold">Escalation done:</span> {escalated.added} harder variant{escalated.added === 1 ? '' : 's'} tried over {escalated.rounds.length} round{escalated.rounds.length === 1 ? '' : 's'}, {escalated.found} got through{escalated.found ? ' — they are in the scenario list now; run the rehearsal again to fold them into the findings' : ' — the agent held on every variant'}.
            {escalated.rounds.map((r) => <span key={r.round} className="ml-2 font-mono text-xs text-muted">round {r.round}: {r.found}/{r.tried}</span>)}
          </div>
        )}
        {stage === 'rehearse' && spec?.target?.kind === 'mcp_client' && !running && <Live scenarios={liveScenarios} cedar={cedar} before={before} onRun={loadRun} onScenarios={() => api.scenarios().then((r) => setLiveScenarios(r.scenarios)).catch(() => {})} />}
        {stage === 'rehearse' && spec?.target?.kind === 'mcp_client' && !running && before && <Scorecard run={before} onOpen={(s) => { setSelected(s); setStage('diagnose') }} />}
        {stage === 'rehearse' && spec?.target?.kind !== 'mcp_client' && (before ? <Scorecard run={before} onOpen={(s) => { setSelected(s); setStage('diagnose') }} onEscalate={escalate} busy={running} /> : !running && (
          <Landing agent={spec?.name ?? 'the agent'} onRun={rehearse} runs={runs} onLoad={loadRun} />
        ))}

        {stage === 'diagnose' && (selected && shownRun ? <Trace scenario={selected} spec={shownRun.spec} mode={shownRun.mode} onBack={() => setStage(shownRun.mode === 'enforce' ? 'replay' : 'rehearse')} /> : (
          <Card title="Diagnose"><p className="text-sm text-muted">Pick a scenario from a scorecard to see its full reasoning path: the prompt, every tool call with its arguments, the policy decision and the rule behind it.</p></Card>
        ))}

        {stage === 'protect' && <Protect run={before} after={after} cedar={cedar} compiledCedar={compiledCedar} onCedar={setCedar} onReplay={replay} busy={running} hardened={hardened} onHarden={harden} onApplyPrompt={applyPrompt} onAddConstraint={addConstraint} />}

        {stage === 'replay' && (after ? (
          <div className="space-y-4">
            <Replay cmp={cmp} holdout={holdout} onValidate={validate} busy={running} />
            <Scorecard run={after} onOpen={(s) => { setSelected(s); setStage('diagnose') }} />
          </div>
        ) : !running && <Replay cmp={null} holdout={null} onValidate={validate} busy={running} />)}

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
          {r.holdout && <span className="rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[10px] text-accent">held-out</span>}
          {r.variant === 'hardened_prompt' && <span className="rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[10px] text-accent">hardened prompt</span>}
          <span className="text-muted">{r.model}</span>
          <span className="ml-auto font-mono">{r.summary.pass}/{r.summary.total} pass</span>
          {r.example && <span className="rounded bg-panel-2 px-1.5 py-0.5 text-[10px] text-muted">example</span>}
        </li>
      ))}
    </ul>
  )
}
