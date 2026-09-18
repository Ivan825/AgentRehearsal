import { useEffect, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { session } from '../api'

export function useTheme() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => { try { return (localStorage.getItem('ar-theme') as 'dark' | 'light') || 'dark' } catch { return 'dark' } })
  useEffect(() => { document.documentElement.setAttribute('data-theme', theme); try { localStorage.setItem('ar-theme', theme) } catch { /* ignore */ } }, [theme])
  return { theme, toggle: () => setTheme(theme === 'dark' ? 'light' : 'dark') }
}

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 30 30" aria-hidden="true">
      <rect x="1.5" y="1.5" width="27" height="27" rx="7" fill="none" stroke="var(--c-accent)" strokeWidth="2" />
      <path d="M9 16.5 L13 20.5 L21 10.5" fill="none" stroke="var(--c-accent)" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="21.5" cy="21" r="3.2" fill="var(--c-ink)" stroke="var(--c-fail)" strokeWidth="2" />
    </svg>
  )
}

export function SiteNav() {
  const { theme, toggle } = useTheme()
  const user = session.user
  const link = ({ isActive }: { isActive: boolean }) => `px-3 py-1.5 text-sm ${isActive ? 'text-text' : 'text-muted hover:text-text'}`
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-ink/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
        <Link to="/" className="flex items-center gap-2.5"><Logo /><span className="text-base font-bold tracking-tight">AgentRehearsal</span></Link>
        <nav className="ml-4 hidden items-center md:flex">
          <NavLink to="/product" className={link}>Product</NavLink>
          <NavLink to="/guides" className={link}>Guides</NavLink>
          <NavLink to="/about" className={link}>About</NavLink>
          <NavLink to="/contact" className={link}>Contact</NavLink>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={toggle} className="rounded-md border border-line px-2.5 py-1.5 text-xs text-muted hover:text-text" title="Toggle theme">{theme === 'dark' ? '☀' : '☾'}</button>
          {user ? (
            <Link to="/app" className="rounded-md bg-accent px-3.5 py-2 text-sm font-semibold text-accent-ink hover:brightness-110">Open workspace →</Link>
          ) : (<>
            <Link to="/signin" className="px-3 py-1.5 text-sm text-muted hover:text-text">Sign in</Link>
            <Link to="/signup" className="rounded-md bg-accent px-3.5 py-2 text-sm font-semibold text-accent-ink hover:brightness-110">Get started</Link>
          </>)}
        </div>
      </div>
    </header>
  )
}

export function SiteFooter() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto grid max-w-6xl gap-6 px-4 py-10 text-sm text-muted md:grid-cols-4">
        <div>
          <div className="flex items-center gap-2 text-text"><Logo size={22} /><span className="font-semibold">AgentRehearsal</span></div>
          <p className="mt-2 text-xs">Crash-test your AI agent before your users do.</p>
        </div>
        <div><div className="mb-2 text-xs uppercase tracking-wider">Product</div><Link to="/product" className="block hover:text-text">How it works</Link><Link to="/guides" className="block hover:text-text">Guides</Link><Link to="/signup" className="block hover:text-text">Create an account</Link></div>
        <div><div className="mb-2 text-xs uppercase tracking-wider">Company</div><Link to="/about" className="block hover:text-text">About</Link><Link to="/contact" className="block hover:text-text">Contact</Link><a href="https://github.com/Ivan825/AgentRehearsal" target="_blank" rel="noreferrer" className="block hover:text-text">GitHub ↗</a></div>
        <div><div className="mb-2 text-xs uppercase tracking-wider">Built with</div><div>Strands Agents · Amazon Bedrock · Cedar</div><div>AgentCore Gateway · DynamoDB · Amplify</div><div className="mt-2 text-xs">MIT licensed · open source</div></div>
      </div>
    </footer>
  )
}

export function Page({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="flex min-h-full flex-col">
      <SiteNav />
      <main className={`mx-auto w-full flex-1 px-4 py-10 ${wide ? 'max-w-6xl' : 'max-w-3xl'}`}>{children}</main>
      <SiteFooter />
    </div>
  )
}
