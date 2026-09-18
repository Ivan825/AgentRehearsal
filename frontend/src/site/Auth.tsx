import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, session } from '../api'
import { Logo } from './Shell'

export function AuthPage({ mode }: { mode: 'signin' | 'signup' }) {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const next = params.get('next') || '/app'

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null)
    try {
      const r = mode === 'signup' ? await api.signup(email, password, name) : await api.login(email, password)
      session.set(r.token, r.user)
      nav(next)
    } catch (ex) { setErr(String((ex as Error).message)) } finally { setBusy(false) }
  }
  const input = 'mt-1 w-full rounded-md border border-line bg-panel px-3 py-2 text-sm text-text outline-none focus:border-accent'
  return (
    <div className="flex min-h-full items-center justify-center px-4 py-16">
      <div className="w-full max-w-sm">
        <Link to="/" className="flex items-center justify-center gap-2"><Logo /><span className="text-lg font-bold">AgentRehearsal</span></Link>
        <h1 className="mt-8 text-center text-2xl font-bold">{mode === 'signup' ? 'Create your account' : 'Welcome back'}</h1>
        <p className="mt-1 text-center text-sm text-muted">{mode === 'signup' ? 'Your workspace starts with the SupportBot example loaded.' : 'Sign in to your workspace.'}</p>
        <form onSubmit={submit} className="mt-8 space-y-4 rounded-xl border border-line bg-panel/60 p-6">
          {mode === 'signup' && <label className="block text-xs text-muted">Name<input value={name} onChange={(e) => setName(e.target.value)} className={input} autoComplete="name" /></label>}
          <label className="block text-xs text-muted">Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={input} autoComplete="email" /></label>
          <label className="block text-xs text-muted">Password<input type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} className={input} autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} />{mode === 'signup' && <span className="text-[11px]">At least 8 characters.</span>}</label>
          {err && <div className="rounded border border-fail/40 bg-fail/10 p-2 text-xs text-fail">{err}</div>}
          <button disabled={busy} className="w-full rounded-md bg-accent py-2.5 text-sm font-semibold text-accent-ink hover:brightness-110 disabled:opacity-50">{busy ? '…' : mode === 'signup' ? 'Create account' : 'Sign in'}</button>
        </form>
        <p className="mt-4 text-center text-sm text-muted">
          {mode === 'signup' ? <>Already have an account? <Link to="/signin" className="text-accent">Sign in</Link></> : <>New here? <Link to="/signup" className="text-accent">Create an account</Link></>}
        </p>
      </div>
    </div>
  )
}
