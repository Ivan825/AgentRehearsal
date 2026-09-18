export type Verdict = 'PASS' | 'FAIL' | 'INTERMITTENT' | 'ERROR'

export interface ToolParam { name: string; type: string; description?: string; required?: boolean }
export interface ToolDef { name: string; description: string; params: ToolParam[]; destructive?: boolean }
export interface Constraint {
  id: string; tool: string; kind: string; param?: string | null; value?: number | null
  values?: string[] | null; session_key?: string | null; rule?: string; description?: string
}
export interface AgentSpec { name: string; purpose: string; system_prompt: string; tools: ToolDef[]; rules: string[]; constraints: Constraint[] }

export interface Scenario {
  id: string; category: string; title: string; prompt: string; customer_id: string
  attachment_id?: string | null; expected: 'allow' | 'deny'; must_call?: string | null; runs: number; source: string; rationale: string
}

export interface RecordedCall { seq: number; tool: string; args: Record<string, unknown>; allowed: boolean; blocked: boolean; violated: string[]; reasons: string[]; result?: string }
export interface Attempt {
  attempt: number; prompt: string; calls: RecordedCall[]; side_effects: Record<string, unknown>
  final_text: string; error: string | null; verdict: Verdict; reason: string; attempted_denied: boolean; blocked: boolean; duration_s: number
}
export interface ScenarioResult extends Scenario { verdict: Verdict; reason: string; attempts: Attempt[] }
export interface Summary {
  total: number; pass: number; fail: number; intermittent: number; error: number
  attacks_total: number; attacks_unsafe: number; attacks_attempted: number; attacks_blocked: number
  legit_total: number; legit_pass: number; by_category: Record<string, { total: number; pass: number; fail: number; intermittent: number; error: number }>
}
export interface Run {
  run_id: string; mode: 'rehearse' | 'enforce'; agent: string; model: string; started_at: string; finished_at: string
  policy_cedar: string; spec: AgentSpec; scenarios: ScenarioResult[]; summary: Summary; base_run_id?: string; tools?: string
}
export interface RunListItem { run_id: string; mode: string; model: string; started_at: string; summary: Summary; base_run_id?: string | null; example: boolean }
export interface JobPlanItem { id: string; title: string; category: string; attempts: number }
export interface Job { job_id: string; status: 'running' | 'done' | 'error'; progress: { scenario_id: string; attempt: number; verdict: Verdict; reason: string }[]; plan: JobPlanItem[]; total_attempts: number; run_id: string | null; error: string | null; mode: string; model?: string }
export interface Comparison {
  before_run: string; after_run: string
  before: { pass: number; total: number; unsafe: number; legit_pass: number; legit_total: number }
  after: { pass: number; total: number; unsafe: number; blocked: number; legit_pass: number; legit_total: number }
  scenarios: { id: string; title: string; category: string; before: Verdict; after: Verdict | null }[]
}
