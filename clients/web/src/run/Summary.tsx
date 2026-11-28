// Summary, the end of the run page and the demo's money shot: the prompt as sent on top with
// each event's phrase highlighted (dim until hovered); clicking a phrase jumps to that event.
// Under the prompt is ONE chart at a time (the story against the twin without it, as big as it
// gets; Previous / Next steps through them) and its Postgres card, the table and column it changed
// with the before/after numbers and the SQL that proves it. Lazy chunk (uPlot).
import { useMemo, useState, type KeyboardEvent, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { sqlOptions, tablesOptions, type Cell, type JobInput, type JobResult, type TableInfo, type VerificationRow } from '../api'
import { CopyButton, SqlBlock } from '../components/Code'
import { VerificationBadge } from '../components/ui'
import { KPI_CS, dateCs, num, signed, withUnit } from '../format'
import type { Spec } from '../spec'
import { KpiChart } from '../story/KpiChart'
import { kpiColumn } from '../story/model'
import '../story/story.css'
import { PsqlTable } from './DataView'
import { findHighlights, rowKey } from './highlight'
import type { Run } from './useRun'

// ---- the verdict -----------------------------------------------------------------------

function Verdict({ r, run, spec }: { r: JobResult; run: Run; spec: Spec | null }) {
  const score = run.detect?.score
  const n = spec?.events.length ?? new Set(r.verification.map((v) => v.event_id)).size
  const found = score && n ? Math.round(score.recall * n) : null
  const twinHit = Number(r.summary.twin.split('/')[0])
  return (
    <p className="text-base font-medium sm:text-lg">
      Story <b className="text-accent tabular-nums">{r.summary.story}</b> confirmed, unidentified events{' '}
      <b className={`tabular-nums ${twinHit === 0 ? 'text-emerald-300' : twinHit === 1 ? 'text-amber-300' : 'text-rose-300'}`}>{twinHit}</b>
      {found !== null && (
        <>
          , the detective found{' '}
          <b className="tabular-nums">
            {found}/{n}
          </b>
        </>
      )}
      .
    </p>
  )
}

// ---- the prompt with highlights ----------------------------------------------------------

export function HighlightedPrompt({
  input,
  rows,
  hover,
  setHover,
  pinned,
  pin,
}: {
  input: JobInput
  rows: VerificationRow[]
  hover: string | null
  setHover: (e: string | null) => void
  pinned: string | null
  pin: (e: string) => void
}) {
  const act = (ev: string) => ({
    'data-hl': ev,
    tabIndex: 0,
    role: 'button',
    'aria-pressed': pinned === ev,
    onMouseEnter: () => setHover(ev),
    onMouseLeave: () => setHover(null),
    onClick: () => pin(ev),
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        pin(ev)
      }
    },
  })
  const text = input.story ?? ''
  const h = useMemo(() => findHighlights(text, rows), [text, rows])
  const parts: ReactNode[] = []
  let at = 0
  for (const s of h.spans) {
    if (s.start > at) parts.push(text.slice(at, s.start))
    const ev = s.events[0]
    parts.push(
      <mark
        key={s.start}
        {...act(ev)}
        className={`mx-px cursor-pointer border-b-2 px-0.5 transition-colors duration-200 [box-decoration-break:clone] focus:outline-none ${
          pinned === ev
            ? 'border-accent bg-accent/25 text-white'
            : hover === ev
              ? 'border-accent/70 bg-accent/15 text-slate-100'
              : 'border-accent/30 bg-accent/[0.05] text-slate-300'
        }`}
      >
        <sup className="mr-0.5 font-mono text-[9px] text-accent">{ev}</sup>
        {text.slice(s.start, s.end)}
      </mark>,
    )
    at = s.end
  }
  if (at < text.length) parts.push(text.slice(at))

  const claims = new Map(rows.map((v) => [v.event_id, v.claim_cs]))
  return (
    <div className="grid gap-3">
      {input.company && input.company !== input.story && <p className="text-xs leading-relaxed text-muted">{input.company}</p>}
      {text ? (
        <p className="max-w-4xl text-base leading-8 whitespace-pre-line text-slate-500">{parts}</p>
      ) : (
        <p className="text-sm text-muted">This run was made from a ready-made spec, with no prompt text. Events:</p>
      )}
      {(h.unmatched.length > 0 || !text) && (
        <ul className="flex flex-wrap gap-1.5">
          {(text ? h.unmatched : [...claims.keys()]).map((ev) => (
            <li key={ev}>
              <span
                {...act(ev)}
                className={`inline-flex cursor-pointer items-baseline gap-1.5 border-b-2 px-0.5 py-0.5 text-xs transition-colors focus:outline-none ${
                  pinned === ev ? 'border-accent text-white' : hover === ev ? 'border-accent/70 text-slate-100' : 'border-line text-slate-400'
                }`}
              >
                <span className="font-mono text-accent">{ev}</span>
                {claims.get(ev)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {text && h.unmatched.length > 0 && (
        <p className="text-[11px] text-slate-500">The LLM derived these events from the text, but no sentence matches them exactly.</p>
      )}
    </div>
  )
}

// ---- the Postgres card of one row ------------------------------------------------------

/** "-- before 2026-03-04 .. 2026-03-31, after 2026-04-01 .. 2026-04-28" in the row's SQL. */
function windows(sql: string | null): string | null {
  const m = /--\s*before (\S+) \.\. (\S+), after (\S+) \.\. (\S+)/.exec(sql ?? '')
  return m ? `before ${dateCs(m[1])} – ${dateCs(m[2])}, after ${dateCs(m[3])} – ${dateCs(m[4])}` : null
}

const at = (cols: { name: string }[], row: Cell[] | undefined, k: string): number | null => {
  const i = cols.findIndex((c) => c.name === k)
  const v = i >= 0 ? row?.[i] : undefined
  return typeof v === 'number' ? v : null
}

function BeforeAfter({ jobId, v }: { jobId: string; v: VerificationRow }) {
  const twin = useQuery(sqlOptions(jobId, v.sql ?? undefined, 'twin'))
  const s = v.sql_result ?? {}
  const n = (x: unknown) => (typeof x === 'number' ? x : null)
  const tw = twin.data
  const rows: [string, number | null, number | null, number | null, number | null][] = [
    ['story', n(s.treated_before), n(s.treated_after), n(s.treated_change_pct), v.measured],
    [
      'twin',
      tw ? at(tw.columns, tw.rows[0], 'treated_before') : null,
      tw ? at(tw.columns, tw.rows[0], 'treated_after') : null,
      tw ? at(tw.columns, tw.rows[0], 'treated_change_pct') : null,
      tw ? (at(tw.columns, tw.rows[0], 'did_pct') ?? v.twin_measured) : v.twin_measured,
    ],
  ]
  const td = 'border-l border-line/70 px-2 text-right tabular-nums'
  return (
    <div className="overflow-x-auto">
      <table className="font-mono text-[11px] leading-[18px] whitespace-nowrap">
        <thead>
          <tr className="border-b border-line text-muted">
            <th className="px-2 text-left font-normal">world</th>
            <th className={`${td} font-normal`}>before</th>
            <th className={`${td} font-normal`}>po</th>
            <th className={`${td} font-normal`}>change</th>
            <th className={`${td} font-normal`}>proti kontrole</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([w, b, a, ch, did], i) => (
            <tr key={w} className={i === 0 ? 'text-slate-100' : 'text-slate-400'}>
              <td className="px-2">{w}</td>
              <td className={td}>{num(b, 2)}</td>
              <td className={td}>{num(a, 2)}</td>
              <td className={td}>{ch === null ? '–' : `${signed(ch)} %`}</td>
              <td className={`${td} ${i === 0 && v.confirmed ? 'font-semibold text-accent' : ''}`}>{withUnit(did, v.measured_unit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {twin.isPending && <p className="px-2 text-[11px] text-muted">computing the twin…</p>}
    </div>
  )
}

/** The key, the first date and the changed column (and a target column like city), at most 5. */
function cardColumns(t: TableInfo, changed: string): string[] {
  const out = new Set<string>(t.primary_key ?? [])
  const date = t.columns.find((c) => /DATE|TIMESTAMP/i.test(c.type))
  if (date) out.add(date.name)
  for (const c of ['city', 'segment', 'courier', 'category']) if (t.columns.some((x) => x.name === c)) out.add(c)
  out.delete(changed)
  return [...[...out].slice(0, 4), changed]
}

function PgCard({ jobId, v, tables, lit }: { jobId: string; v: VerificationRow; tables: TableInfo[]; lit: boolean }) {
  const col = kpiColumn(v.kpi, tables)
  const t = col ? tables.find((x) => x.name === col[0]) : undefined
  const [sqlOpen, setSqlOpen] = useState(false)
  const win = windows(v.sql)
  return (
    <div
      data-target={`${rowKey(v)}:pg`}
      className={`grid min-w-0 max-w-3xl gap-2.5 border-l-2 py-1 pl-3 transition-colors duration-300 ${lit ? 'border-accent' : 'border-line'}`}
    >
      <header className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
        <span className="text-muted">Postgres</span>
        {col ? (
          <span className="font-mono text-sm">
            <span className="text-slate-500">public.</span>
            {col[0]}.<span className={lit ? 'text-accent' : 'text-slate-100'}>{col[1]}</span>
          </span>
        ) : (
          <span className="text-muted">table cannot be determined</span>
        )}
        {win && <span className="ml-auto text-[11px] text-slate-500">{win}</span>}
      </header>
      {t && col && <PsqlTable id={jobId} t={t} lit={lit ? col[1] : undefined} rows={3} only={cardColumns(t, col[1])} />}
      <div className="grid gap-1">
        <span className="text-[11px] text-muted">
          {KPI_CS[v.kpi] ?? v.kpi} per day, 4-week mean before and after the event; {v.target ? <span className="font-mono">{v.target}</span> : 'everyone'}
        </span>
        <BeforeAfter jobId={jobId} v={v} />
      </div>
      {v.sql && (
        <div className="grid gap-1.5">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <button onClick={() => setSqlOpen((o) => !o)} aria-expanded={sqlOpen} className="text-muted hover:text-white">
              {sqlOpen ? '▾' : '▸'} the SQL that proves it
            </button>
            <CopyButton text={v.sql} label="Copy SQL" />
            <Link
              to={`/run/${jobId}/data`}
              state={{ sql: v.sql, label: `${v.event_id} · ${KPI_CS[v.kpi] ?? v.kpi}`, expect: v.sql_result }}
              className="text-accent hover:underline"
            >
              Run ↗
            </Link>
          </div>
          {sqlOpen && <SqlBlock sql={v.sql} maxH="max-h-80" title={`${v.event_id}: did_pct = ${num(v.measured, 2)}`} />}
        </div>
      )}
    </div>
  )
}

// ---- one block per verification row -----------------------------------------------------

/** One event: its sentence, the chart (story vs twin) and the Postgres card. `head` replaces the
 *  sentence line (Rev story puts the prompt and the detective's hypothesis there side by side). */
export function Block({
  jobId,
  v,
  tables,
  head,
}: {
  jobId: string
  v: VerificationRow
  tables: TableInfo[]
  head?: ReactNode
}) {
  return (
    <article className="grid min-w-0 gap-4 border-t border-line pt-4">
      {head ?? (
        <header className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 text-sm">
          <span className="font-mono text-xs text-accent">{v.event_id}</span>
          <span className="min-w-0 flex-1">{v.claim_cs}</span>
          <VerificationBadge s={v.status} />
        </header>
      )}
      <figure data-target={`${rowKey(v)}:chart`} className="grid gap-1.5 py-1">
        <figcaption className="flex flex-wrap items-baseline gap-x-3 text-xs">
          <span className="font-medium text-slate-200">{KPI_CS[v.kpi] ?? v.kpi}</span>
          <span className="font-mono text-muted">{v.target || 'everyone'}</span>
          <span className="ml-auto text-muted">
            <span className="mr-1 inline-block h-0.5 w-3 bg-[#ffffff] align-middle" /> story
            <span className="mr-1 ml-3 inline-block h-0 w-3 border-t-2 border-dashed border-[#808080] align-middle" /> twin
            {v.control_mode !== 'none' && (
              <>
                <span className="mr-1 ml-3 inline-block h-0.5 w-3 bg-[#a6a6a6]/60 align-middle" /> kontrola
              </>
            )}
          </span>
        </figcaption>
        <KpiChart jobId={jobId} v={v} height={420} />
      </figure>
      <PgCard jobId={jobId} v={v} tables={tables} lit />
    </article>
  )
}

// ---- the section's content -------------------------------------------------------------

export default function Summary({ run, spec }: { run: Run; spec: Spec | null }) {
  const r = run.result!
  const id = run.id!
  const tables = useQuery(tablesOptions(id, true))
  const rows = r.verification
  const [hover, setHover] = useState<string | null>(null)
  // one chart at a time: the first to start with, then whichever phrase was clicked last or Previous / Next
  const [at, setAt] = useState(0)
  const i = Math.min(at, Math.max(0, rows.length - 1))
  const pinned = rows[i]?.event_id ?? null
  const pin = (ev: string) => setAt(Math.max(0, rows.findIndex((v) => v.event_id === ev)))
  const shown = rows.slice(i, i + 1)
  const step = (d: number) => setAt((i + d + rows.length) % rows.length)
  const btn = 'border border-line px-3 py-1.5 text-sm text-slate-200 hover:border-slate-400 hover:bg-white/5'

  return (
    <div className="grid gap-5">
      <Verdict r={r} run={run} spec={spec} />
      <div className="grid gap-2">
        <h3 className="text-xs text-muted">Prompt as sent · click a highlighted phrase to jump to its chart</h3>
        {run.input ? (
          <HighlightedPrompt input={run.input} rows={rows} hover={hover} setHover={setHover} pinned={pinned} pin={pin} />
        ) : (
          <p className="text-sm text-muted">Loading the prompt…</p>
        )}
        {r.narrative?.text && (
          <details className="mt-2 text-sm">
            <summary className="cursor-pointer text-xs text-muted select-none hover:text-white">Story as written in the data</summary>
            <p className="mt-2 max-w-4xl leading-relaxed whitespace-pre-line text-slate-300">{r.narrative.text}</p>
          </details>
        )}
      </div>
      <div className="grid min-w-0 content-start gap-4">
        {rows.length === 0 && <p className="text-sm text-muted">The story has no verifiable event.</p>}
        {rows.length > 1 && (
          <nav aria-label="Charts" className="flex items-center gap-3">
            <button onClick={() => step(-1)} className={btn}>
              ← Previous
            </button>
            <span className="text-sm tabular-nums text-muted">
              {i + 1} / {rows.length}
            </span>
            <button onClick={() => step(1)} className={btn}>
              Next →
            </button>
          </nav>
        )}
        {tables.data && shown.map((v) => <Block key={rowKey(v)} jobId={id} v={v} tables={tables.data.tables} />)}
        {r.untested.length > 0 && (
          <p className="text-xs text-muted">
            Not verified: {r.untested.map((u) => `${u.event_id} (${u.reason})`).join('; ')}.
          </p>
        )}
      </div>
    </div>
  )
}
