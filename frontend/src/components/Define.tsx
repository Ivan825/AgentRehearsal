import { useEffect, useState } from 'react'
import type { AgentSpec, Constraint, MockResponse, Scenario, ToolDef } from '../types'
import { api } from '../api'
import { Button, Card, Category } from './ui'

const KIND_TEXT: Record<string, (c: Constraint) => string> = {
  allow: () => 'always allowed',
  forbid: () => 'never allowed',
  param_max: (c) => `${c.param} ≤ ${c.value}`,
  param_min: (c) => `${c.param} ≥ ${c.value}`,
  param_in: (c) => `${c.param} ∈ {${(c.values ?? []).join(', ')}}`,
  param_equals_session: (c) => `${c.param} must equal session.${c.session_key}`,
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
      <span className="shrink-0 font-mono text-[10px] text-muted">{s.expected}{s.must_call ? ` · ${s.must_call}` : ''}{s.source === 'generated' ? ' · gen' : ''}</span>
      <button onClick={onRemove} className="shrink-0 text-xs text-muted hover:text-fail">✕</button>
    </li>
  )
}

export function Define({ spec, onSpec, cedar }: { spec: AgentSpec; onSpec: (s: AgentSpec) => void; cedar: string }) {
  const [models, setModels] = useState<{ id: string; label: string; note?: string }[]>([])
  const [mcp, setMcp] = useState<{ url: string; token: string } | null>(null)
  useEffect(() => { api.models().then((m) => setModels(m.models)).catch(() => {}); api.workspaceMcp().then(setMcp).catch(() => {}) }, [])
  const [draft, setDraft] = useState<AgentSpec>(spec)
  const [rules, setRules] = useState(spec.rules.join('\n'))
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [newSc, setNewSc] = useState<Partial<Scenario>>({ category: 'parameter_violation', expected: 'deny', prompt: '', title: '' })
  const dirty = JSON.stringify(draft) !== JSON.stringify(spec) || rules !== spec.rules.join('\n')

  useEffect(() => { setDraft(spec); setRules(spec.rules.join('\n')) }, [spec])
  useEffect(() => { api.scenarios().then((r) => setScenarios(r.scenarios)).catch(() => {}) }, [])

  const set = (patch: Partial<AgentSpec>) => setDraft({ ...draft, ...patch })
  const run = async (name: string, fn: () => Promise<void>) => { setBusy(name); setErr(null); setMsg(null); try { await fn() } catch (e) { setErr(String(e)) } finally { setBusy(null) } }

  const save = () => run('save', async () => {
    const lines = rules.split('\n').map((s) => s.trim()).filter(Boolean)
    const next = await api.saveSpec({ ...draft, rules: lines })
    onSpec(next); setMsg('Saved. The Cedar policy has been regenerated from the constraints.')
  })
  const reparse = () => run('parse', async () => {
    const lines = rules.split('\n').map((s) => s.trim()).filter(Boolean)
    const saved = await api.saveSpec({ ...draft, rules: lines })
    const { constraints } = await api.parseRules(lines)
    const next = await api.saveSpec({ ...saved, constraints })
    onSpec(next); setMsg(`Bedrock parsed ${constraints.length} constraints. Check them below, then save.`)
  })
  const loadExample = () => run('example', async () => { const r = await api.resetExample(); onSpec(r.spec); const s = await api.scenarios(); setScenarios(s.scenarios); setMsg('SupportBot example loaded with its 13 seed scenarios.') })
  const generate = () => run('gen', async () => { const r = await api.generate(4); const s = await api.scenarios(); setScenarios(s.scenarios); setMsg(`Bedrock wrote ${r.generated} scenarios; ${r.total} ready.`) })
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
  const removeScenario = (id: string) => run('sc', async () => { const next = scenarios.filter((s) => s.id !== id); await api.saveScenarios(next); setScenarios(next) })
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
        <Button kind="ghost" onClick={loadExample} disabled={!!busy}>Load SupportBot example</Button>
        <label className="inline-flex cursor-pointer items-center rounded-md border border-line px-3.5 py-2 text-sm font-semibold hover:bg-panel-2">Import JSON<input type="file" accept="application/json" className="hidden" onChange={(e) => e.target.files?.[0] && importJson(e.target.files[0])} /></label>
        <Button kind="ghost" onClick={exportJson}>Export JSON</Button>
        <Button onClick={save} disabled={!!busy || !dirty}>{busy === 'save' ? 'Saving…' : 'Save agent'}</Button>
      </div>
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
            <select value={models.some((m) => m.id === draft.model_id) ? draft.model_id : (draft.model_id ? '__custom' : '')} onChange={(e) => { if (e.target.value !== '__custom') set({ model_id: e.target.value }) }} className={input}>
              <option value="">Server default</option>
              {models.map((m) => <option key={m.id} value={m.id}>{m.label}{m.note ? ` · ${m.note}` : ''}</option>)}
              <option value="__custom">Custom id…</option>
            </select>
          </div>
          <input value={draft.model_id} onChange={(e) => set({ model_id: e.target.value.trim() })} placeholder="or paste a model / inference profile id" className={`${input} mt-1 font-mono text-xs`} />
          <div className={`mt-3 ${label}`}>System prompt (the agent's own instructions)</div>
          <textarea value={draft.system_prompt} onChange={(e) => set({ system_prompt: e.target.value })} rows={8} className={`${input} font-mono text-xs`} />
          <div className={`mt-3 ${label}`}>Session facts (policy can compare against these as session.&lt;key&gt;)</div>
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

          <div className="mt-4 rounded border border-line bg-panel-2 p-3">
            <div className={label}>Where does the agent run?</div>
            <select value={draft.target.kind} onChange={(e) => set({ target: { ...draft.target, kind: e.target.value as AgentSpec['target']['kind'] } })} className={`${input} mt-1`}>
              <option value="simulated">AgentRehearsal builds it (system prompt + model above + simulated tools)</option>
              <option value="http">My own agent behind an HTTP endpoint</option>
              <option value="agentcore_runtime">My own agent on Bedrock AgentCore Runtime</option>
            </select>
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
                <p className="mt-1 text-muted">Example agent: <code>backend/examples/external_agent.py</code> (Strands + this MCP URL, POST /invoke).</p>
              </div>
            )}
          </div>
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
            {draft.constraints.map((c, i) => (
              <li key={c.id} className="flex items-start gap-2 text-sm">
                <code className="shrink-0 rounded bg-panel-2 px-1.5 py-0.5 text-xs text-accent">{c.tool}</code>
                <span className="text-text">{KIND_TEXT[c.kind]?.(c) ?? c.kind}</span>
                <span className="ml-auto shrink-0 font-mono text-[10px] text-muted">{c.id}</span>
                <button onClick={() => set({ constraints: draft.constraints.filter((_, k) => k !== i) })} className="shrink-0 text-xs text-muted hover:text-fail">✕</button>
              </li>
            ))}
            {draft.constraints.length === 0 && <li className="text-xs text-warn">No constraints: every tool is denied by default. Parse the rules or load the example.</li>}
          </ul>
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-muted">Cedar policy these constraints compile to</summary>
            <pre className="mt-2 rounded bg-ink p-3 text-xs text-muted">{cedar}</pre>
          </details>
        </Card>

      <Card title={`${scenarios.length} scenarios`} className="lg:col-span-3" right={
        <div className="flex items-center gap-2">
          <button onClick={() => setShowAdd(!showAdd)} className="text-xs text-accent">+ add scenario</button>
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
        <ul>{scenarios.map((s) => <ScenarioRow key={s.id} s={s} onRemove={() => removeScenario(s.id)} />)}</ul>
      </Card>
      </div>
    </div>
  )
}
