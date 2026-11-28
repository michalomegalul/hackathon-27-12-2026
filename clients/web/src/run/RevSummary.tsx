// Summary of Rev story. On top, the prompt that made the data with each planted event highlighted,
// and under it, written the same way, what the detective found that the prompt never told (its
// hypotheses). Clicking either shows ONE event at a time: the prompt's sentence beside the
// detective's blind guess, then the chart (story vs twin) and the Postgres card (Summary.Block; a
// find's chart is the verifier's test of it, Detect.charts). Then every matched pair in a table,
// and, folded, the detective's finds against the planted events: a matched pair (match.ts, the
// pairing behind the API's P/R/F1) is linked by an arrow found → planted; a planted event nobody
// found is marked "not found", a find that is no planted event "false find", a find that follows
// from a found one "consequence". Arrows: an SVG inside the section (container pixels), drawn in
// one by one with anime.js when it scrolls into view. Lazy chunk (anime.js).
import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createScope, createTimeline, onScroll, stagger, svg, utils } from 'animejs'
import { answerKeyOptions, isStatus, tablesOptions, type DetectEvent, type JobInput, type PlantedEvent, type VerificationRow } from '../api'
import { Badge } from '../components/ui'
import { KIND_CS, METRIC_CS, dateCs, num, signed } from '../format'
import { fromServer, matchEvents, type Matching } from './match'
import { Block, HighlightedPrompt } from './Summary'
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
  const bg = m.background.find((b) => b.found.id === e.id)
  const tag: Tag = pair
    ? { text: `= ${pair.planted.event_id}`, t: 'green' }
    : cons
      ? { text: `consequence of ${cons.of}`, t: 'gray' }
      : bg
        ? { text: 'also without the story', t: 'gray' }
        : { text: ff?.decoy ? `false find (decoy)` : 'false find', t: 'red' }
  return (
    <Card
      side="found"
      id={e.id}
      pairId={pair ? pair.planted.event_id : null}
      hover={hover}
      setHover={setHover}
      tag={tag}
      dashed={!pair}
      body={
        e.hypothesis_cs ? (
          <>
            {e.observation_cs && <p className="text-xs text-muted">{e.observation_cs}</p>}
            <p>
              <span className="text-xs text-muted">Hypothesis: </span>
              {e.hypothesis_cs}
            </p>
          </>
        ) : undefined
      }
      head={
        e.kind === 'stockout' ? (
          <>One SKU with no sales ({e.segment})</>
        ) : (
        <>
          {metricCs(e.metric)} <span className={e.direction === 'down' ? 'text-rose-300' : 'text-emerald-300'}>{arrow(e.direction)}</span>{' '}
          <span className="tabular-nums text-slate-300">{pct(e.magnitude_pct)}</span>
        </>
        )
      }
      meta={
        <>
          <span className="font-mono">{e.segment || 'everyone'}</span>
          <span>
            {KIND_CS[e.kind] ?? e.kind} from {dateCs(e.start_date)}
          </span>
          <span className="tabular-nums" title="detective confidence">
            confidence {Math.round(e.confidence * 100)} %
          </span>
          {pair && (
            <span className="tabular-nums" title="match per s2d/score.py: 0.4 time + 0.4 segment + 0.2 size">
              match {num(pair.score, 2)}, offset {pair.slots.deltaDays > 0 ? '+' : ''}
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
    ? { text: 'not simulated', t: 'gray' }
    : pair
      ? { text: `found ${pair.found.id}`, t: 'green' }
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
          <span className="font-mono">{t.segment || 'everyone'}</span>
          <span>
            od {dateCs(t.start_date)}
            {t.lag_days ? `, lag ${t.lag_days} d` : ''}
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

// ---- prompt sentence vs the detective's hypothesis ------------------------------------------

function SideBySide({ m, hover, setHover }: { m: Matching; hover: string | null; setHover: (k: string | null) => void }) {
  const pairs = m.pairs
    .filter((p) => p.planted.narrative_cs || p.found.hypothesis_cs)
    .sort((a, b) => a.planted.event_id.localeCompare(b.planted.event_id, undefined, { numeric: true }))
  if (!pairs.length) return null
  return (
    <section className="grid gap-2">
      <h3 className="text-xs text-muted">What the prompt planted and what the detective guessed, for each event it found</h3>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="w-0 py-1 pr-3 font-normal">Event</th>
              <th className="py-1 pr-4 font-normal">Sentence from the prompt</th>
              <th className="py-1 pr-4 font-normal">Detective's hypothesis</th>
              <th className="w-0 py-1 font-normal whitespace-nowrap">Match</th>
            </tr>
          </thead>
          <tbody>
            {pairs.map((p) => {
              const k = p.planted.event_id
              const on = hover === k
              return (
                <tr
                  key={k}
                  tabIndex={0}
                  onMouseEnter={() => setHover(k)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(k)}
                  onBlur={() => setHover(null)}
                  className={`border-t border-line align-top transition-[opacity,background-color] duration-300 ${on ? 'bg-accent/[0.04]' : ''} ${
                    hover !== null && !on ? 'opacity-45' : ''
                  }`}
                >
                  <td className="py-2 pr-3 font-mono text-xs whitespace-nowrap text-accent">
                    {k} = {p.found.id}
                  </td>
                  <td className="py-2 pr-4 text-slate-200">{p.planted.narrative_cs || metricCs(p.planted.metric)}</td>
                  <td className="py-2 pr-4 text-slate-200">
                    {p.found.hypothesis_cs || <span className="text-muted">{p.found.label_cs || 'no hypothesis (an older run)'}</span>}
                    {p.found.observation_cs && <div className="mt-0.5 text-xs text-muted">{p.found.observation_cs}</div>}
                  </td>
                  <td className="py-2 text-xs whitespace-nowrap text-muted tabular-nums" title="match per s2d/score.py: 0.4 time + 0.4 segment + 0.2 size">
                    {num(p.score, 2)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

// ---- the section -------------------------------------------------------------------------

function Prompt({ input }: { input: JobInput | undefined }) {
  if (!input) return <p className="text-sm text-muted">Loading the prompt…</p>
  if (input.spec_given) return <p className="text-sm text-muted">This run was made from a ready-made spec, with no prompt text; the events are below.</p>
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
        The blind detective found <b className="text-accent tabular-nums">{m.pairs.length}</b> of <b className="tabular-nums">{n}</b>{' '}
        planted events
        {m.falseFinds.length > 0 && (
          <>
            , <b className="tabular-nums text-rose-300">{m.falseFinds.length}</b> {m.falseFinds.length === 1 ? 'false find' : 'false finds'}
          </>
        )}
        {m.consequences.length > 0 && (
          <>
            , <b className="tabular-nums">{m.consequences.length}</b> {m.consequences.length === 1 ? 'consequence' : 'consequences'}
          </>
        )}
        {m.background.length > 0 && (
          <>
            , <b className="tabular-nums">{m.background.length}</b> also in the world without the story
          </>
        )}
        .
      </p>
      <p className="text-xs text-muted">
        {nFound} {nFound === 1 ? 'finding' : 'findings'}; a pair counts from a match of 0.5 (time, segment, size), the same as
        the server-side score
        {s && (
          <>
            {' '}
            (precision {num(s.precision, 2)}, recall {num(s.recall, 2)}, F1 {num(s.f1, 2)}
            {s.f1_cons !== undefined && <>; without consequences and twin finds: precision {num(s.precision_cons ?? 0, 2)}, F1 {num(s.f1_cons, 2)}</>})
          </>
        )}
        .
      </p>
    </div>
  )
}

// ---- the story: the prompt, then what the detective found on top of it ----------------------------

/** A find that is no planted event but reads like one: a false find or a consequence with its
 *  hypothesis (single-SKU stock-outs and finds the twin has too are noise, left out). */
function isExtra(e: DetectEvent, m: Matching) {
  if (m.pairs.some((p) => p.found.id === e.id) || m.background.some((b) => b.found.id === e.id)) return false
  if (m.consequences.some((c) => c.found.id === e.id)) return true
  return e.kind !== 'stockout'
}

function extraTag(e: DetectEvent, m: Matching): Tag {
  const c = m.consequences.find((x) => x.found.id === e.id)
  if (c) return { text: `consequence of ${c.of}`, t: 'gray' }
  return m.falseFinds.find((f) => f.found.id === e.id)?.decoy ? { text: 'decoy', t: 'red' } : { text: 'not in the prompt', t: 'amber' }
}

function ExtraFinds({
  extras,
  hover,
  setHover,
  pinned,
  pin,
}: {
  extras: DetectEvent[]
  hover: string | null
  setHover: (k: string | null) => void
  pinned: string | null
  pin: (k: string) => void
}) {
  if (!extras.length) return null
  return (
    <div className="grid gap-1.5">
      <h3 className="text-xs text-muted">And what the detective found on top of it: not in the prompt, but in the data</h3>
      <p className="max-w-4xl text-base leading-8 text-slate-500">
        {extras.map((e) => (
          <mark
            key={e.id}
            tabIndex={0}
            role="button"
            aria-pressed={pinned === e.id}
            onMouseEnter={() => setHover(e.id)}
            onMouseLeave={() => setHover(null)}
            onClick={() => pin(e.id)}
            onKeyDown={(k) => {
              if (k.key === 'Enter' || k.key === ' ') {
                k.preventDefault()
                pin(e.id)
              }
            }}
            className={`mr-1.5 cursor-pointer border-b-2 border-dashed px-0.5 transition-colors duration-200 [box-decoration-break:clone] focus:outline-none ${
              pinned === e.id
                ? 'border-amber-300 bg-amber-300/20 text-white'
                : hover === e.id
                  ? 'border-amber-300/70 bg-amber-300/10 text-slate-100'
                  : 'border-amber-300/30 bg-amber-300/[0.04] text-slate-300'
            }`}
          >
            <sup className="mr-0.5 font-mono text-[9px] text-amber-300">{e.id}</sup>
            {e.hypothesis_cs || e.label_cs || `${metricCs(e.metric)} ${arrow(e.direction)} ${pct(e.magnitude_pct)}`}
          </mark>
        ))}
      </p>
    </div>
  )
}

// ---- one event at a time: the two sentences, then its chart ------------------------------------

function Said({ who, children, tone = 'slate' }: { who: string; children: ReactNode; tone?: 'slate' | 'amber' }) {
  return (
    <div className={`grid content-start gap-1 border-l-2 py-1 pl-3 ${tone === 'amber' ? 'border-amber-300/50' : 'border-line'}`}>
      <span className="text-xs text-muted">{who}</span>
      <div className="text-sm text-slate-100">{children}</div>
    </div>
  )
}

function Guess({ e }: { e: DetectEvent }) {
  return (
    <>
      <p>{e.hypothesis_cs || e.label_cs || <span className="text-muted">no hypothesis (an older run)</span>}</p>
      {e.observation_cs && <p className="mt-0.5 text-xs text-muted">{e.observation_cs}</p>}
    </>
  )
}

type Item = { key: string; v?: VerificationRow; find?: DetectEvent; planted?: PlantedEvent }

function ItemHead({ it, m }: { it: Item; m: Matching }) {
  if (it.planted || !it.find) {
    const pair = m.pairs.find((p) => p.planted.event_id === it.key)
    return (
      <header className="grid gap-3 sm:grid-cols-2">
        <Said who={`${it.key} · the prompt says`}>{it.v?.claim_cs || it.planted?.narrative_cs}</Said>
        {pair ? (
          <Said who={`${pair.found.id} · the detective guessed, blind (match ${num(pair.score, 2)}, offset ${signed(pair.slots.deltaDays)} d)`}>
            <Guess e={pair.found} />
          </Said>
        ) : (
          <Said who="the detective" tone="amber">
            <span className="text-amber-200">did not find this one</span>
          </Said>
        )}
      </header>
    )
  }
  const tag = extraTag(it.find, m)
  return (
    <header className="grid gap-3 sm:grid-cols-2">
      <Said who="the prompt says" tone="amber">
        <span className="text-muted">nothing about this</span> <Badge t={tag.t}>{tag.text}</Badge>
      </Said>
      <Said who={`${it.find.id} · the detective guessed, blind (confidence ${Math.round(it.find.confidence * 100)} %)`}>
        <Guess e={it.find} />
      </Said>
    </header>
  )
}

export default function RevSummary({ run }: { run: Run }) {
  const id = run.id!
  const d = run.detect!
  const key = useQuery(answerKeyOptions(id, true))
  const tables = useQuery(tablesOptions(id, true))
  const forbidden = isStatus(key.error, 403) || isStatus(key.error, 401)
  const planted = useMemo(
    () => (key.data ? key.data.answer_key : forbidden && run.result ? fromVerification(uniqueEvents(run.result.verification)) : null),
    [key.data, forbidden, run.result],
  )
  const found = useMemo(() => d.events ?? [], [d.events])
  // the server's pairing when it has one (it sees the stock levels and the twin), else the port
  const m = useMemo(
    () =>
      planted
        ? ((key.data && d.matching ? fromServer(found, planted, d.matching) : null) ?? matchEvents(found, planted, key.data?.decoys ?? []))
        : null,
    [found, planted, key.data, d.matching],
  )
  const [hover, setHover] = useState<string | null>(null)
  const [hl, setHl] = useState<string | null>(null)
  const [at, setAt] = useState(0)
  const [root, setRoot] = useState<HTMLDivElement | null>(null)
  const wide = useMedia('(min-width: 1024px)')
  const reduce = useMedia('(prefers-reduced-motion: reduce)')

  const rows = useMemo(() => run.result?.verification ?? [], [run.result])
  const extras = useMemo(
    () => (m ? found.filter((e) => isExtra(e, m)).sort((a, b) => a.start_date.localeCompare(b.start_date)) : []),
    [found, m],
  )
  // the planted events (one chart per verification row), then the detective's own finds
  const items = useMemo<Item[]>(() => {
    const charts = new Map((d.charts ?? []).map((v) => [v.event_id, v]))
    const byId = new Map((planted ?? []).map((t) => [t.event_id, t]))
    return [
      ...rows.map((v) => ({ key: v.event_id, v, planted: byId.get(v.event_id) })),
      ...extras.map((e) => ({ key: e.id, v: charts.get(e.id), find: e })),
    ]
  }, [rows, extras, d.charts, planted])

  if (key.error && !forbidden) return <p className="text-sm text-rose-200">{key.error.message}</p>
  if (!m || !planted) return <p className="text-sm text-muted">Loading the planted events…</p>

  const i = Math.min(at, Math.max(0, items.length - 1))
  const it = items[i]
  const pinned = it?.key ?? null
  const pin = (k: string) => setAt(Math.max(0, items.findIndex((x) => x.key === k)))
  const step = (n: number) => setAt((i + n + items.length) % items.length)
  const btn = 'border border-line px-3 py-1.5 text-sm text-slate-200 hover:border-slate-400 hover:bg-white/5'

  // found: pairs first in planted order, then consequences, then false finds; planted in story order
  const order = new Map(planted.map((t, j) => [t.event_id, j]))
  const foundSorted = [...found].sort((a, b) => rank(a) - rank(b))
  // stock-outs of single SKUs that are no planted event: folded into one line instead of a wall of "false find"
  const isLooseStockout = (e: DetectEvent) =>
    e.kind === 'stockout' &&
    !m.pairs.some((p) => p.found.id === e.id) &&
    !m.consequences.some((c) => c.found.id === e.id) &&
    !m.background.some((b) => b.found.id === e.id)
  const looseStockouts = foundSorted.filter(isLooseStockout)
  function rank(e: DetectEvent) {
    const p = m!.pairs.find((x) => x.found.id === e.id)
    if (p) return order.get(p.planted.event_id) ?? 0
    if (m!.consequences.some((c) => c.found.id === e.id)) return 1000
    return m!.background.some((b) => b.found.id === e.id) ? 1500 : 2000
  }

  return (
    <div className="grid gap-5">
      <Verdict m={m} nFound={found.length} server={d} />

      <div className="grid gap-4">
        <div className="grid gap-2">
          <h3 className="text-xs text-muted">The prompt that made the data · click a highlighted phrase for its chart and the detective's guess</h3>
          {run.input ? (
            <HighlightedPrompt input={run.input} rows={rows} hover={hl} setHover={setHl} pinned={pinned} pin={pin} />
          ) : (
            <p className="text-sm text-muted">Loading the prompt…</p>
          )}
        </div>
        <ExtraFinds extras={extras} hover={hl} setHover={setHl} pinned={pinned} pin={pin} />
        {d.narrative?.text && (
          <details className="text-sm">
            <summary className="cursor-pointer text-xs text-muted select-none hover:text-white">The detective's own story, written blind</summary>
            <p className="mt-2 max-w-4xl leading-relaxed whitespace-pre-line text-slate-300">{d.narrative.text}</p>
            {d.narrative.source && <p className="mt-1 text-xs text-slate-500">{d.narrative.source}</p>}
          </details>
        )}
      </div>

      <div className="grid min-w-0 content-start gap-4">
        {items.length > 1 && (
          <nav aria-label="Events" className="flex items-center gap-3">
            <button onClick={() => step(-1)} className={btn}>
              ← Previous
            </button>
            <span className="text-sm tabular-nums text-muted">
              {i + 1} / {items.length}
            </span>
            <button onClick={() => step(1)} className={btn}>
              Next →
            </button>
          </nav>
        )}
        {it &&
          (it.v && tables.data ? (
            <Block key={`${it.key}·${i}`} jobId={id} v={it.v} tables={tables.data.tables} head={<ItemHead it={it} m={m} />} />
          ) : (
            <article className="grid gap-3 border-t border-line pt-4">
              <ItemHead it={it} m={m} />
              <p className="text-sm text-muted">
                {it.v ? 'Loading the tables…' : 'No chart for this find (a run from before the detective tested its finds, or a KPI it cannot chart).'}
              </p>
            </article>
          ))}
      </div>

      <SideBySide m={m} hover={hover} setHover={setHover} />

      <details className="grid gap-4">
        <summary className="cursor-pointer text-xs text-muted select-none hover:text-white">
          Find by find: everything the detective reported against everything the story planted
        </summary>
        <div ref={setRoot} className="relative mt-4 grid gap-6 lg:grid-cols-2 lg:gap-x-20">
          <div className="grid content-start gap-3">
            <h3 className="text-xs text-muted">Detective, without knowing the story</h3>
            {found.length ? (
              <>
                <ul className="grid gap-1.5">
                  {foundSorted.filter((e) => !isLooseStockout(e)).map((e) => (
                    <FoundCard key={e.id} e={e} m={m} hover={hover} setHover={setHover} />
                  ))}
                </ul>
                {looseStockouts.length > 0 && (
                  <details className="border-l-2 border-dashed border-line py-1 pl-3 text-sm">
                    <summary className="cursor-pointer text-slate-300 select-none hover:text-white">
                      {looseStockouts.length} single-SKU stock-outs that match no planted event{' '}
                      <span className="text-xs text-muted">(the simulator's inventory also runs out by itself; counted as false finds in the score)</span>
                    </summary>
                    <ul className="mt-2 grid gap-1.5">
                      {looseStockouts.map((e) => (
                        <FoundCard key={e.id} e={e} m={m} hover={hover} setHover={setHover} />
                      ))}
                    </ul>
                  </details>
                )}
              </>
            ) : (
              <p className="text-sm text-muted">The detective found nothing in the data.</p>
            )}
          </div>
          <div className="grid content-start gap-3">
            <h3 className="text-xs text-muted">Original prompt and planted events</h3>
            <Prompt input={run.input} />
            {forbidden && <p className="text-[11px] text-slate-500">Only the teacher sees the answer key; the events come from the verification table.</p>}
            <ul className="grid gap-1.5">
              {planted.map((t) => (
                <PlantedCard key={t.event_id} t={t} m={m} hover={hover} setHover={setHover} />
              ))}
            </ul>
          </div>
          {wide && root && m.pairs.length > 0 && <Arrows root={root} m={m} hover={hover} reduce={reduce} />}
        </div>
      </details>
    </div>
  )
}

function uniqueEvents(rows: VerificationRow[]): VerificationRow[] {
  const seen = new Set<string>()
  return rows.filter((v) => (seen.has(v.event_id) ? false : (seen.add(v.event_id), true)))
}
