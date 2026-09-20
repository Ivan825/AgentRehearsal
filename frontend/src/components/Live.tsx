import { useEffect, useRef, useState } from 'react'
import type { LiveStatus, Run, Scenario } from '../types'
import { api } from '../api'
import { Button, Card, Category, VerdictBadge, fmtArgs } from './ui'

/** Live rehearsal: the agent is an MCP client (goose, Cline, Claude Code, OpenHands…) connected to the workspace
 *  MCP URL. One session = one scenario attempt: start, paste the prompt into the agent, stop; the verdict comes
 *  from the calls that arrived through the proxy. Finish turns the sessions into a stored run. */
export function Live({ scenarios, cedar, before, onRun }: { scenarios: Scenario[]; cedar: string; before: Run | null; onRun: (runId: string) => void }) {
  const [mode, setMode] = useState<'rehearse' | 'enforce'>(before ? 'enforce' : 'rehearse')
  const [status, setStatus] = useState<LiveStatus | null>(null)
  const [mcp, setMcp] = useState<{ url: string; upstream?: string; forwarding?: boolean; mcp_json?: unknown } | null>(null)
  const [reply, setReply] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [last, setLast] = useState<{ scenario_id: string; verdict: string; reason: string } | null>(null)
  const timer = useRef<number | null>(null)

  const refresh = () => api.liveStatus().then(setStatus).catch(() => {})
  useEffect(() => { refresh(); api.workspaceMcp().then(setMcp).catch(() => {}) }, [])
  useEffect(() => {
    if (timer.current) window.clearInterval(timer.current)
    timer.current = window.setInterval(refresh, status?.open ? 1000 : 4000)
    return () => { if (timer.current) window.clearInterval(timer.current) }
  }, [status?.open])

  const act = async (fn: () => Promise<unknown>) => { setErr(null); try { await fn(); await refresh() } catch (e) { setErr(String(e)) } }
  const start = (id: string) => act(() => api.liveStart(id, mode, mode === 'enforce' ? cedar : undefined))
  const stop = () => act(async () => { const r = await api.liveStop(reply); setLast(r); setReply('') })
  const finish = () => act(async () => { const r = await api.liveFinish(mode === 'enforce' ? before?.run_id ?? null : null); onRun(r.run_id) })
  const done = status?.done ?? {}
  const doneCount = Object.keys(done).length

  return (
    <div className="space-y-4">
      <Card title="Live rehearsal · your agent connects to AgentRehearsal" right={<span className="text-xs text-muted">any MCP client · no adapter</span>}>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="text-sm text-muted">
            <p>Add this to your agent's MCP config (goose, Cline, Claude Code, OpenHands, Cursor…). AgentRehearsal serves the tools defined on Define{mcp?.upstream ? <>, proxying to <code className="text-accent">{mcp.upstream}</code>{mcp.forwarding ? ' (allowed calls are forwarded for real)' : ' (answers with the simulated responses; forwarding is off)'}</> : ''}. Every call is recorded and judged; in enforce mode a denied call gets a tool error instead of running.</p>
            <pre className="mt-2 overflow-auto rounded border border-line bg-ink p-2 font-mono text-[11px] text-text">{JSON.stringify(mcp?.mcp_json ?? { mcpServers: { agentrehearsal: { type: 'http', url: mcp?.url ?? '…' } } }, null, 2)}</pre>
            <div className="mt-2 flex items-center gap-2">
              <button onClick={() => mcp && navigator.clipboard?.writeText(JSON.stringify(mcp.mcp_json, null, 2))} className="rounded border border-line px-2 py-1 text-xs hover:text-text">copy config</button>
              <span className="text-xs">Mode</span>
              <select value={mode} onChange={(e) => setMode(e.target.value as 'rehearse' | 'enforce')} disabled={!!status?.open} className="rounded border border-line bg-ink px-2 py-1 text-xs text-text">
                <option value="rehearse">log-only (rehearse)</option>
                <option value="enforce">enforce (policy from Protect{before ? ', replays ' + before.run_id : ''})</option>
              </select>
            </div>
          </div>
          <div>
            {status?.open ? (
              <div className="rounded border border-accent/40 bg-accent/5 p-3">
                <div className="flex items-center justify-between text-xs"><span className="font-semibold text-text">Session open · {status.open.scenario_id}</span><span className="font-mono text-muted">{status.open.seconds}s · {status.open.calls.length} call{status.open.calls.length === 1 ? '' : 's'}</span></div>
                <div className="mt-1 text-[11px] uppercase tracking-wider text-muted">Paste this into your agent</div>
                <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded bg-ink p-2 font-mono text-[11px] text-text">{status.open.prompt}</pre>
                <button onClick={() => navigator.clipboard?.writeText(status.open!.prompt)} className="mt-1 rounded border border-line px-2 py-0.5 text-[11px] hover:text-text">copy prompt</button>
                <ul className="mt-2 space-y-1 font-mono text-[11px]">
                  {status.open.calls.map((c) => <li key={c.seq} className={c.allowed ? 'text-pass' : 'text-fail'}>{c.allowed ? '✓' : c.blocked ? '✗ blocked' : '! denied (logged)'} {c.tool}({fmtArgs(c.args)})</li>)}
                  {status.open.calls.length === 0 && <li className="text-muted">waiting for the agent's first tool call…</li>}
                </ul>
                <input value={reply} onChange={(e) => setReply(e.target.value)} placeholder="the agent's final reply (optional, for the record)" className="mt-2 w-full rounded border border-line bg-ink px-2 py-1 text-xs text-text outline-none focus:border-accent" />
                <div className="mt-2"><Button onClick={stop}>Stop & judge</Button></div>
              </div>
            ) : (
              <div className="rounded border border-line bg-panel-2 p-3 text-sm text-muted">
                {last ? <div>Last: <span className="font-mono">{last.scenario_id}</span> <VerdictBadge v={last.verdict} /> <span className="text-xs">{last.reason}</span></div> : 'Pick a scenario below to open a session.'}
                {doneCount > 0 && <div className="mt-2 flex items-center gap-2"><span className="text-xs">{doneCount} scenario{doneCount === 1 ? '' : 's'} recorded in this {mode} session.</span><Button onClick={finish}>Finish → scorecard</Button><button onClick={() => act(() => api.liveReset())} className="text-xs text-muted hover:text-fail">discard</button></div>}
              </div>
            )}
          </div>
        </div>
        {err && <div className="mt-3 rounded border border-fail/40 bg-fail/10 p-2 text-xs text-fail">{err}</div>}
      </Card>
      <Card title={`${scenarios.length} scenarios`}>
        <table className="w-full text-sm">
          <tbody>
            {scenarios.map((s) => {
              const d = done[s.id]
              return (
                <tr key={s.id} className="border-t border-line">
                  <td className="w-12 py-1.5 pr-2 font-mono text-xs text-muted">{s.id}</td>
                  <td className="w-40 py-1.5 pr-2"><Category c={s.category} /></td>
                  <td className="py-1.5 pr-2"><div>{s.title}</div><div className="line-clamp-1 text-xs text-muted">{s.prompt}</div></td>
                  <td className="w-28 py-1.5 pr-2">{d ? <span className="inline-flex gap-1">{d.map((a) => <VerdictBadge key={a.attempt} v={a.verdict} />)}</span> : null}</td>
                  <td className="w-24 py-1.5 text-right"><Button kind="ghost" onClick={() => start(s.id)} disabled={!!status?.open}>{d ? 'Again' : 'Start'}</Button></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
