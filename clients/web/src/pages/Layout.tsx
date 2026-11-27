import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, NavLink, Outlet, isRouteErrorResponse, useRouteError } from 'react-router'
import { getHealth, getNetDown, subscribeNet } from '../api'
import { Alert, Card } from '../components/ui'
import { setToken, useToken, useTokenInvalid } from '../token'

function QueueInfo() {
  const { data } = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 10_000 })
  if (!data) return null
  const busy = (data.queue.running ? 1 : 0) + data.queue.waiting
  return (
    <span className="hidden items-center gap-1.5 text-xs text-muted sm:inline-flex" title={`${data.llm.backend} ${data.llm.model}`}>
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
      className="sticky top-0 z-30 mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-rose-500/40 bg-rose-950/90 px-3 py-2 text-sm text-rose-100 backdrop-blur"
    >
      <span className="mr-auto">Server je nedostupný (výpadek sítě nebo restart API). Zkoušíme to znovu.</span>
      <button
        disabled={busy}
        className="rounded-md bg-white/10 px-3 py-1 font-medium hover:bg-white/20 disabled:opacity-60"
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
  `rounded-md px-2.5 py-1.5 text-sm ${isActive ? 'bg-white/10 text-white' : 'text-muted hover:text-white'}`

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex min-h-dvh max-w-6xl flex-col px-3 sm:px-6">
      <header className="flex items-center gap-3 py-3 sm:py-4">
        <Link to="/" className="mr-auto flex items-center gap-2 font-semibold tracking-tight">
          <span className="grid size-7 place-items-center rounded-md bg-accent/20 text-accent">S</span>
          Story2Data
        </Link>
        <QueueInfo />
        <nav className="flex gap-1">
          <NavLink to="/" end className={navCls}>
            Nová úloha
          </NavLink>
          <NavLink to="/jobs" end className={navCls}>
            Moje úlohy
          </NavLink>
        </nav>
        <Logout />
      </header>
      <NetBanner />
      <main className="flex-1 pb-12">{children}</main>
    </div>
  )
}

function Logout() {
  const token = useToken()
  const qc = useQueryClient()
  if (!token) return null
  return (
    <button
      className="text-xs text-muted hover:text-white"
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
    <Card className="mx-auto mt-6 max-w-md">
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
          className="w-full rounded-lg border border-line bg-bg px-3 py-2 text-[16px] focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent sm:text-sm"
        />
        <button className="rounded-lg bg-accent px-4 py-2.5 font-medium text-slate-950 hover:brightness-110">Pokračovat</button>
      </form>
    </Card>
  )
}

export function Layout() {
  const token = useToken()
  return <Shell>{token ? <Outlet /> : <TokenForm />}</Shell>
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
