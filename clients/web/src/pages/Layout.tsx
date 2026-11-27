import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, NavLink, Outlet, isRouteErrorResponse, useRouteError } from 'react-router'
import { getHealth, hasToken } from '../api'
import { Alert } from '../components/ui'

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
      </header>
      <main className="flex-1 pb-12">{children}</main>
    </div>
  )
}

export function Layout() {
  return (
    <Shell>
      {!hasToken && (
        <div className="mb-4">
          <Alert t="amber">
            Chybí token: nastavte <code>VITE_API_TOKEN</code> v <code>clients/web/.env.local</code> a restartujte{' '}
            <code>npm run dev</code>.
          </Alert>
        </div>
      )}
      <Outlet />
    </Shell>
  )
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
