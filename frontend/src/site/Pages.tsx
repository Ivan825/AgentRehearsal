import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { GUIDES } from './guides'
import { Page } from './Shell'

export function ProductPage() {
  const rows = [
    ['Define', 'Agent, tools with simulated responses, session facts, rules → constraints', 'Bedrock (rule parsing)'],
    ['Rehearse', 'Generated scenarios against the real agent, policy in log-only mode, three attempts per attack', 'Strands + Bedrock'],
    ['Diagnose', 'Per-call trace: decision, arguments, policy verdict, what the tool returned, injected text highlighted', 'Cedar (cedarpy)'],
    ['Protect', 'Findings → least-privilege Cedar policy, editable and validated', 'Cedar'],
    ['Replay', 'Same scenarios with the policy enforced: attacks blocked, legitimate tasks checked', 'Strands hook or AgentCore Gateway'],
  ]
  return (
    <Page wide>
      <h1 className="text-4xl font-bold tracking-tight">How AgentRehearsal works</h1>
      <p className="mt-3 max-w-2xl text-muted">A test suite for what an agent does, not what it says. Verdicts are computed from recorded tool calls checked against a policy; no model grades another model.</p>
      <div className="mt-8 overflow-hidden rounded-xl border border-line">
        <table className="w-full text-sm">
          <thead className="bg-panel text-left text-[11px] uppercase tracking-wider text-muted"><tr><th className="px-4 py-2">Stage</th><th className="px-4 py-2">What happens</th><th className="px-4 py-2">Runs on</th></tr></thead>
          <tbody>{rows.map(([a, b, c]) => <tr key={a} className="border-t border-line"><td className="px-4 py-3 font-semibold">{a}</td><td className="px-4 py-3 text-muted">{b}</td><td className="px-4 py-3 font-mono text-xs">{c}</td></tr>)}</tbody>
        </table>
      </div>
      <h2 className="mt-12 text-2xl font-bold">Why tool calls and not text</h2>
      <p className="mt-2 max-w-2xl text-muted">Most red-teaming tools grade the model's answer. An agent's answer is not the risk; its actions are. The agent either attempted refund_customer(amount=50000) or it did not, and that fact is recorded before the tool runs. It makes results reproducible, and it makes the fix deterministic: a Cedar policy evaluated outside the model, at the tool boundary.</p>
      <h2 className="mt-12 text-2xl font-bold">What a run costs</h2>
      <p className="mt-2 max-w-2xl text-muted">Thirteen scenarios with three attempts per attack is about thirty model calls to a small Bedrock model, typically well under a rupee. Scenario generation uses a stronger model once per rule.</p>
      <div className="mt-10"><Link to="/signup" className="rounded-md bg-accent px-5 py-3 text-sm font-semibold text-accent-ink">Create your account</Link></div>
    </Page>
  )
}

export function GuidesIndex() {
  return (
    <Page>
      <h1 className="text-4xl font-bold tracking-tight">Guides</h1>
      <p className="mt-3 text-muted">Step by step, in the order you will need them. The middle group is the five ways to put an agent under test.</p>
      {[
        { h: 'Start here', items: GUIDES.filter((g) => g.slug === 'getting-started') },
        { h: 'Defining the agent under test: five ways', items: GUIDES.filter((g) => g.slug.startsWith('define-')) },
        { h: 'Rules, scenarios, fixes, AWS', items: GUIDES.filter((g) => g.slug !== 'getting-started' && !g.slug.startsWith('define-')) },
      ].map((grp) => (
        <section key={grp.h} className="mt-8">
          <h2 className="text-[11px] uppercase tracking-wider text-muted">{grp.h}</h2>
          <ul className="mt-3 space-y-3">
            {grp.items.map((g) => (
              <li key={g.slug}><Link to={`/guides/${g.slug}`} className="block rounded-xl border border-line bg-panel p-5 transition hover:border-accent/50">
                <div className="font-mono text-xs text-accent">{String(GUIDES.indexOf(g) + 1).padStart(2, '0')}</div>
                <div className="mt-1 text-lg font-semibold">{g.title}</div>
                <div className="mt-1 text-sm text-muted">{g.summary}</div>
              </Link></li>
            ))}
          </ul>
        </section>
      ))}
    </Page>
  )
}

export function GuidePage() {
  const { slug } = useParams()
  const g = GUIDES.find((x) => x.slug === slug)
  if (!g) return <Page><p className="text-muted">No such guide. <Link to="/guides" className="text-accent">All guides</Link></p></Page>
  const i = GUIDES.indexOf(g)
  return (
    <Page>
      <Link to="/guides" className="text-xs text-muted hover:text-text">← Guides</Link>
      <h1 className="mt-3 text-3xl font-bold tracking-tight">{g.title}</h1>
      <p className="mt-2 text-muted">{g.summary}</p>
      {g.sections.map((s) => (
        <section key={s.h} className="mt-8">
          <h2 className="text-xl font-semibold">{s.h}</h2>
          {s.p.map((p, k) => /^\d+ · /.test(p)
            ? <p key={k} className="mt-2 flex gap-3 text-muted"><span className="shrink-0 font-mono text-xs text-accent">{p.slice(0, p.indexOf(' · '))}</span><span>{p.slice(p.indexOf(' · ') + 3)}</span></p>
            : <p key={k} className="mt-2 text-muted">{p}</p>)}
          {s.code && <pre className="mt-3 overflow-auto rounded-lg border border-line bg-panel p-3 text-xs">{s.code}</pre>}
        </section>
      ))}
      <div className="mt-12 flex justify-between text-sm">
        {i > 0 ? <Link to={`/guides/${GUIDES[i - 1].slug}`} className="text-accent">← {GUIDES[i - 1].title}</Link> : <span />}
        {i < GUIDES.length - 1 ? <Link to={`/guides/${GUIDES[i + 1].slug}`} className="text-accent">{GUIDES[i + 1].title} →</Link> : <span />}
      </div>
    </Page>
  )
}

export function AboutPage() {
  return (
    <Page>
      <h1 className="text-4xl font-bold tracking-tight">About</h1>
      <p className="mt-4 text-muted">AgentRehearsal started from one observation: we test ordinary software before we ship it, but there is no equivalent for what an autonomous agent will decide to do with the tools it has been given. Agents now call APIs, send email and change records, and the only thing standing between a convincing message and a ₹50,000 refund is a paragraph in a system prompt.</p>
      <p className="mt-4 text-muted">The whole product is one loop. Describe what an agent is allowed to do, let AgentRehearsal stress-test it, see exactly which tool calls crossed the line, turn the findings into a least-privilege policy, and prove the fix by replaying the same tests. The agent under test is a real Strands agent on a real Bedrock model; failures are found, never scripted.</p>
      <h2 className="mt-10 text-xl font-semibold">Honesty notes</h2>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-muted">
        <li>Verdicts are computed from recorded tool calls checked against a Cedar policy. No model grades another model.</li>
        <li>The "scripted" target model is an offline simulation of a naive agent, used for development and tests, and is labelled wherever it appears.</li>
        <li>Simulated tools never touch real systems. Nothing is refunded, emailed or deleted anywhere.</li>
      </ul>
      <h2 className="mt-10 text-xl font-semibold">Open source</h2>
      <p className="mt-3 text-muted">MIT licensed. Source, build plan and deployment notes: <a className="text-accent" href="https://github.com/Ivan825/AgentRehearsal" target="_blank" rel="noreferrer">github.com/Ivan825/AgentRehearsal</a>.</p>
    </Page>
  )
}

export function ContactPage() {
  const [form, setForm] = useState({ name: '', email: '', message: '' })
  const [state, setState] = useState<'idle' | 'busy' | 'sent' | 'error'>('idle')
  const [err, setErr] = useState('')
  const input = 'mt-1 w-full rounded-md border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-accent'
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setState('busy')
    try { await api.contact(form.name, form.email, form.message); setState('sent') } catch (ex) { setErr(String((ex as Error).message)); setState('error') }
  }
  return (
    <Page>
      <h1 className="text-4xl font-bold tracking-tight">Contact</h1>
      <p className="mt-3 text-muted">Questions, an agent you would like tested, or feedback on a run. We read everything.</p>
      {state === 'sent' ? <div className="mt-8 rounded-xl border border-pass/40 bg-pass/10 p-5 text-pass">Thanks. Your message is in; we will reply by email.</div> : (
        <form onSubmit={submit} className="mt-8 space-y-4 rounded-xl border border-line bg-panel/60 p-6">
          <label className="block text-xs text-muted">Name<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={input} /></label>
          <label className="block text-xs text-muted">Email<input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className={input} /></label>
          <label className="block text-xs text-muted">Message<textarea required rows={5} value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} className={input} /></label>
          {state === 'error' && <div className="text-xs text-fail">{err}</div>}
          <button disabled={state === 'busy'} className="rounded-md bg-accent px-5 py-2.5 text-sm font-semibold text-accent-ink hover:brightness-110 disabled:opacity-50">Send</button>
        </form>
      )}
    </Page>
  )
}
