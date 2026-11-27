// Shrnutí of Rev story: what the blind detective told next to what the story planted. Left the
// detective's narrative and its finds, right the original prompt and the planted events (from
// /answer-key; the verification rows if this user may not see it). A matched pair (match.ts, the
// pairing behind the API's P/R/F1) is linked by an arrow found → planted; a planted event nobody
// found is marked "nenalezeno", a find that is no planted event "falešný nález", a find that
// follows from a found one "důsledek". Arrows: an SVG inside the section (container pixels),
// drawn in one by one with anime.js when it scrolls into view. Lazy chunk (anime.js).
import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createScope, createTimeline, onScroll, stagger, svg, utils } from 'animejs'
import { answerKeyOptions, isStatus, type DetectEvent, type JobInput, type PlantedEvent, type VerificationRow } from '../api'
import { Badge } from '../components/ui'
import { KIND_CS, METRIC_CS, dateCs, num, signed } from '../format'
import { matchEvents, type Matching } from './match'
import type { Run } from './useRun'

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

const metricCs = (m: string) => METRIC_CS[m] ?? m
const arrow = (d: string) => (d === 'up' ? '↑' : d === 'down' ? '↓' : '·')
const pct = (n: number | null) => (n === null ? '' : `${signed(n)} %`)

/** Without the answer key (a student): the planted events from the verification rows, one per row. */
function fromVerification(rows: VerificationRow[]): PlantedEvent[] {
  return rows.map((v) => ({
    event_id: v.event_id,
    type: '',
    metric: v.metric,
    segment: v.target || null,
    start_date: v.start,
    lag_days: 0,
    magnitude_pct: v.story_unit === '%' ? v.story_size : null,
    direction: v.direction,
    caused_by: null,
    simulated: v.status !== 'not_testable',
    narrative_cs: v.claim_cs,
  }))
}

// ---- cards -------------------------------------------------------------------------------

type Tag = { text: string; t: 'green' | 'red' | 'amber' | 'gray' }

function Card({
  side,
  id,
  head,
  body,
  meta,
  tag,
  pairId,
  hover,
  setHover,
  dashed,
}: {
  side: 'found' | 'planted'
  id: string
  head: ReactNode
  body?: ReactNode
  meta: ReactNode
  tag: Tag
  pairId: string | null
  hover: string | null
  setHover: (k: string | null) => void
  dashed?: boolean
}) {
  const on = pairId !== null && hover === pairId
  const dim = hover !== null && !on
  return (
    <li
      data-rev={`${side}:${id}`}
      tabIndex={pairId ? 0 : undefined}
      onMouseEnter={() => pairId && setHover(pairId)}
      onMouseLeave={() => setHover(null)}
      onFocus={() => pairId && setHover(pairId)}
      onBlur={() => setHover(null)}
      className={`grid gap-1 border-l-2 py-1 pl-3 text-sm transition-[opacity,border-color,background-color] duration-300 ${
        on ? 'border-accent bg-accent/[0.04]' : dashed ? 'border-dashed border-line' : 'border-line'
      } ${dim ? 'opacity-45' : ''}`}
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="font-mono text-xs text-accent">{id}</span>
        <span className="min-w-0 flex-1">{head}</span>
        <Badge t={tag.t}>{tag.text}</Badge>
      </div>
      {body && <div className="text-slate-300">{body}</div>}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted">{meta}</div>
    </li>
  )
}

function FoundCard({ e, m, hover, setHover }: { e: DetectEvent; m: Matching; hover: string | null; setHover: (k: string | null) => void }) {
  const pair = m.pairs.find((p) => p.found.id === e.id)
  const cons = m.consequences.find((c) => c.found.id === e.id)
  const ff = m.falseFinds.find((f) => f.found.id === e.id)
  const tag: Tag = pair
    ? { text: `= ${pair.planted.event_id}`, t: 'green' }
    : cons
      ? { text: `důsledek ${cons.of}`, t: 'gray' }
      : { text: ff?.decoy ? `falešný nález (návnada)` : 'falešný nález', t: 'red' }
  return (
    <Card
      side="found"
      id={e.id}
      pairId={pair ? pair.planted.event_id : null}
      hover={hover}
      setHover={setHover}
      tag={tag}
      dashed={!pair}
      head={
        <>
          {metricCs(e.metric)} <span className={e.direction === 'down' ? 'text-rose-300' : 'text-emerald-300'}>{arrow(e.direction)}</span>{' '}
          <span className="tabular-nums text-slate-300">{pct(e.magnitude_pct)}</span>
        </>
      }
      meta={
        <>
          <span className="font-mono">{e.segment || 'všichni'}</span>
          <span>
            {KIND_CS[e.kind] ?? e.kind} od {dateCs(e.start_date)}
          </span>
          <span className="tabular-nums" title="jistota detektivu">
            jistota {Math.round(e.confidence * 100)} %
          </span>
          {pair && (
            <span className="tabular-nums" title="shoda podle s2d/score.py: 0,4 čas + 0,4 segment + 0,2 velikost">
              shoda {num(pair.score, 2)}, posun {pair.slots.deltaDays > 0 ? '+' : ''}
              {pair.slots.deltaDays} d
            </span>
          )}
        </>
      }
    />
  )
}

function PlantedCard({ t, m, hover, setHover }: { t: PlantedEvent; m: Matching; hover: string | null; setHover: (k: string | null) => void }) {
  const pair = m.pairs.find((p) => p.planted.event_id === t.event_id)
  const tag: Tag = !t.simulated
    ? { text: 'nesimulováno', t: 'gray' }
    : pair
      ? { text: `nalezeno ${pair.found.id}`, t: 'green' }
      : { text: 'nenalezeno', t: 'amber' }
  return (
    <Card
      side="planted"
      id={t.event_id}
      pairId={pair ? t.event_id : null}
      hover={hover}
      setHover={setHover}
      tag={tag}
      dashed={!pair}
      head={t.narrative_cs || metricCs(t.metric)}
      meta={
        <>
          <span>
            {metricCs(t.metric)} {arrow(t.direction)} {pct(t.magnitude_pct)}
          </span>
          <span className="font-mono">{t.segment || 'všichni'}</span>
          <span>
            od {dateCs(t.start_date)}
            {t.lag_days ? `, se zpožděním ${t.lag_days} d` : ''}
          </span>
        </>
      }
    />
  )
}

// ---- the arrows (container pixels) ---------------------------------------------------------

type Path = { key: string; d: string; x2: number; y2: number }

function geometry(root: HTMLElement, m: Matching): Path[] {
  const r = root.getBoundingClientRect()
  const out: Path[] = []
  for (const p of m.pairs) {
    const a = root.querySelector<HTMLElement>(`[data-rev="found:${CSS.escape(p.found.id)}"]`)?.getBoundingClientRect()
    const b = root.querySelector<HTMLElement>(`[data-rev="planted:${CSS.escape(p.planted.event_id)}"]`)?.getBoundingClientRect()
    if (!a || !b) continue
    const x1 = a.right - r.left + 3
    const y1 = a.top - r.top + Math.min(20, a.height / 2)
    const x2 = b.left - r.left - 5
    const y2 = b.top - r.top + Math.min(20, b.height / 2)
    const dx = Math.max(24, (x2 - x1) * 0.5)
    out.push({ key: p.planted.event_id, x2, y2, d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}` })
  }
  return out
}

function Arrows({ root, m, hover, reduce }: { root: HTMLElement; m: Matching; hover: string | null; reduce: boolean }) {
  const [paths, setPaths] = useState<Path[]>(() => geometry(root, m))
  useLayoutEffect(() => {
    let raf = 0
    const update = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => setPaths(geometry(root, m)))
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(root)
    root.querySelectorAll('[data-rev]').forEach((el) => ro.observe(el))
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [root, m])

  const ref = useRef<SVGSVGElement>(null)
  const n = paths.length
  useEffect(() => {
    if (reduce || !n || !ref.current) return
    const el = ref.current
    const scope = createScope().add(() => {
      const lines = svg.createDrawable(el.querySelectorAll<SVGPathElement>('path.arrow'))
      const heads = el.querySelectorAll('.head')
      utils.set(lines, { draw: '0 0' })
      utils.set(heads, { opacity: 0 })
      createTimeline({ autoplay: onScroll({ target: root, enter: 'bottom-=20% top' }) })
        .add(lines, { draw: ['0 0', '0 1'], duration: 600, delay: stagger(220), ease: 'inOutQuad' })
        .add(heads, { opacity: [0, 1], duration: 200, delay: stagger(220) }, 400)
    })
    return () => scope.revert()
  }, [n, reduce, root])

  return (
    <svg ref={ref} className="pointer-events-none absolute inset-0 h-full w-full overflow-visible" aria-hidden>
      {paths.map((p) => {
        const on = hover === p.key
        return (
          <g key={p.key} style={{ opacity: hover === null ? 0.75 : on ? 1 : 0.12, transition: 'opacity 250ms' }}>
            <path className="arrow" d={p.d} fill="none" stroke="var(--color-accent)" strokeWidth={on ? 2.2 : 1.5} strokeLinecap="round" />
            <circle className="head" cx={p.x2} cy={p.y2} r={on ? 4.5 : 3.5} fill="var(--color-accent)" />
          </g>
        )
      })}
    </svg>
  )
}

// ---- the section -------------------------------------------------------------------------

function Prompt({ input }: { input: JobInput | undefined }) {
  if (!input) return <p className="text-sm text-muted">Načítám zadání…</p>
  if (input.spec_given) return <p className="text-sm text-muted">Běh vznikl z hotové specifikace, bez textového zadání; události jsou dole.</p>
  return (
    <div className="grid gap-2 border-l-2 border-line py-1 pl-3 text-sm leading-relaxed">
      {input.company && input.company !== input.story && <p className="text-xs text-muted">{input.company}</p>}
      <p className="whitespace-pre-line text-slate-200">{input.story}</p>
    </div>
  )
}

function Verdict({ m, nFound, server }: { m: Matching; nFound: number; server: Run['detect'] }) {
  const n = m.pairs.length + m.missed.length
  const s = server?.score
  return (
    <div className="grid gap-1">
      <p className="text-base font-medium sm:text-lg">
        Detektiv naslepo našel <b className="text-accent tabular-nums">{m.pairs.length}</b> z <b className="tabular-nums">{n}</b>{' '}
        zasazených událostí
        {m.falseFinds.length > 0 && (
          <>
            , <b className="tabular-nums text-rose-300">{m.falseFinds.length}</b> {m.falseFinds.length === 1 ? 'falešný nález' : 'falešné nálezy'}
          </>
        )}
        {m.consequences.length > 0 && (
          <>
            , <b className="tabular-nums">{m.consequences.length}</b> {m.consequences.length === 1 ? 'důsledek' : 'důsledky'}
          </>
        )}
        .
      </p>
      <p className="text-xs text-muted">
        {nFound} {nFound === 1 ? 'nález' : nFound < 5 && nFound > 1 ? 'nálezy' : 'nálezů'}; pár se počítá od shody 0,5 (čas, segment, velikost), stejně jako
        skóre na serveru
        {s && (
          <>
            {' '}
            (přesnost {num(s.precision, 2)}, úplnost {num(s.recall, 2)}, F1 {num(s.f1, 2)})
          </>
        )}
        .
      </p>
    </div>
  )
}

export default function RevSummary({ run }: { run: Run }) {
  const id = run.id!
  const d = run.detect!
  const key = useQuery(answerKeyOptions(id, true))
  const forbidden = isStatus(key.error, 403) || isStatus(key.error, 401)
  const planted = useMemo(
    () => (key.data ? key.data.answer_key : forbidden && run.result ? fromVerification(uniqueEvents(run.result.verification)) : null),
    [key.data, forbidden, run.result],
  )
  const found = useMemo(() => d.events ?? [], [d.events])
  const m = useMemo(() => (planted ? matchEvents(found, planted, key.data?.decoys ?? []) : null), [found, planted, key.data])
  const [hover, setHover] = useState<string | null>(null)
  const [root, setRoot] = useState<HTMLDivElement | null>(null)
  const wide = useMedia('(min-width: 1024px)')
  const reduce = useMedia('(prefers-reduced-motion: reduce)')

  if (key.error && !forbidden) return <p className="text-sm text-rose-200">{key.error.message}</p>
  if (!m || !planted) return <p className="text-sm text-muted">Načítám zasazené události…</p>

  // found: pairs first in planted order, then consequences, then false finds; planted in story order
  const order = new Map(planted.map((t, i) => [t.event_id, i]))
  const foundSorted = [...found].sort((a, b) => rank(a) - rank(b))
  function rank(e: DetectEvent) {
    const p = m!.pairs.find((x) => x.found.id === e.id)
    if (p) return order.get(p.planted.event_id) ?? 0
    return m!.consequences.some((c) => c.found.id === e.id) ? 1000 : 2000
  }

  return (
    <div className="grid gap-4">
      <Verdict m={m} nFound={found.length} server={d} />
      <div ref={setRoot} className="relative grid gap-6 lg:grid-cols-2 lg:gap-x-20">
        <div className="grid content-start gap-3">
          <h3 className="text-xs text-muted">Detektiv, bez znalosti příběhu</h3>
          {d.narrative?.text ? (
            <blockquote className="border-l-2 border-line py-1 pl-3 text-sm leading-relaxed whitespace-pre-line text-slate-200">
              {d.narrative.text}
              {d.narrative.source && <footer className="mt-2 text-xs text-slate-500">{d.narrative.source}</footer>}
            </blockquote>
          ) : (
            <p className="text-sm text-muted">Detektiv nenapsal žádný příběh.</p>
          )}
          {found.length ? (
            <ul className="grid gap-1.5">
              {foundSorted.map((e) => (
                <FoundCard key={e.id} e={e} m={m} hover={hover} setHover={setHover} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Detektiv v datech nic nenašel.</p>
          )}
        </div>
        <div className="grid content-start gap-3">
          <h3 className="text-xs text-muted">Původní zadání a zasazené události</h3>
          <Prompt input={run.input} />
          {forbidden && <p className="text-[11px] text-slate-500">Klíč s odpověďmi vidí jen učitel; události jsou z ověřovací tabulky.</p>}
          <ul className="grid gap-1.5">
            {planted.map((t) => (
              <PlantedCard key={t.event_id} t={t} m={m} hover={hover} setHover={setHover} />
            ))}
          </ul>
        </div>
        {wide && root && m.pairs.length > 0 && <Arrows root={root} m={m} hover={hover} reduce={reduce} />}
      </div>
    </div>
  )
}

function uniqueEvents(rows: VerificationRow[]): VerificationRow[] {
  const seen = new Set<string>()
  return rows.filter((v) => (seen.has(v.event_id) ? false : (seen.add(v.event_id), true)))
}
