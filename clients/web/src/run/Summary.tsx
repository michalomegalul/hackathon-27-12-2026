// Shrnutí, the end of the run page and the demo's money shot: the prompt as sent with each
// event's phrase highlighted, and from each highlight an arrow to (a) its chart, the story
// against the twin without it, and (b) its Postgres card, the table and column it changed with
// the before/after numbers and the SQL that proves it. Arrows: a fixed SVG overlay in screen
// pixels (the SpanArrow recipe of docs/research/web-stack.md, DOM to DOM), drawn in one by one
// with anime.js when the section scrolls into view. Lazy chunk (uPlot, anime.js).
import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { createScope, createTimeline, onScroll, stagger, svg, utils } from 'animejs'
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

// ---- media queries ---------------------------------------------------------------------

function useMedia(q: string) {
  return useSyncExternalStore(
    (cb) => {
      const m = matchMedia(q)
      m.addEventListener('change', cb)
      return () => m.removeEventListener('change', cb)
    },
    () => matchMedia(q).matches,
  )
}
const REDUCE = '(prefers-reduced-motion: reduce)'
const WIDE = '(min-width: 1024px)' // lg: prompt beside the blocks, arrows on

// ---- the verdict -----------------------------------------------------------------------

function Verdict({ r, run, spec }: { r: JobResult; run: Run; spec: Spec | null }) {
  const score = run.detect?.score
  const n = spec?.events.length ?? new Set(r.verification.map((v) => v.event_id)).size
  const found = score && n ? Math.round(score.recall * n) : null
  return (
    <p className="text-base font-medium sm:text-lg">
      Příběh <b className="text-accent tabular-nums">{r.summary.story}</b> potvrzeno, dvojče{' '}
      <b className={`tabular-nums ${r.summary.twin.startsWith('0/') ? 'text-accent' : 'text-amber-300'}`}>{r.summary.twin}</b> falešných
      poplachů
      {found !== null && (
        <>
          , detektiv našel{' '}
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

function HighlightedPrompt({
  input,
  rows,
  hover,
  setHover,
}: {
  input: JobInput
  rows: VerificationRow[]
  hover: string | null
  setHover: (e: string | null) => void
}) {
  const text = input.story ?? ''
  const h = useMemo(() => findHighlights(text, rows), [text, rows])
  const parts: ReactNode[] = []
  let at = 0
  for (const s of h.spans) {
    if (s.start > at) parts.push(text.slice(at, s.start))
    const ev = s.events[0]
    const on = hover === ev
    parts.push(
      <mark
        key={s.start}
        data-hl={ev}
        tabIndex={0}
        onMouseEnter={() => setHover(ev)}
        onMouseLeave={() => setHover(null)}
        onFocus={() => setHover(ev)}
        onBlur={() => setHover(null)}
        className={`mx-px cursor-default rounded-t-[3px] border-b-2 px-0.5 text-inherit transition-colors duration-200 [box-decoration-break:clone] ${
          on ? 'border-accent bg-accent/30 text-white' : 'border-accent/45 bg-accent/[0.09] hover:bg-accent/20'
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
        <p className="text-[15px] leading-7 whitespace-pre-line text-slate-200">{parts}</p>
      ) : (
        <p className="text-sm text-muted">Běh vznikl z hotové specifikace, bez textového zadání. Události:</p>
      )}
      {(h.unmatched.length > 0 || !text) && (
        <ul className="flex flex-wrap gap-1.5">
          {(text ? h.unmatched : [...claims.keys()]).map((ev) => (
            <li key={ev}>
              <span
                data-hl={ev}
                tabIndex={0}
                onMouseEnter={() => setHover(ev)}
                onMouseLeave={() => setHover(null)}
                className={`inline-flex items-baseline gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
                  hover === ev ? 'border-accent/60 bg-accent/20 text-white' : 'border-line bg-bg/60 text-slate-300'
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
        <p className="text-[11px] text-slate-500">Tyto události AI v textu odvodila, ale žádná věta jim přesně neodpovídá.</p>
      )}
    </div>
  )
}

// ---- the Postgres card of one row ------------------------------------------------------

/** "-- before 2026-03-04 .. 2026-03-31, after 2026-04-01 .. 2026-04-28" in the row's SQL. */
function windows(sql: string | null): string | null {
  const m = /--\s*before (\S+) \.\. (\S+), after (\S+) \.\. (\S+)/.exec(sql ?? '')
  return m ? `před ${dateCs(m[1])} – ${dateCs(m[2])}, po ${dateCs(m[3])} – ${dateCs(m[4])}` : null
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
    ['příběh', n(s.treated_before), n(s.treated_after), n(s.treated_change_pct), v.measured],
    [
      'dvojče',
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
            <th className="px-2 text-left font-normal">svět</th>
            <th className={`${td} font-normal`}>před</th>
            <th className={`${td} font-normal`}>po</th>
            <th className={`${td} font-normal`}>změna</th>
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
      {twin.isPending && <p className="px-2 text-[11px] text-muted">dvojče se počítá…</p>}
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
      className={`grid min-w-0 gap-2.5 rounded-lg border bg-bg/50 p-3 transition-colors duration-300 ${lit ? 'border-accent/50' : 'border-line'}`}
    >
      <header className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
        <span className="text-muted">Postgres</span>
        {col ? (
          <span className="font-mono text-sm">
            <span className="text-slate-500">public.</span>
            {col[0]}.<span className={lit ? 'text-accent' : 'text-slate-100'}>{col[1]}</span>
          </span>
        ) : (
          <span className="text-muted">tabulka se nedá určit</span>
        )}
        {win && <span className="ml-auto text-[11px] text-slate-500">{win}</span>}
      </header>
      {t && col && <PsqlTable id={jobId} t={t} lit={lit ? col[1] : undefined} rows={3} only={cardColumns(t, col[1])} />}
      <div className="grid gap-1">
        <span className="text-[11px] text-muted">
          {KPI_CS[v.kpi] ?? v.kpi} za den, průměr 4 týdnů před a po události; {v.target ? <span className="font-mono">{v.target}</span> : 'všichni'}
        </span>
        <BeforeAfter jobId={jobId} v={v} />
      </div>
      {v.sql && (
        <div className="grid gap-1.5">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <button onClick={() => setSqlOpen((o) => !o)} aria-expanded={sqlOpen} className="text-muted hover:text-white">
              {sqlOpen ? '▾' : '▸'} SQL, které to dokazuje
            </button>
            <CopyButton text={v.sql} label="Kopírovat SQL" />
            <Link
              to={`/run/${jobId}/data`}
              state={{ sql: v.sql, label: `${v.event_id} · ${KPI_CS[v.kpi] ?? v.kpi}`, expect: v.sql_result }}
              className="text-accent hover:underline"
            >
              Spustit ↗
            </Link>
          </div>
          {sqlOpen && <SqlBlock sql={v.sql} maxH="max-h-80" title={`${v.event_id}: did_pct = ${num(v.measured, 2)}`} />}
        </div>
      )}
    </div>
  )
}

// ---- one block per verification row -----------------------------------------------------

function Block({
  jobId,
  v,
  tables,
  hover,
  setHover,
}: {
  jobId: string
  v: VerificationRow
  tables: TableInfo[]
  hover: string | null
  setHover: (e: string | null) => void
}) {
  const on = hover === v.event_id
  const dim = hover !== null && !on
  return (
    <article
      onMouseEnter={() => setHover(v.event_id)}
      onMouseLeave={() => setHover(null)}
      className={`grid min-w-0 gap-3 rounded-xl border p-3 transition-[opacity,border-color] duration-300 sm:p-4 ${
        on ? 'border-accent/40 bg-accent/[0.03]' : 'border-line'
      } ${dim ? 'opacity-45' : ''}`}
    >
      <header className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 text-sm">
        <span className="font-mono text-xs text-accent">{v.event_id}</span>
        <span className="min-w-0 flex-1">{v.claim_cs}</span>
        <VerificationBadge s={v.status} />
      </header>
      <figure data-target={`${rowKey(v)}:chart`} className="grid gap-1.5 rounded-lg border border-line bg-[#181b1f] p-2.5">
        <figcaption className="flex flex-wrap items-baseline gap-x-3 text-xs">
          <span className="font-medium text-slate-200">{KPI_CS[v.kpi] ?? v.kpi}</span>
          <span className="font-mono text-muted">{v.target || 'všichni'}</span>
          <span className="ml-auto text-muted">
            <span className="mr-1 inline-block h-0.5 w-3 bg-[#73bf69] align-middle" /> příběh
            <span className="mr-1 ml-3 inline-block h-0 w-3 border-t-2 border-dashed border-[#b8c0cc] align-middle" /> dvojče
            {v.control_mode !== 'none' && (
              <>
                <span className="mr-1 ml-3 inline-block h-0.5 w-3 bg-[#8ab8ff]/60 align-middle" /> kontrola
              </>
            )}
          </span>
        </figcaption>
        <KpiChart jobId={jobId} v={v} height={180} />
      </figure>
      <PgCard jobId={jobId} v={v} tables={tables} lit={on} />
    </article>
  )
}

// ---- the arrows --------------------------------------------------------------------------

type Path = { key: string; ev: string; d: string; x2: number; y2: number; off: boolean }
type Band = { left: number; top: number; width: number; height: number }

/**
 * From the highlight's last line box (right edge) to the target's left edge, near its top.
 * The band is the summary's part of the screen between the sticky header and the chat input;
 * an arrow whose target is outside it is hidden (it would only point off-screen).
 */
function geometry(root: HTMLElement): { paths: Path[]; band: Band } {
  const r = root.getBoundingClientRect()
  const head = document.querySelector('[data-chrome="top"]')?.getBoundingClientRect().bottom ?? 0
  const input = document.querySelector('[data-chrome="bottom"]')?.getBoundingClientRect().top ?? innerHeight
  const top = Math.max(r.top, head)
  const bottom = Math.min(r.bottom, innerHeight, input)
  const band = { left: r.left - 8, top, width: r.width + 16, height: Math.max(0, bottom - top) }
  const paths: Path[] = []
  for (const tgt of root.querySelectorAll<HTMLElement>('[data-target]')) {
    const [key, kind] = tgt.dataset.target!.split(':')
    const ev = key.split('·')[0]
    const from = root.querySelector<HTMLElement>(`[data-hl="${CSS.escape(ev)}"]`)
    if (!from) continue
    const rects = from.getClientRects()
    const a = rects[rects.length - 1] ?? from.getBoundingClientRect()
    const b = tgt.getBoundingClientRect()
    const x1 = a.right + 3
    const y1 = a.top + a.height / 2
    const x2 = b.left - 5
    const y2 = b.top + Math.min(26, b.height / 2)
    const dx = Math.max(40, (x2 - x1) * 0.5)
    const off = y2 < top + 4 || y2 > bottom - 4 || y1 < top || y1 > bottom
    paths.push({ key: `${key}:${kind}`, ev, x2, y2, off, d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}` })
  }
  return { paths, band }
}

function Arrows({ root, hover, reduce }: { root: HTMLElement; hover: string | null; reduce: boolean }) {
  const [g, setG] = useState(() => geometry(root))
  // redraw on scroll, resize and any size change inside (charts and cards load late)
  useLayoutEffect(() => {
    let raf = 0
    const update = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => setG(geometry(root)))
    }
    update()
    window.addEventListener('scroll', update, { passive: true, capture: true })
    window.addEventListener('resize', update)
    const ro = new ResizeObserver(update)
    ro.observe(root)
    root.querySelectorAll('[data-target], [data-hl]').forEach((el) => ro.observe(el))
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('scroll', update, { capture: true })
      window.removeEventListener('resize', update)
      ro.disconnect()
    }
  }, [root])

  // draw in one by one when the section scrolls into view; reduced motion: drawn already
  const svgRef = useRef<SVGSVGElement>(null)
  const n = g.paths.length
  useEffect(() => {
    if (reduce || !n || !svgRef.current) return
    const el = svgRef.current
    const scope = createScope().add(() => {
      const lines = svg.createDrawable(el.querySelectorAll<SVGPathElement>('path.arrow'))
      const heads = el.querySelectorAll('.head')
      utils.set(lines, { draw: '0 0' })
      utils.set(heads, { opacity: 0 })
      createTimeline({ autoplay: onScroll({ target: root, enter: 'bottom-=25% top' }) })
        .add(lines, { draw: ['0 0', '0 1'], duration: 650, delay: stagger(260), ease: 'inOutQuad' })
        .add(heads, { opacity: [0, 1], duration: 200, delay: stagger(260) }, 450)
    })
    return () => scope.revert()
  }, [n, reduce, root])

  const c = g.band
  return (
    <svg ref={svgRef} className="pointer-events-none fixed inset-0 z-20 h-full w-full overflow-visible" aria-hidden>
      <defs>
        <clipPath id="summary-clip">
          <rect x={c.left} y={c.top} width={c.width} height={c.height} />
        </clipPath>
      </defs>
      <g clipPath="url(#summary-clip)">
        {g.paths.map((p) => {
          const on = hover === p.ev
          const op = p.off ? 0 : hover === null ? 0.7 : on ? 1 : 0.1
          return (
            <g key={p.key} style={{ opacity: op, transition: 'opacity 250ms' }}>
              <path className="arrow" d={p.d} fill="none" stroke="var(--color-accent)" strokeWidth={on ? 2.2 : 1.5} strokeLinecap="round" />
              <circle className="head" cx={p.x2} cy={p.y2} r={on ? 4.5 : 3.5} fill="var(--color-accent)" />
            </g>
          )
        })}
      </g>
    </svg>
  )
}

// ---- the section's content -------------------------------------------------------------

export default function Summary({ run, spec }: { run: Run; spec: Spec | null }) {
  const r = run.result!
  const id = run.id!
  const tables = useQuery(tablesOptions(id, true))
  const [hover, setHover] = useState<string | null>(null)
  const reduce = useMedia(REDUCE)
  const wide = useMedia(WIDE)
  const [root, setRoot] = useState<HTMLDivElement | null>(null)
  const rows = r.verification
  const ready = Boolean(run.input && tables.data)

  return (
    <div className="grid gap-4">
      <Verdict r={r} run={run} spec={spec} />
      <div ref={setRoot} className="grid gap-4 lg:grid-cols-[minmax(0,19rem)_minmax(0,1fr)] lg:gap-x-16 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="self-start rounded-xl border border-line bg-bg/40 p-4 lg:sticky lg:top-20">
          <h3 className="mb-2 text-xs text-muted">Zadání, jak přišlo</h3>
          {run.input ? (
            <HighlightedPrompt input={run.input} rows={rows} hover={hover} setHover={setHover} />
          ) : (
            <p className="text-sm text-muted">Načítám zadání…</p>
          )}
          {r.narrative?.text && (
            <details className="mt-4 text-sm">
              <summary className="cursor-pointer text-xs text-muted select-none hover:text-white">Příběh, jak ho napsala data</summary>
              <p className="mt-2 leading-relaxed whitespace-pre-line text-slate-300">{r.narrative.text}</p>
            </details>
          )}
        </div>
        <div className="grid min-w-0 content-start gap-4">
          {rows.length === 0 && <p className="text-sm text-muted">Příběh nemá žádnou ověřitelnou událost.</p>}
          {tables.data &&
            rows.map((v) => <Block key={rowKey(v)} jobId={id} v={v} tables={tables.data.tables} hover={hover} setHover={setHover} />)}
          {r.untested.length > 0 && (
            <p className="text-xs text-muted">
              Neověřeno: {r.untested.map((u) => `${u.event_id} (${u.reason})`).join('; ')}.
            </p>
          )}
        </div>
      </div>
      {ready && wide && root && <Arrows root={root} hover={hover} reduce={reduce} />}
    </div>
  )
}
