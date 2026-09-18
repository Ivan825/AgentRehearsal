import type { AgentSpec, Comparison, Job, Run, RunListItem, Scenario } from './types'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? ''

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, { headers: { 'content-type': 'application/json' }, ...init })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

export const api = {
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
