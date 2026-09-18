import type { AgentSpec, Comparison, Job, Run, RunListItem, Scenario } from './types'

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
    let msg = `${r.status}`
    try { const b = await r.json(); msg = b.detail ?? JSON.stringify(b) } catch { msg = `${r.status} ${await r.text()}` }
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
  exampleSpec: () => j<AgentSpec>('/api/spec/example'),
  resetExample: () => j<{ spec: AgentSpec; scenarios: number }>('/api/spec/reset', { method: 'POST' }),
  importTools: (tools: unknown[]) => j<{ tools: AgentSpec['tools'] }>('/api/tools/import', { method: 'POST', body: JSON.stringify({ tools }) }),
  saveScenarios: (scenarios: Scenario[]) => j<{ count: number }>('/api/scenarios', { method: 'PUT', body: JSON.stringify({ scenarios }) }),
  parseRules: (rules: string[]) => j<{ constraints: AgentSpec['constraints'] }>('/api/rules/parse', { method: 'POST', body: JSON.stringify({ rules }) }),
  policy: () => j<{ cedar: string; problems: string[] }>('/api/policy'),
  validatePolicy: (cedar: string) => j<{ problems: string[] }>('/api/policy/validate', { method: 'POST', body: JSON.stringify({ cedar }) }),
  scenarios: () => j<{ scenarios: Scenario[] }>('/api/scenarios'),
  generate: (per_constraint = 4) => j<{ generated: number; total: number }>('/api/scenarios/generate', { method: 'POST', body: JSON.stringify({ per_constraint, append: true }) }),
  startRun: (body: { mode: 'rehearse' | 'enforce'; model: 'bedrock' | 'scripted'; attack_runs?: number; workers?: number; base_run_id?: string; cedar?: string }) =>
    j<Job>('/api/runs', { method: 'POST', body: JSON.stringify(body) }),
  job: (id: string) => j<Job>(`/api/jobs/${id}`),
  runs: () => j<{ runs: RunListItem[] }>('/api/runs'),
  run: (id: string) => j<Run>(`/api/runs/${id}`),
  reportUrl: (id: string) => `${BASE}/api/runs/${id}/report.md`,
  compare: (before: string, after: string) => j<Comparison>(`/api/compare?before=${before}&after=${after}`),
}
