import type { AgentSpec, Analysis, Comparison, Coverage, Example, Job, LiveStatus, RecordedCall, Run, RunListItem, Scenario, Summary, Surface, ToolDef, Verdict } from './types'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? ''

export const session = {
  get token(): string | null { try { return localStorage.getItem('ar-token') } catch { return null } },
  set(token: string, user: SessionUser) { try { localStorage.setItem('ar-token', token); localStorage.setItem('ar-user', JSON.stringify(user)) } catch { /* ignore */ } },
  clear() { try { localStorage.removeItem('ar-token'); localStorage.removeItem('ar-user') } catch { /* ignore */ } },
  get user(): SessionUser | null { try { const u = localStorage.getItem('ar-user'); return u ? JSON.parse(u) : null } catch { return null } },
}
export interface SessionUser { id: string; email: string; name: string }

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'content-type': 'application/json' }
  const t = session.token
  if (t) headers['authorization'] = `Bearer ${t}`
  const r = await fetch(BASE + path, { ...init, headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) } })
  if (r.status === 401 && !path.startsWith('/api/auth/')) {
    session.clear()
    if (!location.pathname.startsWith('/signin')) location.assign('/signin?next=' + encodeURIComponent(location.pathname))
  }
  if (!r.ok) {
    // read the body once: a proxy/backend error page is plain text, not JSON
    const text = await r.text()
    let msg = `${r.status}`
    try { const b = JSON.parse(text); msg = typeof b.detail === 'string' ? b.detail : JSON.stringify(b.detail ?? b) } catch { msg = `${r.status} ${text.slice(0, 300)}`.trim() }
    if (r.status >= 502 || r.status === 500 && !text) msg = 'Backend is not reachable on port 8000: start it with `uvicorn agentrehearsal.api:app --port 8000` in backend/ and reload.'
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}

export const api = {
  authConfig: () => j<{ enabled: boolean }>('/api/auth/config'),
  signup: (email: string, password: string, name: string) => j<{ token: string; user: SessionUser }>('/api/auth/signup', { method: 'POST', body: JSON.stringify({ email, password, name }) }),
  login: (email: string, password: string) => j<{ token: string; user: SessionUser }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  contact: (name: string, email: string, message: string) => j<{ ok: boolean }>('/api/contact', { method: 'POST', body: JSON.stringify({ name, email, message }) }),
  spec: () => j<AgentSpec>('/api/spec'),
  saveSpec: (spec: AgentSpec) => j<AgentSpec>('/api/spec', { method: 'PUT', body: JSON.stringify(spec) }),
  examples: () => j<{ examples: Example[] }>('/api/examples'),
  exampleSpec: (example = 'supportbot') => j<AgentSpec>(`/api/spec/example?example=${example}`),
  resetExample: (example = 'supportbot') => j<{ spec: AgentSpec; scenarios: number; example: string }>('/api/spec/reset', { method: 'POST', body: JSON.stringify({ example }) }),
  connectMcp: (url: string, auth_header: string) => j<{ tools: ToolDef[]; count: number }>('/api/tools/connect', { method: 'POST', body: JSON.stringify({ url, auth_header }) }),
  draftWorld: async (name: string, purpose: string, tools: ToolDef[]) => {
    const job = await j<Job>('/api/tools/draft', { method: 'POST', body: JSON.stringify({ name, purpose, tools, apply: true }) })
    const done = await waitJob(job.job_id)
    return done.result as { spec: AgentSpec; rules_with_reasons: string[] }
  },
  importTools: (tools: unknown[]) => j<{ tools: AgentSpec['tools'] }>('/api/tools/import', { method: 'POST', body: JSON.stringify({ tools }) }),
  saveScenarios: (scenarios: Scenario[]) => j<{ count: number }>('/api/scenarios', { method: 'PUT', body: JSON.stringify({ scenarios }) }),
  parseRules: (rules: string[]) => j<{ constraints: AgentSpec['constraints']; notes: { id: string; confidence: number; ambiguity: string }[]; problems: string[] }>('/api/rules/parse', { method: 'POST', body: JSON.stringify({ rules }) }),
  validateConstraints: () => j<{ problems: string[] }>('/api/constraints/validate'),
  coverage: () => j<Coverage>('/api/scenarios/coverage'),
  escalate: (body: { base_run_id: string; rounds?: number; model: 'bedrock' | 'scripted'; model_id?: string | null; attack_runs?: number }) => j<Job>('/api/escalate', { method: 'POST', body: JSON.stringify(body) }),
  policy: () => j<{ cedar: string; problems: string[] }>('/api/policy'),
  validatePolicy: (cedar: string) => j<{ problems: string[] }>('/api/policy/validate', { method: 'POST', body: JSON.stringify({ cedar }) }),
  scenarios: () => j<{ scenarios: Scenario[] }>('/api/scenarios'),
  generate: async (per_constraint = 4, max_rules: number | null = null) => {
    // authoring runs as a background job so hosted proxies (30 s limit) never cut it off
    const job = await j<Job>('/api/scenarios/generate', { method: 'POST', body: JSON.stringify({ per_constraint, append: true, max_rules }) })
    const done = await waitJob(job.job_id)
    return done.result as { generated: number; total: number }
  },
  startRun: (body: { mode: 'rehearse' | 'enforce'; model: 'bedrock' | 'scripted'; model_id?: string | null; attack_runs?: number; workers?: number; base_run_id?: string; cedar?: string }) =>
    j<Job>('/api/runs', { method: 'POST', body: JSON.stringify(body) }),
  job: (id: string) => j<Job>(`/api/jobs/${id}`),
  runningJobs: () => j<{ jobs: Job[] }>('/api/jobs'),
  models: () => j<{ models: { id: string; label: string; note?: string; provider?: string; available?: boolean }[]; default: string; live: boolean; providers?: { id: string; label: string; available: boolean; env: string | null }[] }>('/api/models'),
  workspaceMcp: () => j<{ token: string; url: string; tools: string[]; upstream?: string; forwarding?: boolean; mcp_json?: unknown }>('/api/workspace/mcp'),
  liveStart: (scenario_id: string, mode: 'rehearse' | 'enforce', cedar?: string) => j<{ scenario_id: string; prompt: string; mode: string }>('/api/live/start', { method: 'POST', body: JSON.stringify({ scenario_id, mode, cedar }) }),
  liveStatus: () => j<LiveStatus>('/api/live'),
  liveStop: (final_text: string) => j<{ scenario_id: string; verdict: Verdict; reason: string; calls: RecordedCall[]; attempts: number }>('/api/live/stop', { method: 'POST', body: JSON.stringify({ final_text }) }),
  liveFinish: (base_run_id?: string | null) => j<{ run_id: string; summary: Summary }>('/api/live/finish', { method: 'POST', body: JSON.stringify({ base_run_id }) }),
  liveReset: () => j<{ ok: boolean }>('/api/live/reset', { method: 'POST' }),
  holdout: async (per_constraint = 2) => { const job = await j<Job>('/api/scenarios/holdout', { method: 'POST', body: JSON.stringify({ per_constraint }) }); return (await waitJob(job.job_id)).result as { generated: number; ids: string[] } },
  rotateMcp: () => j<{ token: string; url: string; tools: string[] }>('/api/workspace/mcp/rotate', { method: 'POST' }),
  runs: () => j<{ runs: RunListItem[] }>('/api/runs'),
  run: (id: string) => j<Run>(`/api/runs/${id}`),
  reportUrl: (id: string) => `${BASE}/api/runs/${id}/report.md?token=${encodeURIComponent(session.token ?? '')}`,
  fixpackUrl: (id: string, after?: string | null, hardened?: string | null) => `${BASE}/api/runs/${id}/fixpack.md?token=${encodeURIComponent(session.token ?? '')}${after ? `&after=${after}` : ''}${hardened ? `&hardened=${hardened}` : ''}`,
  harden: (body: { base_run_id: string; model: 'bedrock' | 'scripted'; model_id?: string | null; attack_runs?: number }) => j<Job>('/api/fix/harden', { method: 'POST', body: JSON.stringify(body) }),
  applyPrompt: (system_prompt: string) => j<AgentSpec>('/api/fix/apply-prompt', { method: 'POST', body: JSON.stringify({ system_prompt }) }),
  surface: (id: string) => j<Surface>(`/api/runs/${id}/surface`),
  analysis: (id: string) => j<Analysis>(`/api/runs/${id}/analysis`),
  compare: (before: string, after: string) => j<Comparison>(`/api/compare?before=${before}&after=${after}`),
  validate: (body: { base_run_id: string; per_constraint?: number; model: 'bedrock' | 'scripted'; model_id?: string | null; attack_runs?: number }) => j<Job>('/api/validate', { method: 'POST', body: JSON.stringify(body) }),
}

/** Poll a background job until it finishes; throws with the job's error on failure. */
export async function waitJob(jobId: string, intervalMs = 1500): Promise<Job> {
  let misses = 0
  for (;;) {
    let cur: Job
    try { cur = await api.job(jobId); misses = 0 } catch (e) {
      // a dropped fetch or proxy hiccup is not the end of the job; only give up when the job is really gone
      if (/job not found|no such job/i.test(String(e)) || ++misses >= 6) throw e
      await new Promise(r => setTimeout(r, intervalMs)); continue
    }
    if (cur.status === 'done') return cur
    if (cur.status === 'error') throw new Error(cur.error ?? 'job failed')
    await new Promise(r => setTimeout(r, intervalMs))
  }
}
