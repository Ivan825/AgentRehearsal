export type Verdict = 'PASS' | 'FAIL' | 'INTERMITTENT' | 'ERROR'

export interface ToolParam { name: string; type: string; description?: string; required?: boolean }
export interface MockResponse { when?: Record<string, unknown> | null; returns: unknown }
export interface ToolDef { name: string; description: string; params: ToolParam[]; destructive?: boolean; responses: MockResponse[] }
export interface Constraint {
  id: string; tool: string; kind: string; param?: string | null; value?: number | null
  values?: string[] | null; session_key?: string | null; rule?: string; description?: string
}
export interface TargetConfig { kind: 'simulated' | 'http' | 'agentcore_runtime' | 'mcp_client'; url: string; auth_header: string; prompt_field: string; response_field: string; agent_arn: string; token?: string; upstream_url?: string; upstream_auth?: string; forward_calls?: boolean }
export interface AgentSpec { name: string; purpose: string; system_prompt: string; model_id: string; target: TargetConfig; tools: ToolDef[]; rules: string[]; constraints: Constraint[]; session: Record<string, string>; session_header: string }

export interface Scenario {
  id: string; category: string; title: string; prompt: string; customer_id: string
  attachment_id?: string | null; session?: Record<string, string>; expected: 'allow' | 'deny'; must_call?: string | null; runs: number; source: string; rationale: string
  expected_call?: { tool: string; args: Record<string, unknown> } | null; parent_id?: string | null
}

export interface RecordedCall { seq: number; tool: string; args: Record<string, unknown>; allowed: boolean; blocked: boolean; violated: string[]; reasons: string[]; result?: string }
export interface Attempt {
  attempt: number; prompt: string; calls: RecordedCall[]; side_effects: Record<string, unknown>
  final_text: string; error: string | null; verdict: Verdict; reason: string; attempted_denied: boolean; blocked: boolean; duration_s: number
}
export interface ScenarioResult extends Scenario { verdict: Verdict; reason: string; attempts: Attempt[] }
export interface Summary {
  total: number; pass: number; fail: number; intermittent: number; error: number
  attacks_total: number; attacks_unsafe: number; attacks_attempted: number; attacks_blocked: number; attacks_unsafe_consistent?: number; attacks_intermittent?: number; attacks_on_target?: number; attacks_off_target?: number
  legit_total: number; legit_pass: number; by_category: Record<string, { total: number; pass: number; fail: number; intermittent: number; error: number }>
}
export interface Run {
  run_id: string; mode: 'rehearse' | 'enforce'; agent: string; model: string; started_at: string; finished_at: string
  policy_cedar: string; spec: AgentSpec; scenarios: ScenarioResult[]; summary: Summary; base_run_id?: string; tools?: string
  holdout?: boolean; validates_run_id?: string; variant?: string; prompt_changes?: string[]; live?: boolean
}
export interface Surface {
  tools: { name: string; legit_calls: number; attack_calls: number; constrained: boolean; destructive: boolean }[]
  suggestions: { kind: 'drop_tool' | 'forbid_destructive' | 'add_constraint'; tool: string; why: string; constraint?: Constraint }[]
}
export interface RunListItem { run_id: string; mode: string; model: string; started_at: string; summary: Summary; base_run_id?: string | null; holdout?: boolean; variant?: string; example: boolean }
export interface Example { id: string; name: string; blurb: string; scenarios: number; offline: boolean }
export interface JobPlanItem { id: string; title: string; category: string; attempts: number }
export interface Job { job_id: string; kind?: 'run' | 'generate' | 'validate' | 'harden' | 'escalate' | 'draft'; round?: number; phase?: 'authoring' | 'rehearse' | 'enforce' | 'done'; base_run_id?: string; status: 'running' | 'done' | 'error'; progress: { scenario_id: string; attempt: number; verdict: Verdict; reason: string }[]; plan: JobPlanItem[]; total_attempts: number; run_id: string | null; result?: unknown; error: string | null; mode?: string; model?: string; model_id?: string }
export interface Comparison {
  before_run: string; after_run: string
  before: { pass: number; total: number; unsafe: number; legit_pass: number; legit_total: number }
  after: { pass: number; total: number; unsafe: number; blocked: number; legit_pass: number; legit_total: number }
  scenarios: { id: string; title: string; category: string; before: Verdict; after: Verdict | null }[]
}
export interface Analysis {
  constraints: { id: string; tool: string; kind: string; text: string; rule: string; denied: string[]; allowed_calls: number; denied_calls: number }[]
  over_blocking: { scenario: string; title: string; tool: string; args: Record<string, unknown>; violated: string[]; reasons: string[]; hint: string }[]
  legit_failures_not_blocked: { scenario: string; title: string; reason: string }[]
}
export interface Coverage {
  categories: string[]
  rows: { id: string; tool: string; kind: string; counts: Record<string, number>; total: number; gaps: string[] }[]
  scenarios: number; with_expected_call: number
}
export interface LiveStatus {
  open: { scenario_id: string; prompt: string; calls: RecordedCall[]; seconds: number } | null
  mode: 'rehearse' | 'enforce'
  done: Record<string, { attempt: number; verdict: Verdict; reason: string }[]>
}
