import type { ReactNode } from 'react'
import type { JobStatus, VerificationStatus } from '../api'
import { plural } from '../format'

// ---- badges ----------------------------------------------------------------------------

const tone = {
  green: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  red: 'bg-rose-500/15 text-rose-300 ring-rose-500/30',
  amber: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  blue: 'bg-sky-500/15 text-sky-300 ring-sky-500/30',
  gray: 'bg-slate-500/15 text-slate-300 ring-slate-500/30',
}
export type Tone = keyof typeof tone

export function Badge({ t, children }: { t: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center whitespace-nowrap px-1.5 py-0.5 text-xs font-medium ${tone[t]}`}>
      {children}
    </span>
  )
}

const JOB_STATUS: Record<JobStatus, [Tone, string]> = {
  queued: ['gray', 'queued'],
  running: ['blue', 'running'],
  done: ['green', 'done'],
  error: ['red', 'error'],
}
export const JobStatusBadge = ({ s }: { s: JobStatus }) => <Badge t={JOB_STATUS[s][0]}>{JOB_STATUS[s][1]}</Badge>

const VER_STATUS: Record<VerificationStatus, [Tone, string]> = {
  confirmed: ['green', 'confirmed'],
  not_confirmed: ['amber', 'not confirmed'],
  not_testable: ['gray', 'not testable'],
}
export const VerificationBadge = ({ s }: { s: VerificationStatus }) => (
  <Badge t={VER_STATUS[s]?.[0] ?? 'gray'}>{VER_STATUS[s]?.[1] ?? s}</Badge>
)

// ---- layout bits -----------------------------------------------------------------------

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`border-t border-line pt-5 ${className}`}>{children}</section>
}

export function Alert({ children, t = 'red' }: { children: ReactNode; t?: 'red' | 'amber' }) {
  const c = t === 'red' ? 'border-rose-500/70 text-rose-200' : 'border-amber-500/70 text-amber-100'
  return <div className={`border-l-2 py-1 pl-3 text-sm ${c}`}>{children}</div>
}

export const Spinner = () => (
  <span className="inline-block size-4 animate-spin rounded-full border-2 border-current border-r-transparent align-[-2px]" />
)

/** "Show 4 more tables" / "Show less" under a cut-off list. */
export function ShowMore({ open, onClick, more, noun }: { open: boolean; onClick: () => void; more: number; noun: [string, string] }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={open}
      className="justify-self-start border border-line px-3 py-1.5 text-sm text-slate-300 hover:border-slate-500 hover:text-white"
    >
      {open ? 'Show less ▴' : `Show ${more} more ${plural(more, noun)} ▾`}
    </button>
  )
}
