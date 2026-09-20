import { useEffect, useState } from 'react'
import type { AgentSpec, Constraint, Coverage, Example, MockResponse, Scenario, ToolDef } from '../types'
import { CATEGORY_LABEL } from './ui'
import { api } from '../api'
import { Button, Card, Category } from './ui'

// shown if /api/models is unreachable, so the picker is never empty
const FALLBACK_MODELS = [
  { id: 'us.amazon.nova-lite-v1:0', label: 'Amazon Nova Lite', note: 'default', provider: 'bedrock', available: true },
  { id: 'us.amazon.nova-pro-v1:0', label: 'Amazon Nova Pro', provider: 'bedrock', available: true },
  { id: 'us.anthropic.claude-haiku-4-5-20251001-v1:0', label: 'Claude Haiku 4.5', provider: 'bedrock', available: true },
  { id: 'global.anthropic.claude-opus-4-6-v1', label: 'Claude Opus 4.6', provider: 'bedrock', available: true },
]

const KIND_TEXT: Record<string, (c: Constraint) => string> = {
  allow: () => 'always allowed',
  forbid: () => 'never allowed',
  param_max: (c) => `${c.param} ≤ ${c.value}`,
  param_min: (c) => `${c.param} ≥ ${c.value}`,
  param_in: (c) => `${c.param} ∈ {${(c.values ?? []).join(', ')}}`,
  param_equals_session: (c) => `${c.param} must equal session.${c.session_key}`,
  param_like: (c) => `${c.param} must match ${(c.values ?? []).join(' or ')}`,
  param_not_like: (c) => `${c.param} must not match ${(c.values ?? []).join(' or ')}`,
}
const CATEGORIES = ['allowed', 'boundary', 'scope_violation', 'parameter_violation', 'direct_injection', 'indirect_injection', 'destructive_action']

const input = 'w-full rounded border border-line bg-ink px-2 py-1.5 text-sm text-text outline-none focus:border-accent'
const label = 'text-[11px] uppercase tracking-wider text-muted'

function JsonField({ value, onChange, rows = 3, placeholder }: { value: unknown; onChange: (v: unknown) => void; rows?: number; placeholder?: string }) {
  const [text, setText] = useState(() => (value === undefined || value === null ? '' : JSON.stringify(value, null, 1)))
  const [bad, setBad] = useState(false)
  useEffect(() => { setText(value === undefined || value === null ? '' : JSON.stringify(value, null, 1)); setBad(false) }, [value])
  return (
    <textarea rows={rows} spellCheck={false} placeholder={placeholder} value={text}
      onChange={(e) => { setText(e.target.value); try { const v = e.target.value.trim() ? JSON.parse(e.target.value) : null; setBad(false); onChange(v) } catch { setBad(true) } }}
      className={`${input} font-mono text-xs ${bad ? 'border-fail' : ''}`} />
  )
}

function ToolEditor({ tool, onChange, onRemove }: { tool: ToolDef; onChange: (t: ToolDef) => void; onRemove: () => void }) {
  const [open, setOpen] = useState(false)
  const set = (patch: Partial<ToolDef>) => onChange({ ...tool, ...patch })
  return (
    <li className="rounded border border-line bg-panel-2">
      <div className="flex items-center gap-2 p-2.5">
        <button onClick={() => setOpen(!open)} className="text-xs text-muted">{open ? '▾' : '▸'}</button>
        <input value={tool.name} onChange={(e) => set({ name: e.target.value.replace(/[^\w]/g, '_') })} className="w-44 rounded border border-line bg-ink px-2 py-1 font-mono text-sm text-accent outline-none focus:border-accent" />
        <span className="truncate font-mono text-xs text-muted">({tool.params.map((p) => p.name).join(', ')})</span>
        <span className="ml-auto" />
        <label className="flex shrink-0 items-center gap-1 text-[10px] uppercase tracking-wider text-muted"><input type="checkbox" checked={!!tool.destructive} onChange={(e) => set({ destructive: e.target.checked })} /> destructive</label>
        <button onClick={onRemove} className="shrink-0 text-xs text-muted hover:text-fail">✕</button>
      </div>
      {open && (
        <div className="space-y-3 border-t border-line p-3">
          <div><div className={label}>Description (what the agent is told)</div><input value={tool.description} onChange={(e) => set({ description: e.target.value })} className={input} /></div>
          <div>
            <div className="flex items-center justify-between"><div className={label}>Parameters</div><button onClick={() => set({ params: [...tool.params, { name: 'param', type: 'string', description: '', required: true }] })} className="text-xs text-accent">+ add</button></div>
            <table className="mt-1 w-full text-xs">
              <tbody>
                {tool.params.map((p, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="py-1 pr-2"><input value={p.name} onChange={(e) => set({ params: tool.params.map((q, k) => k === i ? { ...q, name: e.target.value.replace(/[^\w]/g, '_') } : q) })} className={`${input} font-mono`} /></td>
                    <td className="py-1 pr-2">
                      <select value={p.type} onChange={(e) => set({ params: tool.params.map((q, k) => k === i ? { ...q, type: e.target.value } : q) })} className={input}>
                        {['string', 'integer', 'number', 'boolean'].map((t) => <option key={t}>{t}</option>)}
                      </select>
                    </td>
                    <td className="py-1 pr-2"><input value={p.description ?? ''} placeholder="description" onChange={(e) => set({ params: tool.params.map((q, k) => k === i ? { ...q, description: e.target.value } : q) })} className={input} /></td>
                    <td className="py-1 pr-2"><label className="flex items-center gap-1 text-muted"><input type="checkbox" checked={p.required !== false} onChange={(e) => set({ params: tool.params.map((q, k) => k === i ? { ...q, required: e.target.checked } : q) })} /> req</label></td>
                    <td className="py-1"><button onClick={() => set({ params: tool.params.filter((_, k) => k !== i) })} className="text-muted hover:text-fail">✕</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <div className="flex items-center justify-between">
              <div className={label}>Simulated responses (first match wins; no “when” = default; {'{{param}}'} placeholders allowed)</div>
              <button onClick={() => set({ responses: [...tool.responses, { when: null, returns: { status: 'ok' } }] })} className="text-xs text-accent">+ add</button>
            </div>
            <ul className="mt-1 space-y-2">
              {tool.responses.map((r: MockResponse, i) => (
                <li key={i} className="grid grid-cols-[2fr_3fr_auto] gap-2 rounded border border-line p-2">
                  <div><div className="text-[10px] text-muted">when (args match)</div><JsonField rows={4} value={r.when ?? null} placeholder='{"attachment_id": "inv_2202"}' onChange={(v) => set({ responses: tool.responses.map((q, k) => k === i ? { ...q, when: (v as Record<string, unknown>) ?? null } : q) })} /></div>
                  <div><div className="text-[10px] text-muted">returns</div><JsonField rows={4} value={r.returns} onChange={(v) => set({ responses: tool.responses.map((q, k) => k === i ? { ...q, returns: v } : q) })} /></div>
                  <button onClick={() => set({ responses: tool.responses.filter((_, k) => k !== i) })} className="self-start text-xs text-muted hover:text-fail">✕</button>
                </li>
              ))}
              {tool.responses.length === 0 && <li className="text-xs text-muted">No responses yet: the tool will return {'{"status": "ok"}'}.</li>}
            </ul>
          </div>
        </div>
      )}
    </li>
  )
}

function ScenarioRow({ s, onRemove }: { s: Scenario; onRemove: () => void }) {
  return (
    <li className="flex items-start gap-2 border-t border-line py-1.5 text-sm">
      <span className="w-10 shrink-0 font-mono text-xs text-muted">{s.id}</span>
      <span className="w-36 shrink-0"><Category c={s.category} /></span>
      <span className="flex-1"><div>{s.title}</div><div className="line-clamp-1 text-xs text-muted">{s.prompt}</div></span>
      <span className="shrink-0 font-mono text-[10px] text-muted">{s.expected}{s.must_call ? ` · ${s.must_call}` : ''}{s.source === 'generated' ? ' · bedrock' : s.source === 'holdout' ? ' · held-out' : s.source === 'escalated' ? ` · escalated${s.parent_id ? ` from ${s.parent_id}` : ''}` : ''}{s.expected_call?.tool ? ` · aims at ${s.expected_call.tool}` : ''}</span>
      <button onClick={onRemove} className="shrink-0 text-xs text-muted hover:text-fail">✕</button>
    </li>
  )
}

export function Define({ spec, onSpec, cedar }: { spec: AgentSpec; onSpec: (s: AgentSpec) => void; cedar: string }) {
  const [models, setModels] = useState<{ id: string; label: string; note?: string; provider?: string; available?: boolean }[]>([])
  const [mcp, setMcp] = useState<{ url: string; token: string } | null>(null)
  const [examples, setExamples] = useState<Example[]>([])
  useEffect(() => { api.models().then((m) => setModels(m.models)).catch(() => setModels(FALLBACK_MODELS)); api.workspaceMcp().then(setMcp).catch(() => {}); api.examples().then((r) => setExamples(r.examples)).catch(() => {}) }, [])
  const [draft, setDraft] = useState<AgentSpec>(spec)
  const [rules, setRules] = useState(spec.rules.join('\n'))
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [mcpUrl, setMcpUrl] = useState(''); const [mcpAuth, setMcpAuth] = useState(''); const [mcpName, setMcpName] = useState(''); const [mcpPurpose, setMcpPurpose] = useState('')
  const [fetched, setFetched] = useState<ToolDef[] | null>(null)
  const [rulesWhy, setRulesWhy] = useState<string[]>([])
  const [showConnect, setShowConnect] = useState(false)
  const [perRule, setPerRule] = useState(2)
  const [notes, setNotes] = useState<{ id: string; confidence: number; ambiguity: string }[]>([])
  const [problems, setProblems] = useState<string[]>([])
  const [coverage, setCoverage] = useState<Coverage | null>(null)
  const refreshCoverage = () => api.coverage().then(setCoverage).catch(() => {})
  useEffect(() => { refreshCoverage(); api.validateConstraints().then((r) => setProblems(r.problems)).catch(() => {}) }, [spec, scenarios.length])
  const [newSc, setNewSc] = useState<Partial<Scenario>>({ category: 'parameter_violation', expected: 'deny', prompt: '', title: '' })
  const dirty = JSON.stringify(draft) !== JSON.stringify(spec) || rules !== spec.rules.join('\n')

  useEffect(() => { setDraft(spec); setRules(spec.rules.join('\n')) }, [spec])
  useEffect(() => {
    const sync = () => api.scenarios().then((r) => setScenarios(r.scenarios)).catch(() => {})
    sync()
    window.addEventListener('focus', sync)   // another tab or teammate may have changed the list
    return () => window.removeEventListener('focus', sync)
  }, [])

  const set = (patch: Partial<AgentSpec>) => setDraft({ ...draft, ...patch })
  // the model is the one field that should never sit unsaved: a run picks it up from the server, not the draft
  const setModel = (model_id: string) => {
    const next = { ...draft, model_id }
    setDraft(next)
    api.saveSpec({ ...next, rules: rules.split('\n').map((s) => s.trim()).filter(Boolean) }).then(onSpec).catch((e) => setErr(String(e)))
  }
  const run = async (name: string, fn: () => Promise<void>) => { setBusy(name); setErr(null); setMsg(null); try { await fn() } catch (e) { setErr(String(e)) } finally { setBusy(null) } }

  const save = () => run('save', async () => {
    const lines = rules.split('\n').map((s) => s.trim()).filter(Boolean)
    const next = await api.saveSpec({ ...draft, rules: lines })
    onSpec(next); setMsg('Saved. The Cedar policy has been regenerated from the constraints.')
  })
  const reparse = () => run('parse', async () => {
    const lines = rules.split('\n').map((s) => s.trim()).filter(Boolean)
    const saved = await api.saveSpec({ ...draft, rules: lines })
    const r = await api.parseRules(lines)
    const next = await api.saveSpec({ ...saved, constraints: r.constraints })
    setNotes(r.notes); setProblems(r.problems)
    onSpec(next); setMsg(`Bedrock parsed ${r.constraints.length} constraints${r.problems.length ? `, with ${r.problems.length} problem${r.problems.length === 1 ? '' : 's'} to look at` : ''}. Check them below.`)
  })
  const loadExample = (id: string) => run('example', async () => {
    const authored = scenarios.filter((s) => s.source !== 'seed').length
    if (authored && !confirm(`Loading an example replaces the current agent and its ${scenarios.length} scenarios (${authored} authored by Bedrock). Export JSON first if you want to keep them. Continue?`)) return
    const r = await api.resetExample(id); onSpec(r.spec); const s = await api.scenarios(); setScenarios(s.scenarios)
    setMsg(r.scenarios ? `${r.example} loaded with ${r.scenarios} scenarios. Next: ▶ Run Rehearsal.` : `${r.example} loaded. It ships with no scenarios: press Generate with Bedrock to author them from the rules, then run the rehearsal.`)
  })
  const generate = () => run('gen', async () => { const r = await api.generate(perRule === 0 ? 1 : perRule, perRule === 0 ? 8 : null); const s = await api.scenarios(); setScenarios(s.scenarios); setMsg(`Bedrock wrote ${r.generated} scenarios; ${r.total} ready.`) })
  const exportJson = () => {
    const blob = new Blob([JSON.stringify({ spec: draft, scenarios }, null, 2)], { type: 'application/json' })
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `${draft.name || 'agent'}.agentrehearsal.json`; a.click()
  }
  const importJson = (file: File) => run('import', async () => {
    const data = JSON.parse(await file.text())
    if (data.spec) { const next = await api.saveSpec(data.spec); onSpec(next) }
    if (Array.isArray(data.scenarios)) { await api.saveScenarios(data.scenarios); setScenarios(data.scenarios) }
    if (Array.isArray(data.tools) && !data.spec) { const r = await api.importTools(data.tools); set({ tools: [...draft.tools, ...r.tools] }) }
    setMsg('Imported.')
  })
  const connect = () => run('connect', async () => { const r = await api.connectMcp(mcpUrl.trim(), mcpAuth.trim()); setFetched(r.tools); setMsg(`Read ${r.count} tools from the server (schema only; nothing was called). Next: let Bedrock draft the world and the rules.`) })
  const draftWorld = () => run('draft', async () => {
    const r = await api.draftWorld(mcpName.trim(), mcpPurpose.trim(), fetched ?? [])
    onSpec(r.spec); setRulesWhy(r.rules_with_reasons); setScenarios([])
    setMsg(`${r.spec.name} is set up: ${r.spec.tools.length} tools with simulated responses, ${r.spec.rules.length} suggested rules, ${r.spec.constraints.length} constraints. Check the rules, then Generate with Bedrock and run the rehearsal.`)
  })
  const removeScenario = (id: string) => run('sc', async () => { const next = scenarios.filter((s) => s.id !== id); await api.saveScenarios(next); setScenarios(next) })
  const clearScenarios = (keep: (s: Scenario) => boolean, what: string) => run('sc', async () => {
    const next = scenarios.filter(keep)
    if (next.length === scenarios.length) return
    if (!confirm(`Remove ${scenarios.length - next.length} ${what}? Generate with Bedrock appends, so clear first if you want a small set.`)) return
    await api.saveScenarios(next); setScenarios(next); setMsg(`${next.length} scenarios left.`)
  })
  const addScenario = () => run('sc', async () => {
    const id = `C${String(scenarios.filter((s) => s.id.startsWith('C')).length + 1).padStart(2, '0')}`
    const sc: Scenario = { id, category: newSc.category ?? 'parameter_violation', title: newSc.title || 'Custom scenario', prompt: newSc.prompt ?? '', customer_id: '', attachment_id: newSc.attachment_id || null, session: newSc.session ?? {}, expected: newSc.expected ?? 'deny', must_call: newSc.expected === 'allow' ? newSc.must_call || null : null, runs: 1, source: 'seed', rationale: newSc.rationale ?? 'Custom scenario' }
    const next = [...scenarios, sc]; await api.saveScenarios(next); setScenarios(next); setShowAdd(false); setNewSc({ category: 'parameter_violation', expected: 'deny', prompt: '', title: '' })
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel px-4 py-2.5">
        <span className="text-sm">{dirty ? <span className="text-warn">Unsaved changes</span> : <span className="text-muted">All changes saved</span>}</span>
        <span className="ml-auto" />
        <select value="" onChange={(e) => e.target.value && loadExample(e.target.value)} disabled={!!busy} className="rounded-md border border-line bg-panel px-3 py-2 text-sm font-semibold text-text hover:bg-panel-2" title="Replaces the current agent and scenarios">
          <option value="">Start from an example…</option>
          {examples.map((x) => <option key={x.id} value={x.id} title={x.blurb}>{x.name} · {x.scenarios ? `${x.scenarios} seed scenarios` : 'no seeds, Bedrock authors them'}</option>)}
        </select>
        <Button kind="ghost" onClick={() => setShowConnect(!showConnect)}>{showConnect ? 'Hide' : 'Connect MCP server'}</Button>
        <label className="inline-flex cursor-pointer items-center rounded-md border border-line px-3.5 py-2 text-sm font-semibold hover:bg-panel-2">Import JSON<input type="file" accept="application/json" className="hidden" onChange={(e) => e.target.files?.[0] && importJson(e.target.files[0])} /></label>
        <Button kind="ghost" onClick={exportJson}>Export JSON</Button>
        <Button onClick={save} disabled={!!busy || !dirty}>{busy === 'save' ? 'Saving…' : 'Save agent'}</Button>
      </div>
      {showConnect && (
        <div className="rounded-lg border border-accent/30 bg-accent/5 p-4">
          <div className="text-sm font-semibold">Connect your agent's MCP server</div>
          <p className="mt-1 text-xs text-muted">We read its tool list (initialize + tools/list) and nothing else: the real tools are never called during a rehearsal. Bedrock then drafts a simulated world for them (canned responses, one poisoned document, session facts) and suggests rules for you to confirm.</p>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            <input value={mcpUrl} onChange={(e) => setMcpUrl(e.target.value)} placeholder="https://your-server.example.com/mcp" className={`${input} font-mono text-xs md:col-span-2`} />
            <input value={mcpAuth} onChange={(e) => setMcpAuth(e.target.value)} placeholder="Authorization header value (optional), e.g. Bearer …" className={`${input} font-mono text-xs md:col-span-2`} />
            <input value={mcpName} onChange={(e) => setMcpName(e.target.value)} placeholder="Agent name, e.g. BillingBot" className={input} />
            <input value={mcpPurpose} onChange={(e) => setMcpPurpose(e.target.value)} placeholder="What the agent is for, one sentence" className={input} />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button kind="ghost" onClick={connect} disabled={!!busy || !mcpUrl.trim()}>{busy === 'connect' ? 'Reading tools…' : '1 · Read tools'}</Button>
            <Button onClick={draftWorld} disabled={!!busy || !fetched}>{busy === 'draft' ? 'Drafting with Bedrock…' : `2 · Draft world & rules${fetched ? ` for ${fetched.length} tools` : ''}`}</Button>
            {fetched && <span className="font-mono text-xs text-muted">{fetched.map((t) => t.name).join(', ')}</span>}
          </div>
          {rulesWhy.length > 0 && (
            <div className="mt-3 rounded border border-line bg-panel-2 p-3 text-xs">
              <div className="font-semibold text-text">Suggested rules and why (edit them in the Rules box below)</div>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted">{rulesWhy.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </div>
          )}
        </div>
      )}
      {msg && <div className="rounded border border-pass/40 bg-pass/10 p-2.5 text-sm text-pass">{msg}</div>}
      {err && <div className="rounded border border-fail/40 bg-fail/10 p-2.5 text-sm text-fail">{err}</div>}

      <div className="grid gap-4 lg:grid-cols-5">
        <Card title="Agent under test" className="lg:col-span-2">
          <div className={label}>Name</div>
          <input value={draft.name} onChange={(e) => set({ name: e.target.value })} className={`${input} text-lg font-semibold`} />
          <div className={`mt-3 ${label}`}>Purpose</div>
          <textarea value={draft.purpose} onChange={(e) => set({ purpose: e.target.value })} rows={3} className={input} />
          <div className={`mt-3 ${label}`}>Model the agent runs on (Bedrock)</div>
          <div className="mt-1 flex gap-1">
            <select value={models.some((m) => m.id === draft.model_id) ? draft.model_id : (draft.model_id ? '__custom' : '')} onChange={(e) => { if (e.target.value !== '__custom') setModel(e.target.value) }} className={input}>
              <option value="">Server default</option>
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}{m.note ? ` · ${m.note}` : ''}</option>)}
              <option value="__custom">Custom id…</option>
            </select>
          </div>
          <input value={draft.model_id} onChange={(e) => set({ model_id: e.target.value.trim() })} onBlur={(e) => setModel(e.target.value.trim())} placeholder="or paste a model / inference profile id" className={`${input} mt-1 font-mono text-xs`} />
          <div className="mt-1 text-[11px] text-muted">Applies immediately to the next run; no need to press Save.</div>
          <div className={`mt-3 ${label}`}>System prompt (the agent's own instructions)</div>
          <textarea value={draft.system_prompt} onChange={(e) => set({ system_prompt: e.target.value })} rows={8} className={`${input} font-mono text-xs`} />
          <details className="mt-3" open>
          <summary className={`cursor-pointer ${label}`}>Session facts (policy can compare against these as session.&lt;key&gt;)</summary>
          <ul className="mt-1 space-y-1">
            {Object.entries(draft.session).map(([k, v]) => (
              <li key={k} className="flex gap-1">
                <input value={k} readOnly className={`${input} w-40 font-mono text-xs`} />
                <input value={v} onChange={(e) => set({ session: { ...draft.session, [k]: e.target.value } })} className={`${input} font-mono text-xs`} />
                <button onClick={() => { const s = { ...draft.session }; delete s[k]; set({ session: s }) }} className="text-xs text-muted hover:text-fail">✕</button>
              </li>
            ))}
          </ul>
          <button onClick={() => { const k = prompt('Session key (e.g. customer_email)'); if (k) set({ session: { ...draft.session, [k]: '' } }) }} className="mt-1 text-xs text-accent">+ add session fact</button>
          <div className={`mt-3 ${label}`}>Context line shown to the agent ({'{key}'} placeholders)</div>
          <input value={draft.session_header} onChange={(e) => set({ session_header: e.target.value })} className={`${input} font-mono text-xs`} />
          </details>

          <details className="mt-4 rounded border border-line bg-panel-2 p-3" open={draft.target.kind !== 'simulated'}>
            <summary className={`cursor-pointer ${label}`}>Where does the agent run? <span className="normal-case tracking-normal text-text">· {draft.target.kind === 'simulated' ? 'built by AgentRehearsal' : draft.target.kind === 'http' ? 'my own agent, HTTP' : 'my own agent, AgentCore Runtime'}</span></summary>
            <select value={draft.target.kind} onChange={(e) => set({ target: { ...draft.target, kind: e.target.value as AgentSpec['target']['kind'] } })} className={`${input} mt-1`}>
              <option value="simulated">AgentRehearsal builds it (system prompt + model above + simulated tools)</option>
              <option value="http">My own agent behind an HTTP endpoint</option>
              <option value="agentcore_runtime">My own agent on Bedrock AgentCore Runtime</option>
              <option value="mcp_client">My own agent connects here as an MCP client (goose, Cline, Claude Code, OpenHands…)</option>
            </select>
            {draft.target.kind === 'mcp_client' && (<>
              <p className="mt-2 text-xs text-muted">Nothing to adapt: the agent stays exactly as published and gets one extra MCP server, this one. AgentRehearsal serves the tools on this page, records every call, and applies the policy. Optionally put your real MCP server behind it.</p>
              <div className={`mt-2 ${label}`}>Real MCP server behind the proxy (optional)</div>
              <input value={draft.target.upstream_url ?? ''} onChange={(e) => set({ target: { ...draft.target, upstream_url: e.target.value.trim() } })} placeholder="https://your-server.example.com/mcp" className={`${input} font-mono text-xs`} />
              <input value={draft.target.upstream_auth ?? ''} onChange={(e) => set({ target: { ...draft.target, upstream_auth: e.target.value } })} placeholder="Authorization header for it (optional)" className={`${input} mt-1 font-mono text-xs`} />
              <label className="mt-2 flex items-center gap-2 text-xs text-muted"><input type="checkbox" checked={!!draft.target.forward_calls} onChange={(e) => set({ target: { ...draft.target, forward_calls: e.target.checked } })} /> Forward allowed calls to it for real (off = answer with the simulated responses; keep off unless the server is a sandbox)</label>
            </>)}
            {draft.target.kind === 'http' && (<>
              <div className={`mt-2 ${label}`}>Endpoint (POST, JSON)</div>
              <input value={draft.target.url} onChange={(e) => set({ target: { ...draft.target, url: e.target.value.trim() } })} placeholder="http://127.0.0.1:9000/invoke" className={`${input} font-mono text-xs`} />
              <div className="mt-1 grid grid-cols-2 gap-1">
                <input value={draft.target.prompt_field} onChange={(e) => set({ target: { ...draft.target, prompt_field: e.target.value.trim() } })} placeholder="prompt field (prompt)" className={`${input} font-mono text-xs`} />
                <input value={draft.target.response_field} onChange={(e) => set({ target: { ...draft.target, response_field: e.target.value.trim() } })} placeholder="reply field (auto)" className={`${input} font-mono text-xs`} />
              </div>
              <input value={draft.target.auth_header} onChange={(e) => set({ target: { ...draft.target, auth_header: e.target.value } })} placeholder="Authorization header value (optional)" className={`${input} mt-1 font-mono text-xs`} />
            </>)}
            {draft.target.kind === 'agentcore_runtime' && (<>
              <div className={`mt-2 ${label}`}>Agent Runtime ARN</div>
              <input value={draft.target.agent_arn} onChange={(e) => set({ target: { ...draft.target, agent_arn: e.target.value.trim() } })} placeholder="arn:aws:bedrock-agentcore:us-east-1:…:runtime/…" className={`${input} font-mono text-xs`} />
            </>)}
            {draft.target.kind !== 'simulated' && (
              <div className="mt-3 rounded border border-line bg-ink p-2 text-xs">
                <div className="font-semibold text-text">Give your agent these tools</div>
                <p className="mt-1 text-muted">Connect your agent's tools to this MCP endpoint. AgentRehearsal serves the tools defined on this page and judges every call against the policy. Keep the URL private.</p>
                <div className="mt-1 flex items-center gap-1">
                  <code className="flex-1 truncate rounded bg-panel px-1.5 py-1">{mcp?.url ?? '…'}</code>
                  <button onClick={() => mcp && navigator.clipboard?.writeText(mcp.url)} className="rounded border border-line px-2 py-1 text-muted hover:text-text">copy</button>
                  <button onClick={() => api.rotateMcp().then(setMcp)} className="rounded border border-line px-2 py-1 text-muted hover:text-fail" title="Invalidate the current URL">rotate</button>
                </div>
                <p className="mt-1 text-muted">{draft.target.kind === 'mcp_client' ? 'Then go to Rehearse → Live rehearsal: start a scenario, paste its prompt into your agent, stop.' : <>Example agent: <code>backend/examples/external_agent.py</code> (Strands + this MCP URL, POST /invoke).</>}</p>
              </div>
            )}
          </details>
        </Card>

        <Card title={`${draft.tools.length} tools`} className="lg:col-span-3" right={<button onClick={() => set({ tools: [...draft.tools, { name: 'new_tool', description: '', params: [], destructive: false, responses: [] }] })} className="text-xs text-accent">+ add tool</button>}>
          <ul className="space-y-2">
            {draft.tools.map((t, i) => <ToolEditor key={i} tool={t} onChange={(nt) => set({ tools: draft.tools.map((x, k) => k === i ? nt : x) })} onRemove={() => set({ tools: draft.tools.filter((_, k) => k !== i) })} />)}
          </ul>
          <p className="mt-3 text-xs text-muted">Tools are simulated: the agent sees real names, parameters and responses, but nothing outside this page is called. Import an MCP tool list via Import JSON ({'{"tools": [...]}'}).</p>
        </Card>

      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card title={`${draft.constraints.length} operating constraints`} className="lg:col-span-2" right={<Button kind="ghost" onClick={reparse} disabled={!!busy}>{busy === 'parse' ? 'Parsing…' : 'Parse rules with Bedrock'}</Button>}>
          <div className={label}>Rules, in plain English (one per line)</div>
          <textarea value={rules} onChange={(e) => setRules(e.target.value)} rows={5} className={`${input} mt-1`} />
          <div className={`mt-3 ${label}`}>Parsed constraints (what gets enforced)</div>
          <ul className="mt-1 space-y-1.5">
            {draft.constraints.map((c, i) => {
              const n = notes.find((x) => x.id === c.id)
              return (
                <li key={c.id} className="text-sm">
                  <div className="flex items-start gap-2">
                    <code className="shrink-0 rounded bg-panel-2 px-1.5 py-0.5 text-xs text-accent">{c.tool}</code>
                    <span className="text-text">{KIND_TEXT[c.kind]?.(c) ?? c.kind}</span>
                    {n && n.confidence < 0.8 && <span className="rounded bg-warn/15 px-1 py-0.5 font-mono text-[10px] text-warn" title="parser confidence">{Math.round(n.confidence * 100)}%</span>}
                    <span className="ml-auto shrink-0 font-mono text-[10px] text-muted">{c.id}</span>
                    <button onClick={() => set({ constraints: draft.constraints.filter((_, k) => k !== i) })} className="shrink-0 text-xs text-muted hover:text-fail">✕</button>
                  </div>
                  {c.rule && <div className="ml-1 text-[11px] text-muted">from “{c.rule}”</div>}
                  {n?.ambiguity && <div className="ml-1 text-[11px] text-warn">assumed: {n.ambiguity}</div>}
                </li>
              )
            })}
            {draft.constraints.length === 0 && <li className="text-xs text-warn">No constraints: every tool is denied by default. Parse the rules or load the example.</li>}
          </ul>
          {problems.length > 0 && (
            <div className="mt-3 rounded border border-warn/40 bg-warn/10 p-2.5 text-xs">
              <div className="font-semibold text-warn">Checked against the tools and session facts</div>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-text">{problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
            </div>
          )}
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-muted">Cedar policy these constraints compile to</summary>
            <pre className="mt-2 rounded bg-ink p-3 text-xs text-muted">{cedar}</pre>
          </details>
        </Card>

      <Card title={`${scenarios.length} scenarios · ${scenarios.filter((s) => s.source === 'seed').length} seed, ${scenarios.filter((s) => s.source !== 'seed').length} authored by Bedrock`} className="lg:col-span-3" right={
        <div className="flex items-center gap-2">
          <button onClick={() => setShowAdd(!showAdd)} className="text-xs text-accent">+ add scenario</button>
          {scenarios.length > 0 && <button onClick={() => clearScenarios(() => false, 'scenarios')} disabled={!!busy} className="text-xs text-muted hover:text-fail" title="Generate with Bedrock appends to the list; clear first for a small set">clear all</button>}
          <label className="flex items-center gap-1 text-xs text-muted" title="scenarios per rule that can be broken">per rule
            <select value={perRule} onChange={(e) => setPerRule(Number(e.target.value))} className="rounded border border-line bg-ink px-1.5 py-1 text-xs text-text"><option value={0}>demo (≈10 total)</option>{[1, 2, 3, 4, 6].map((n) => <option key={n} value={n}>{n}</option>)}</select>
          </label>
          <Button kind="ghost" onClick={generate} disabled={!!busy}>{busy === 'gen' ? 'Authoring with Bedrock…' : 'Generate with Bedrock'}</Button>
        </div>
      }>
        {showAdd && (
          <div className="mb-3 grid gap-2 rounded border border-line bg-panel-2 p-3 md:grid-cols-4">
            <input placeholder="Title" value={newSc.title ?? ''} onChange={(e) => setNewSc({ ...newSc, title: e.target.value })} className={`${input} md:col-span-2`} />
            <select value={newSc.category} onChange={(e) => setNewSc({ ...newSc, category: e.target.value })} className={input}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select>
            <select value={newSc.expected} onChange={(e) => setNewSc({ ...newSc, expected: e.target.value as 'allow' | 'deny' })} className={input}><option value="deny">expected: deny</option><option value="allow">expected: allow</option></select>
            <textarea placeholder="The customer's message, in their own words" value={newSc.prompt ?? ''} onChange={(e) => setNewSc({ ...newSc, prompt: e.target.value })} rows={2} className={`${input} md:col-span-4`} />
            {newSc.expected === 'allow' && <select value={newSc.must_call ?? ''} onChange={(e) => setNewSc({ ...newSc, must_call: e.target.value })} className={input}><option value="">must call…</option>{draft.tools.map((t) => <option key={t.name}>{t.name}</option>)}</select>}
            <input placeholder="attachment id (optional)" value={newSc.attachment_id ?? ''} onChange={(e) => setNewSc({ ...newSc, attachment_id: e.target.value })} className={input} />
            <div className="md:col-span-2"><JsonField value={newSc.session ?? {}} rows={1} placeholder='session overrides, e.g. {"customer_id": "c_1002"}' onChange={(v) => setNewSc({ ...newSc, session: (v as Record<string, string>) ?? {} })} /></div>
            <div className="md:col-span-4"><Button onClick={addScenario} disabled={!newSc.prompt}>Add scenario</Button></div>
          </div>
        )}
        {scenarios.length === 0 && !showAdd && (
          <div className="rounded border border-dashed border-line p-4 text-sm text-muted">
            <div className="font-semibold text-text">No scenarios yet</div>
            <p className="mt-1">Generate with Bedrock writes allowed, boundary and attack cases for every constraint above, in the voice of real users, using only the ids your simulated tools know. Add your own with + add scenario.</p>
            <div className="mt-3"><Button onClick={generate} disabled={!!busy || draft.constraints.length === 0}>{busy === 'gen' ? 'Authoring with Bedrock…' : 'Generate with Bedrock'}</Button></div>
          </div>
        )}
        <ul>{scenarios.map((s) => <ScenarioRow key={s.id} s={s} onRemove={() => removeScenario(s.id)} />)}</ul>
        {coverage && coverage.rows.length > 0 && (
          <details className="mt-3" open={coverage.rows.some((r) => r.gaps.length > 0)}>
            <summary className="cursor-pointer text-xs text-muted">Coverage: which rule each scenario aims at ({coverage.with_expected_call} of {coverage.scenarios} state an expected call){coverage.rows.some((r) => r.gaps.length) ? <span className="text-warn"> · gaps</span> : <span className="text-pass"> · no gaps</span>}</summary>
            <table className="mt-2 w-full text-[11px]">
              <thead className="text-left uppercase tracking-wider text-muted"><tr><th className="pb-1 pr-2">Rule</th>{coverage.categories.map((c) => <th key={c} className="pb-1 pr-1 font-normal normal-case">{CATEGORY_LABEL[c] ?? c}</th>)}</tr></thead>
              <tbody>
                {coverage.rows.map((r) => (
                  <tr key={r.id} className="border-t border-line">
                    <td className="py-1 pr-2 font-mono text-accent">{r.id}</td>
                    {coverage.categories.map((c) => <td key={c} className={`py-1 pr-1 font-mono ${r.counts[c] ? 'text-text' : r.gaps.includes(c) ? 'text-warn' : 'text-muted'}`}>{r.counts[c] || (r.gaps.includes(c) ? '·' : '')}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-1 text-[11px] text-muted">A dot is a gap: no scenario tests that rule with that tactic. Generate with Bedrock fills gaps; Escalate on the Rehearse tab finds what the agent resists.</p>
          </details>
        )}
      </Card>
      </div>
    </div>
  )
}
