// The run view used by Story, Rev story and History: the process in a left sidebar (a top drawer
// on the phone) with a sticky status block, and the six sections in the main column.
import { useEffect, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router'
import { duration } from '../format'
import { STAGES, scrollToStage, sectionId, type Run, type StageId, type StageState, type Status } from './useRun'

// ---- status block ----------------------------------------------------------------------

function Bar({ value, tone }: { value: number; tone: Status['tone'] }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100)
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-white/10" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
      <div
        className={`h-full rounded-full transition-[width] duration-700 ease-out ${tone === 'error' ? 'bg-rose-400' : 'bg-accent'}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

function StatusBlock({ s, compact = false }: { s: Status; compact?: boolean }) {
  const dot =
    s.tone === 'busy' ? 'bg-accent animate-pulse' : s.tone === 'done' ? 'bg-accent' : s.tone === 'error' ? 'bg-rose-400' : 'bg-slate-500'
  return (
    <div className="grid gap-2" aria-live="polite">
      <div className="flex items-baseline gap-2">
        <span className={`size-2 shrink-0 translate-y-[-1px] rounded-full ${dot}`} />
        <span className={`min-w-0 font-medium ${compact ? 'truncate text-sm' : 'text-sm leading-snug'}`}>{s.title}</span>
        {compact && s.etaS !== null && <span className="ml-auto shrink-0 text-xs tabular-nums text-muted">zbývá ~{duration(s.etaS)}</span>}
      </div>
      {s.progress !== null && <Bar value={s.progress} tone={s.tone} />}
      {!compact && (
        <div className="grid gap-0.5 text-xs text-muted">
          {s.etaS !== null && <span className="tabular-nums">zbývá ~{duration(s.etaS)}</span>}
          {s.position !== null && s.position > 0 && <span className="tabular-nums">pořadí ve frontě: {s.position + 1}.</span>}
          {s.detail && <span className={s.tone === 'error' ? 'text-rose-300' : ''}>{s.detail}</span>}
        </div>
      )}
    </div>
  )
}

// ---- process list ----------------------------------------------------------------------

function Marker({ state, n }: { state: StageState; n: number }) {
  if (state === 'done') return <span className="grid size-5 place-items-center rounded-full bg-accent/15 text-[11px] font-bold text-accent">✓</span>
  if (state === 'error') return <span className="grid size-5 place-items-center rounded-full bg-rose-500/20 text-[11px] font-bold text-rose-300">!</span>
  if (state === 'running')
    return (
      <span className="relative grid size-5 place-items-center">
        <span className="absolute inset-0 animate-ping rounded-full bg-accent/25 motion-reduce:animate-none" />
        <span className="size-2.5 rounded-full bg-accent" />
      </span>
    )
  return <span className="grid size-5 place-items-center rounded-full border border-line text-[10px] text-slate-500">{n}</span>
}

function ProcessList({ run, onPick }: { run: Run; onPick?: () => void }) {
  return (
    <ol className="grid gap-0.5">
      {STAGES.map((st, i) => {
        const s = run.stages[st.id]
        const reachable = s.state === 'done' || s.state === 'error'
        const label = (
          <>
            <Marker state={s.state} n={i + 1} />
            <span className="grid min-w-0">
              <span
                className={`text-sm ${
                  s.state === 'pending' ? 'text-slate-500' : s.state === 'running' ? 'font-medium text-white' : s.state === 'error' ? 'text-rose-200' : 'text-slate-200'
                }`}
              >
                {st.label}
              </span>
              {s.state === 'running' && s.sub && <span className="truncate text-[11px] text-muted">{s.sub}</span>}
            </span>
          </>
        )
        return (
          <li key={st.id}>
            {reachable ? (
              <button
                onClick={() => {
                  scrollToStage(st.id)
                  onPick?.()
                }}
                className="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left hover:bg-white/[0.05]"
              >
                {label}
              </button>
            ) : (
              <div className="flex items-center gap-2.5 px-2 py-1.5" aria-current={s.state === 'running' ? 'step' : undefined}>
                {label}
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}

// ---- phone: a top drawer, the status always visible ------------------------------------

function MobileBar({ run }: { run: Run }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="sticky top-14 z-20 -mx-3 mb-4 border-b border-line bg-bg/95 px-3 py-2.5 backdrop-blur sm:-mx-6 sm:px-6 lg:hidden">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <StatusBlock s={run.status} compact />
        </div>
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="shrink-0 rounded-md border border-line px-2.5 py-1 text-xs text-slate-300 hover:border-slate-500"
        >
          Průběh <span className={`inline-block transition-transform ${open ? 'rotate-180' : ''}`}>▾</span>
        </button>
      </div>
      {open && (
        <div className="mt-2.5 rounded-xl border border-line bg-panel p-2">
          <ProcessList run={run} onPick={() => setOpen(false)} />
          {run.status.detail && <p className="px-2 pb-1 pt-2 text-xs text-muted">{run.status.detail}</p>}
        </div>
      )}
    </div>
  )
}

// ---- sections --------------------------------------------------------------------------

function Skeleton({ busy }: { busy: boolean }) {
  return (
    <div className={`grid gap-2 ${busy ? 'animate-pulse motion-reduce:animate-none' : ''}`} aria-hidden>
      <div className="h-3 w-2/3 rounded bg-white/[0.06]" />
      <div className="h-3 w-1/2 rounded bg-white/[0.06]" />
      <div className="h-3 w-3/5 rounded bg-white/[0.06]" />
    </div>
  )
}

export function Section({
  run,
  id,
  title,
  hint,
  children,
  waiting,
}: {
  run: Run
  id: StageId
  title: string
  /** one line under the title */
  hint?: ReactNode
  /** the content once the stage is done */
  children?: ReactNode
  /** what shows while the stage runs (default: a skeleton) */
  waiting?: ReactNode
}) {
  const s = run.stages[id]
  const n = STAGES.findIndex((x) => x.id === id) + 1
  return (
    <section
      id={sectionId(id)}
      className={`scroll-mt-32 rounded-xl border p-4 sm:p-5 lg:scroll-mt-20 ${
        s.state === 'done' ? 'border-line bg-panel' : s.state === 'error' ? 'border-rose-500/40 bg-panel' : 'border-line/70 bg-panel/40'
      }`}
    >
      <header className="mb-3 flex items-baseline gap-2">
        <span className="font-mono text-xs text-slate-500">{n}</span>
        <h2 className={`font-semibold ${s.state === 'pending' ? 'text-slate-500' : ''}`}>{title}</h2>
        {s.state === 'running' && <span className="text-xs text-accent">{s.sub ?? 'běží'}…</span>}
        {hint && s.state === 'done' && <span className="ml-auto text-xs text-muted">{hint}</span>}
      </header>
      {s.state === 'done' ? (
        children
      ) : s.state === 'error' ? (
        <div className="grid justify-items-start gap-3">
          <p className="text-sm text-rose-200">{s.error}</p>
          {s.retry && (
            <button onClick={s.retry} className="rounded-lg border border-rose-400/40 px-3 py-1.5 text-sm text-rose-100 hover:bg-rose-500/10">
              Zkusit znovu
            </button>
          )}
        </div>
      ) : s.state === 'running' ? (
        (waiting ?? <Skeleton busy />)
      ) : (
        <Skeleton busy={false} />
      )}
    </section>
  )
}

// ---- the frame -------------------------------------------------------------------------

/** Sidebar + main column. `children` are the sections; `bottom` sits under them (the chat input). */
export function RunView({ run, children, bottom, top }: { run: Run; children: ReactNode; bottom?: ReactNode; top?: ReactNode }) {
  // a link with #s-<stage> (e.g. the old /jobs/:id/story) scrolls there once that section is filled
  const { hash } = useLocation()
  const target = STAGES.find((s) => `#${sectionId(s.id)}` === hash)?.id
  const ready = target ? run.stages[target].state === 'done' : false
  useEffect(() => {
    if (target && ready) scrollToStage(target)
  }, [target, ready])

  return (
    <div className="lg:grid lg:grid-cols-[14.5rem_minmax(0,1fr)] lg:gap-6">
      <MobileBar run={run} />
      <aside className="hidden lg:block">
        <div className="sticky top-20 grid gap-4">
          <div className="rounded-xl border border-line bg-panel p-3.5">
            <StatusBlock s={run.status} />
          </div>
          <nav aria-label="Průběh" className="rounded-xl border border-line bg-panel p-1.5">
            <ProcessList run={run} />
          </nav>
        </div>
      </aside>
      <div className="grid min-w-0 content-start gap-4">
        {top}
        {children}
        {bottom}
      </div>
    </div>
  )
}
