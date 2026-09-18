import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import './index.css'
import App from './App'
import { api, session } from './api'
import { Landing } from './site/Landing'
import { AuthPage } from './site/Auth'
import { AboutPage, ContactPage, GuidePage, GuidesIndex, ProductPage } from './site/Pages'

/** The workspace needs a session when the API has auth on; with auth off it opens directly. */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<'checking' | 'ok' | 'redirect'>('checking')
  const loc = useLocation()
  useEffect(() => {
    api.authConfig().then((c) => setState(!c.enabled || session.token ? 'ok' : 'redirect')).catch(() => setState('ok'))
  }, [])
  if (state === 'checking') return <div className="p-10 text-sm text-muted">Loading…</div>
  if (state === 'redirect') return <Navigate to={`/signin?next=${encodeURIComponent(loc.pathname)}`} replace />
  return <>{children}</>
}

function ScrollTop() { const { pathname } = useLocation(); useEffect(() => { window.scrollTo(0, 0) }, [pathname]); return null }

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <ScrollTop />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/product" element={<ProductPage />} />
        <Route path="/guides" element={<GuidesIndex />} />
        <Route path="/guides/:slug" element={<GuidePage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/contact" element={<ContactPage />} />
        <Route path="/signin" element={<AuthPage mode="signin" />} />
        <Route path="/signup" element={<AuthPage mode="signup" />} />
        <Route path="/app/*" element={<RequireAuth><App /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
