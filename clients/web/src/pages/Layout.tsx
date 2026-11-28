import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Outlet, isRouteErrorResponse, useLocation, useRouteError } from 'react-router'
import { getNetDown, inputOptions, isStatus, jobOptions, statsOptions, subscribeNet } from '../api'
import { duration, stepEn } from '../format'
import { clearActive, useActive, useLastRun } from '../run/lastRun'
import { recallSent } from '../run/useSend'
import { Alert, Card } from '../components/ui'
import { Spiral } from '../components/Spiral'
import { setToken, useLoginRequired, useToken, useTokenInvalid } from '../token'

/**
 * The server queue, in every page of the header (also on Story, also while your own run is open):
 * "Queue: idle" or "Queue: 1 running, 2 waiting". Click for what the running job is doing now
 * (GET /v1/stats; the API reports only the running job's step and the number of waiting ones).
 */
function QueueChip() {
  const { data: s } = useQuery(statsOptions())
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false)
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', esc)
    }
  }, [open])
  if (!s) return null
  const label = !s.running && !s.waiting ? 'idle' : `${s.running ? '1 running' : '0 running'}${s.waiting ? `, ${s.waiting} waiting` : ''}`
  return (
    <div ref={box} className="relative shrink-0">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="border border-line px-2.5 py-1 text-xs whitespace-nowrap text-slate-300 hover:border-slate-500 hover:text-white sm:text-sm"
      >
        <span className="hidden sm:inline">Queue: </span>
        {label}
      </button>
      {open && (
        <div className="absolute right-0 top-full z-40 mt-2 grid w-72 gap-3 border border-line bg-panel p-3 text-sm shadow-xl">
          {s.running ? (
            <div className="grid gap-1.5">
              <div className="text-xs text-muted">Running now</div>
              <div className="font-medium">{stepEn(s.running.step ?? 'starting')}</div>
              <div className="h-1.5 overflow-hidden bg-white/10">
                <div className="h-full bg-accent transition-[width] duration-700" style={{ width: `${Math.round(Math.min(1, s.running.progress) * 100)}%` }} />
              </div>
              <div className="flex justify-between text-xs tabular-nums text-muted">
                <span>{Math.round(Math.min(1, s.running.progress) * 100)} %</span>
                <span>~{duration(s.running.eta_s)} left</span>
              </div>
            </div>
          ) : (
            <p className="text-muted">Nothing is running.</p>
          )}
          <div className="text-xs text-muted">
            {s.waiting ? `${s.waiting} waiting behind it.` : 'Nobody is waiting.'} Median run {s.median_run_s === null ? 'unknown' : duration(s.median_run_s)}.
          </div>
        </div>
      )}
    </div>
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
      <span className="mr-auto">The server is unreachable (network outage or API restart). Retrying.</span>
      <button
        disabled={busy}
        className="bg-white/10 px-3 py-1 font-medium hover:bg-white/20 disabled:opacity-60"
        onClick={() => {
          setBusy(true)
          void qc.refetchQueries({ type: 'active' }).finally(() => setBusy(false))
        }}
      >
        {busy ? 'Retrying…' : 'Retry'}
      </button>
    </div>
  )
}

const navCls = ({ isActive }: { isActive: boolean }) =>
  `border-b-2 px-2 py-1.5 text-base whitespace-nowrap sm:px-3 ${isActive ? 'border-accent text-white' : 'border-transparent text-muted hover:text-white'}`

/** The run started last in this tab, from any page: queued / running / done, one click back to it. */
function ActiveRun() {
  const a = useActive()
  const { pathname } = useLocation()
  const job = useQuery({ ...jobOptions(a?.id ?? ''), enabled: Boolean(a) }) // shares the run page's polling
  const input = useQuery({ ...inputOptions(a?.id ?? ''), enabled: Boolean(a) })
  const here = Boolean(a && (pathname === a.path || pathname.startsWith(`${a.path}/`)))
  const j = job.data
  const finishedHere = here && (j?.status === 'done' || j?.status === 'error')
  const gone = isStatus(job.error, 404)
  // seen it finished, or it no longer exists: stop following it
  useEffect(() => {
    if (finishedHere || gone) clearActive()
  }, [finishedHere, gone])
  if (!a || here || !j) return null

  const name = input.data?.company || recallSent(a.id)?.specName || 'run'
  const [dot, text, tone] =
    j.status === 'queued'
      ? ['bg-slate-400', j.position > 0 ? `queued (${j.position})` : 'queued', 'border-line text-slate-300']
      : j.status === 'running'
        ? ['bg-sky-400', `${Math.round(Math.min(1, j.progress) * 100)} %`, 'border-sky-500/40 text-sky-200']
        : j.status === 'done'
          ? ['bg-emerald-400', 'done', 'border-emerald-500/40 text-emerald-200']
          : ['bg-rose-400', 'error', 'border-rose-500/40 text-rose-200']
  return (
    <Link
      to={a.path}
      title={`Back to ${name}${j.step && j.status === 'running' ? ` · ${stepEn(j.step)}` : ''}`}
      className={`inline-flex min-w-0 shrink items-center gap-1.5 rounded-full border bg-white/[0.03] px-2.5 py-1 text-xs hover:bg-white/[0.07] ${tone}`}
    >
      <span className={`size-2 shrink-0 rounded-full ${dot}`} />
      <span className="hidden max-w-40 truncate text-slate-200 sm:inline">{name}</span>
      <span className="shrink-0 tabular-nums">{text}</span>
    </Link>
  )
}

function Shell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  // Story and Rev story lead back to the run left there (per browser tab); lit on their runs too
  const lastStory = useLastRun('story')
  const lastRev = useLastRun('rev')
  const NAV: [to: string, label: string, active: boolean][] = [
    [lastStory ? `/run/${lastStory}` : '/', 'Story', pathname === '/' || pathname.startsWith('/run/')],
    [lastRev ? `/rev/${lastRev}` : '/rev', 'Rev story', pathname === '/rev' || pathname.startsWith('/rev/')],
    ['/history', 'History', pathname.startsWith('/history')],
    ['/demo', 'Demo', pathname.startsWith('/demo')],
    ['/spec', 'Spec', pathname.startsWith('/spec')],
  ]
  return (
    <div className="flex min-h-dvh flex-col">
      <header data-chrome="top" className="sticky top-0 z-30 border-b border-line bg-bg/95 backdrop-blur">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-3 px-3 sm:gap-6 sm:px-6">
          <Link to="/" className="flex shrink-0 items-center gap-2 text-xl font-semibold tracking-tight">
            <Spiral />
            <span className="hidden sm:inline">Story2Data</span>
          </Link>
          <nav className="-mx-1 flex min-w-0 gap-0.5 overflow-x-auto px-1">
            {NAV.map(([to, label, isActive]) => (
              <Link key={label} to={to} aria-current={isActive ? 'page' : undefined} className={navCls({ isActive })}>
                {label}
              </Link>
            ))}
          </nav>
          <span className="ml-auto" />
          <ActiveRun />
          <QueueChip />
          <Link to="/about" aria-current={pathname.startsWith('/about') ? 'page' : undefined} className={navCls({ isActive: pathname.startsWith('/about') })}>
            About
          </Link>
          <Logout />
        </div>
      </header>
      <div className="mx-auto w-full max-w-6xl px-3 sm:px-6">
        <NetBanner />
      </div>
      <main className="mx-auto w-full max-w-6xl flex-1 px-3 pb-12 pt-4 sm:px-6 sm:pt-6">{children}</main>
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
      title="Forget the token in this browser"
      onClick={() => {
        setToken('')
        qc.clear()
      }}
    >
      Log out
    </button>
  )
}

function TokenForm() {
  const [value, setValue] = useState('')
  const qc = useQueryClient()
  const invalid = useTokenInvalid()
  return (
    <Card className="mt-6 max-w-md">
      <h1 className="text-lg font-semibold">Log in</h1>
      {invalid && (
        <div className="mt-3">
          <Alert>Invalid token. Enter a valid one (or ask the team for a new one).</Alert>
        </div>
      )}
      <p className="mt-1 text-sm text-muted">
        Enter the API access token (you get it from the team). It is stored in this browser only.
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
        <button className="bg-accent px-4 py-2.5 font-medium text-slate-950 hover:brightness-110">Continue</button>
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
      ? 'Page not found.'
      : `${err.status} ${err.statusText}`
    : err instanceof Error
      ? err.message
      : 'Unknown error.'
  return (
    <Shell>
      <Alert>{msg}</Alert>
      <Link to="/" className="mt-4 inline-block text-accent hover:underline">
        ← Back to start
      </Link>
    </Shell>
  )
}
