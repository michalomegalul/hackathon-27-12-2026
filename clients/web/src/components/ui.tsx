import type { ReactNode } from 'react'
import type { JobStatus, VerificationStatus } from '../api'

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
    <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tone[t]}`}>
      {children}
    </span>
  )
}

const JOB_STATUS: Record<JobStatus, [Tone, string]> = {
  queued: ['gray', 've frontě'],
  running: ['blue', 'běží'],
  done: ['green', 'hotovo'],
  error: ['red', 'chyba'],
}
export const JobStatusBadge = ({ s }: { s: JobStatus }) => <Badge t={JOB_STATUS[s][0]}>{JOB_STATUS[s][1]}</Badge>

const VER_STATUS: Record<VerificationStatus, [Tone, string]> = {
  confirmed: ['green', 'potvrzeno'],
  not_confirmed: ['amber', 'nepotvrzeno'],
  not_testable: ['gray', 'nelze ověřit'],
}
export const VerificationBadge = ({ s }: { s: VerificationStatus }) => (
  <Badge t={VER_STATUS[s]?.[0] ?? 'gray'}>{VER_STATUS[s]?.[1] ?? s}</Badge>
)

// ---- layout bits -----------------------------------------------------------------------

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-line bg-panel p-4 sm:p-5 ${className}`}>{children}</section>
}

export function Alert({ children, t = 'red' }: { children: ReactNode; t?: 'red' | 'amber' }) {
  const c = t === 'red' ? 'border-rose-500/40 bg-rose-500/10 text-rose-200' : 'border-amber-500/40 bg-amber-500/10 text-amber-100'
  return <div className={`rounded-lg border px-3 py-2 text-sm ${c}`}>{children}</div>
}

export const Spinner = () => (
  <span className="inline-block size-4 animate-spin rounded-full border-2 border-current border-r-transparent align-[-2px]" />
)
