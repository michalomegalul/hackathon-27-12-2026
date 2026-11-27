// /jobs/:id/story: the demo page for the pitch. The generated tables as an ERD, the narrative
// beside it with an arrow from each event's claim to the KPI column it moved, and per confirmed
// event its daily KPI (target vs control) around `start`. Lazy-loaded: React Flow, uPlot and
// anime.js stay out of the main bundle.
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { ReactFlowProvider } from '@xyflow/react'
import { createScope, createTimeline, stagger, type Scope } from 'animejs'
import { jobOptions, resultOptions, tablesOptions, type TableInfo, type VerificationRow } from '../api'
import { Alert, Spinner, VerificationBadge } from '../components/ui'
import { KPI_CS, dateCs, withUnit } from '../format'
import { Erd, SpanArrow } from '../story/Erd'
import { KpiChart } from '../story/KpiChart'
import { kpiColumn } from '../story/model'
import '../story/story.css'

const REDUCE = '(prefers-reduced-motion: reduce)'
function useReducedMotion() {
  return useSyncExternalStore(
    (cb) => {
      const m = matchMedia(REDUCE)
      m.addEventListener('change', cb)
      return () => m.removeEventListener('change', cb)
    },
    () => matchMedia(REDUCE).matches,
  )
}

const rowKey = (v: VerificationRow) => `${v.event_id}·${v.kpi}·${v.target}`

// ---- side panel: narrative, then one step per verification row --------------------------

function Steps({
  rows,
  tables,
  active,
  onPick,
  spanRef,
}: {
  rows: VerificationRow[]
  tables: TableInfo[]
  active: string | null
  onPick: (k: string) => void
  spanRef: (el: HTMLSpanElement | null) => void
}) {
  return (
    <ol className="grid gap-2">
      {rows.map((v) => {
        const k = rowKey(v)
        const on = k === active
        const col = kpiColumn(v.kpi, tables)
        return (
          <li key={k} className="step opacity-0">
            <button
              onClick={() => onPick(k)}
              onMouseEnter={() => onPick(k)}
              className={`grid w-full gap-1.5 rounded-lg border px-3 py-2.5 text-left transition-colors ${
                on ? 'border-accent/50 bg-accent/10' : 'border-line hover:border-white/20 hover:bg-white/5'
              }`}
            >
              <span className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-mono text-muted">{v.event_id}</span>
                <VerificationBadge s={v.status} />
                <span className="text-muted">{dateCs(v.start)}</span>
              </span>
              <span className="text-sm leading-snug">
                <span
                  ref={on ? spanRef : undefined}
                  className={`rounded px-0.5 ${on ? 'bg-accent/15 text-accent' : 'text-slate-100'}`}
                >
                  {v.claim_cs}
                </span>
              </span>
              <span className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted">
                <span>{KPI_CS[v.kpi] ?? v.kpi}</span>
                {col && <span className="font-mono">→ {col.join('.')}</span>}
                {v.measured !== null && (
                  <span className={`ml-auto tabular-nums ${v.status === 'confirmed' ? 'text-accent' : ''}`}>
                    {withUnit(v.measured, v.measured_unit)}
                  </span>
                )}
              </span>
            </button>
          </li>
        )
      })}
    </ol>
  )
}

// ---- page ------------------------------------------------------------------------------

export function StoryPage() {
  const { id = '' } = useParams()
  const job = useQuery(jobOptions(id))
  const done = job.data?.status === 'done'
  const result = useQuery(resultOptions(id, done))
  const tables = useQuery(tablesOptions(id, done))
  const reduce = useReducedMotion()

  const rows = useMemo(() => result.data?.verification ?? [], [result.data])
  const confirmed = useMemo(() => rows.filter((v) => v.status === 'confirmed'), [rows])
  const [picked, setPicked] = useState<string | null>(null)
  // default: the first confirmed event (else the first one)
  const first = confirmed[0] ?? rows[0]
  const activeKey = picked ?? (first ? rowKey(first) : null)
  const activeRow = rows.find((v) => rowKey(v) === activeKey)
  const tableList = tables.data?.tables
  const target = useMemo(() => {
    const c = activeRow && tableList ? kpiColumn(activeRow.kpi, tableList) : undefined
    return c ? { table: c[0], column: c[1] } : null
  }, [activeRow, tableList])

  const [span, setSpan] = useState<HTMLSpanElement | null>(null) // callback ref: re-render once it exists
  const [flowBox, setFlowBox] = useState<HTMLDivElement | null>(null)

  // steps reveal (anime.js); reduced motion: no movement, instant
  const root = useRef<HTMLDivElement>(null)
  const scope = useRef<Scope | null>(null)
  const ready = Boolean(rows.length && tableList)
  useEffect(() => {
    if (!ready) return
    scope.current = createScope({ root, mediaQueries: { reduce: REDUCE } }).add((self) => {
      const r = self?.matches.reduce
      const d = (ms: number) => (r ? 0 : ms)
      createTimeline({ defaults: { ease: 'outExpo' } })
        .add('.reveal', { opacity: [0, 1], y: r ? 0 : [10, 0], duration: d(600), delay: stagger(d(120)) })
        .add('.step', { opacity: [0, 1], x: r ? 0 : [-14, 0], duration: d(500), delay: stagger(d(110)) }, '-=300')
        .add('.chart', { opacity: [0, 1], y: r ? 0 : [16, 0], duration: d(600), delay: stagger(d(150)) }, '-=200')
    })
    return () => scope.current?.revert()
  }, [ready])

  const error = job.error ?? result.error ?? tables.error
  if (error)
    return (
      <div className="grid gap-4">
        <Alert>{error.message}</Alert>
        <Link to={`/jobs/${id}`} className="text-accent hover:underline">
          ← Zpět na úlohu
        </Link>
      </div>
    )
  if (job.data && !done)
    return (
      <div className="grid gap-4">
        <Alert t="amber">Úloha ještě neskončila, příběh v datech zatím není k dispozici.</Alert>
        <Link to={`/jobs/${id}`} className="text-accent hover:underline">
          ← Zpět na úlohu
        </Link>
      </div>
    )
  if (!result.data || !tableList)
    return (
      <p className="text-muted">
        <Spinner /> Načítám příběh…
      </p>
    )

  const r = result.data
  return (
    <div ref={root} className="grid gap-5">
      <div className="reveal flex flex-wrap items-end gap-3 opacity-0">
        <div className="mr-auto min-w-0">
          <Link to={`/jobs/${id}`} className="text-sm text-muted hover:text-white">
            ← Zpět na úlohu
          </Link>
          <h1 className="text-xl font-semibold sm:text-2xl">Příběh v datech</h1>
          <p className="text-sm text-muted">
            {tableList.length} tabulek · příběh {r.summary.story} potvrzeno · dvojče {r.summary.twin}
          </p>
        </div>
        <Link
          to={`/jobs/${id}/data`}
          className="rounded-lg border border-line px-3 py-2 text-sm hover:border-accent/60"
        >
          ▦ Data a SQL
        </Link>
      </div>

      <ReactFlowProvider>
        <div className="reveal grid overflow-hidden rounded-xl border border-line opacity-0 lg:h-[640px] lg:grid-cols-[22rem_1fr]">
          <aside data-scroll className="max-h-[640px] overflow-y-auto border-b border-line bg-panel p-4 lg:border-b-0 lg:border-r">
            {r.narrative && (
              <blockquote className="mb-4 border-l-2 border-accent/60 pl-3 text-sm leading-relaxed text-slate-300">
                {r.narrative.text}
              </blockquote>
            )}
            <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Události</h2>
            <Steps rows={rows} tables={tableList} active={activeKey} onPick={setPicked} spanRef={setSpan} />
            {r.untested.length > 0 && (
              <p className="mt-3 text-xs text-muted">
                Neověřeno: {r.untested.map((u) => u.event_id).join(', ')} (simulátor tyto události nepodporuje).
              </p>
            )}
          </aside>
          <div className="h-[520px] bg-bg lg:h-auto">
            <Erd tables={tableList} active={target} onBox={setFlowBox}>
              {target && (
                <SpanArrow from={span} table={target.table} column={target.column} flowBox={flowBox} reduce={reduce} />
              )}
            </Erd>
          </div>
        </div>
      </ReactFlowProvider>

      <section className="grid gap-3">
        <h2 className="reveal text-lg font-semibold opacity-0">Potvrzené události den po dni</h2>
        {confirmed.length === 0 ? (
          <p className="text-muted">Žádná událost se v datech nepotvrdila.</p>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {confirmed.map((v) => (
              <div key={rowKey(v)} className="chart opacity-0">
                <KpiChart jobId={id} v={v} />
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
