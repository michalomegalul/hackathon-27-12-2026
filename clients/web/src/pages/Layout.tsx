import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, NavLink, Outlet, isRouteErrorResponse, useLocation, useRouteError } from 'react-router'
import { getHealth, getNetDown, subscribeNet } from '../api'
import { Alert, Card } from '../components/ui'
import { Spiral } from '../components/Spiral'
import { setToken, useLoginRequired, useToken, useTokenInvalid } from '../token'

function QueueInfo() {
  const { data } = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 10_000 })
  if (!data) return null
  const busy = (data.queue.running ? 1 : 0) + data.queue.waiting
  return (
    <span className="hidden items-center gap-1.5 text-sm text-muted sm:inline-flex" title={`${data.llm.backend} ${data.llm.model}`}>
      <span className={`size-2 rounded-full ${data.ok && data.llm.reachable ? 'bg-emerald-400' : 'bg-rose-400'}`} />
      {busy === 0 ? 'fronta volná' : `ve frontě ${busy}`}
    </span>
  )
}

/** Shown while the API can't be reached; retries every active query (and by itself when the browser comes back online). */
function NetBanner() {
  const down = useSyncExternalStore(subscribeNet, getNetDown)
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const retry = () => void qc.refetchQueries({ type: 'active' })
    window.addEventListener('online', retry)
    return () => window.removeEventListener('online', retry)
  }, [qc])
  if (!down) return null
  return (
    <div
      role="alert"
      className="sticky top-[4.5rem] z-30 mt-3 flex flex-wrap items-center gap-3 border border-rose-500/40 bg-rose-950/90 px-3 py-2 text-sm text-rose-100 backdrop-blur"
    >
      <span className="mr-auto">Server je nedostupný (výpadek sítě nebo restart API). Zkoušíme to znovu.</span>
      <button
        disabled={busy}
        className="bg-white/10 px-3 py-1 font-medium hover:bg-white/20 disabled:opacity-60"
        onClick={() => {
          setBusy(true)
          void qc.refetchQueries({ type: 'active' }).finally(() => setBusy(false))
        }}
      >
        {busy ? 'Zkouším…' : 'Zkusit znovu'}
      </button>
    </div>
  )
}

const navCls = ({ isActive }: { isActive: boolean }) =>
  `border-b-2 px-2 py-1.5 text-base whitespace-nowrap sm:px-3 ${isActive ? 'border-accent text-white' : 'border-transparent text-muted hover:text-white'}`

const NAV: [to: string, label: string, end?: boolean][] = [
  ['/', 'Story', true],
  ['/rev', 'Rev story'],
  ['/history', 'History'],
  ['/about', 'About'],
]

function Shell({ children }: { children: ReactNode }) {
  // /run/:id is a Story run: keep "Story" lit there too
  const { pathname } = useLocation()
  const inRun = pathname.startsWith('/run/')
  return (
    <div className="flex min-h-dvh flex-col">
      <header data-chrome="top" className="sticky top-0 z-30 border-b border-line bg-bg/95 backdrop-blur">
        <div className="flex h-16 items-center gap-3 px-3 sm:gap-6 sm:px-6">
          <Link to="/" className="flex shrink-0 items-center gap-2 text-xl font-semibold tracking-tight">
            <Spiral />
            <span className="hidden sm:inline">Story2Data</span>
          </Link>
          <nav className="-mx-1 flex min-w-0 gap-0.5 overflow-x-auto px-1">
            {NAV.map(([to, label, end]) => (
              <NavLink key={to} to={to} end={end} className={(a) => navCls({ isActive: a.isActive || (to === '/' && inRun) })}>
                {label}
              </NavLink>
            ))}
          </nav>
          <span className="ml-auto" />
          <QueueInfo />
          <Logout />
        </div>
      </header>
      <div className="w-full max-w-7xl px-3 sm:px-6">
        <NetBanner />
      </div>
      <main className="w-full max-w-7xl flex-1 px-3 pb-12 pt-4 sm:px-6 sm:pt-6">{children}</main>
    </div>
  )
}

function Logout() {
  const token = useToken()
  const qc = useQueryClient()
  if (!token) return null
  return (
    <button
      className="text-sm text-muted hover:text-white"
      title="Zapomenout token v tomto prohlížeči"
      onClick={() => {
        setToken('')
        qc.clear()
      }}
    >
      Odhlásit
    </button>
  )
}

function TokenForm() {
  const [value, setValue] = useState('')
  const qc = useQueryClient()
  const invalid = useTokenInvalid()
  return (
    <Card className="mt-6 max-w-md">
      <h1 className="text-lg font-semibold">Přihlášení</h1>
      {invalid && (
        <div className="mt-3">
          <Alert>Neplatný token. Zadejte platný token (nebo požádejte tým o nový).</Alert>
        </div>
      )}
      <p className="mt-1 text-sm text-muted">
        Zadejte přístupový token k API (dostanete ho od týmu). Uloží se jen v tomto prohlížeči.
      </p>
      <form
        className="mt-4 grid gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          qc.clear()
          setToken(value)
        }}
      >
        <input
          type="password"
          autoComplete="current-password"
          required
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="token"
          className="w-full border border-line bg-bg px-3 py-2 text-[16px] focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent sm:text-sm"
        />
        <button className="bg-accent px-4 py-2.5 font-medium text-slate-950 hover:brightness-110">Pokračovat</button>
      </form>
    </Card>
  )
}

export function Layout() {
  const token = useToken()
  const loginRequired = useLoginRequired()
  return <Shell>{token || !loginRequired ? <Outlet /> : <TokenForm />}</Shell>
}

export function RouteError() {
  const err = useRouteError()
  const msg = isRouteErrorResponse(err)
    ? err.status === 404
      ? 'Stránka neexistuje.'
      : `${err.status} ${err.statusText}`
    : err instanceof Error
      ? err.message
      : 'Neznámá chyba.'
  return (
    <Shell>
      <Alert>{msg}</Alert>
      <Link to="/" className="mt-4 inline-block text-accent hover:underline">
        ← Zpět na úvod
      </Link>
    </Shell>
  )
}
