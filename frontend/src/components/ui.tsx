import type { ReactNode } from 'react'
import type { Verdict } from '../types'

export const VERDICT_STYLE: Record<Verdict, string> = {
  PASS: 'bg-pass/15 text-pass border-pass/40',
  FAIL: 'bg-fail/15 text-fail border-fail/40',
  INTERMITTENT: 'bg-warn/15 text-warn border-warn/40',
  ERROR: 'bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/40',
}

export function VerdictBadge({ v, size = 'sm' }: { v: Verdict | string; size?: 'sm' | 'lg' }) {
  const cls = VERDICT_STYLE[v as Verdict] ?? 'bg-panel-2 text-muted border-line'
  return <span className={`inline-flex items-center rounded border font-mono font-semibold ${size === 'lg' ? 'px-3 py-1 text-sm' : 'px-2 py-0.5 text-xs'} ${cls}`}>{v}</span>
}

export const CATEGORY_LABEL: Record<string, string> = {
  allowed: 'Allowed',
  boundary: 'Boundary',
  scope_violation: 'Scope violation',
  parameter_violation: 'Parameter violation',
  direct_injection: 'Direct injection',
  indirect_injection: 'Indirect injection',
  destructive_action: 'Destructive action',
}

export function Category({ c }: { c: string }) {
  const attack = !['allowed', 'boundary'].includes(c)
  return <span className={`text-xs font-medium ${attack ? 'text-orange-300' : 'text-sky-300'}`}>{CATEGORY_LABEL[c] ?? c}</span>
}

export function Card({ title, children, right, className = '' }: { title?: ReactNode; children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-line bg-panel ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <h3 className="text-sm font-semibold tracking-wide text-text">{title}</h3>
          <div>{right}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

export function Stat({ label, value, tone = 'default', sub }: { label: string; value: ReactNode; tone?: 'default' | 'pass' | 'fail' | 'warn'; sub?: string }) {
  const color = { default: 'text-text', pass: 'text-pass', fail: 'text-fail', warn: 'text-warn' }[tone]
  return (
    <div className="rounded-lg border border-line bg-panel-2 px-4 py-3">
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-semibold ${color}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  )
}

export function Button({ children, onClick, kind = 'primary', disabled, title }: { children: ReactNode; onClick?: () => void; kind?: 'primary' | 'ghost' | 'danger'; disabled?: boolean; title?: string }) {
  const base = 'inline-flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50'
  const k = {
    primary: 'bg-accent text-ink hover:bg-sky-300',
    ghost: 'border border-line bg-transparent text-text hover:bg-panel-2',
    danger: 'bg-fail text-white hover:bg-red-400',
  }[kind]
  return <button className={`${base} ${k}`} onClick={onClick} disabled={disabled} title={title}>{children}</button>
}

export function fmtArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => {
      const s = typeof v === 'string' ? (v.length > 48 ? `"${v.slice(0, 45)}…"` : `"${v}"`) : String(v)
      return `${k}=${s}`
    })
    .join(', ')
}
