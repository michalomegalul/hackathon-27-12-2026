// Daily KPI of one verification row in the story and in its twin, with a marker at `start`
// (uPlot, dark). Data: the row's own SQL cut at its `daily` CTE (model.dailySql), run through
// POST /query once per world.
import { useEffect, useMemo, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { sqlOptions, type Cell, type VerificationRow } from '../api'
import { KPI_CS, dateCs } from '../format'
import { Alert, Spinner } from '../components/ui'
import { dailySql, daySec, rolling } from './model'

const C = { marker: '#f2cc0c', grid: '#2c3235', text: '#9fa7b3' }
const DAY = 86_400

const controlLabel = (v: VerificationRow) =>
  v.control_mode === 'yoy' ? 'stejné dny loni' : v.control_mode === 'none' ? '' : v.control || 'kontrola'

/** Vertical line + label at `start`, drawn over the series. */
function markerPlugin(start: number, label: string): uPlot.Plugin {
  return {
    hooks: {
      draw: (u) => {
        const x = u.valToPos(start, 'x', true)
        const { top, height, left, width } = u.bbox
        if (x < left || x > left + width) return
        const ctx = u.ctx
        const px = devicePixelRatio
        ctx.save()
        ctx.strokeStyle = C.marker
        ctx.lineWidth = 1.5 * px
        ctx.setLineDash([5 * px, 4 * px])
        ctx.beginPath()
        ctx.moveTo(x, top)
        ctx.lineTo(x, top + height)
        ctx.stroke()
        ctx.setLineDash([])
        ctx.fillStyle = C.marker
        ctx.font = `${11 * px}px ui-sans-serif, system-ui, sans-serif`
        ctx.fillText(label, x + 5 * px, top + 13 * px)
        ctx.restore()
      },
    },
  }
}

// ---- story vs twin: one line until the event, then they split ------------------------------

const T = { story: '#73bf69', twin: '#b8c0cc', control: '#8ab8ff', gap: 'rgba(115,191,105,0.16)' }

/** Fill between series a and b from `start` on (the effect of the story: story minus twin). */
function gapPlugin(start: number, a: number, b: number): uPlot.Plugin {
  return {
    hooks: {
      drawSeries: (u, si) => {
        if (si !== a) return
        const xs = u.data[0]
        const ya = u.data[a] as (number | null)[]
        const yb = u.data[b] as (number | null)[]
        const ctx = u.ctx
        const top: [number, number][] = []
        const bottom: [number, number][] = []
        for (let i = 0; i < xs.length; i++) {
          if (xs[i] < start || ya[i] === null || yb[i] === null) continue
          const x = u.valToPos(xs[i], 'x', true)
          top.push([x, u.valToPos(ya[i]!, 'y', true)])
          bottom.push([x, u.valToPos(yb[i]!, 'y', true)])
        }
        if (top.length < 2) return
        const { left, top: t, width, height } = u.bbox
        ctx.save()
        ctx.beginPath()
        ctx.rect(left, t, width, height)
        ctx.clip()
        ctx.beginPath()
        top.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))
        for (let i = bottom.length - 1; i >= 0; i--) ctx.lineTo(bottom[i][0], bottom[i][1])
        ctx.closePath()
        ctx.fillStyle = T.gap
        ctx.fill()
        ctx.restore()
      },
    },
  }
}

function SplitPlot({ data, v, hasControl, height }: { data: uPlot.AlignedData; v: VerificationRow; hasControl: boolean; height: number }) {
  const el = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const box = el.current!
    const start = daySec(v.start)
    const xs = data[0]
    const axis: uPlot.Axis = {
      stroke: C.text,
      grid: { stroke: C.grid, width: 1 },
      ticks: { stroke: C.grid, width: 1 },
      font: '11px ui-sans-serif, system-ui, sans-serif',
    }
    const opts: uPlot.Options = {
      width: box.clientWidth,
      height,
      tzDate: (ts) => uPlot.tzDate(new Date(ts * 1000), 'UTC'),
      scales: {
        x: { min: Math.max(xs[0], start - 56 * DAY), max: Math.min(xs[xs.length - 1], start + 56 * DAY) },
        // fitted, not from zero: a −5 % split must be visible
        y: { range: (_u, min, max) => (max > min ? [min - (max - min) * 0.15, max + (max - min) * 0.15] : [min - 1, max + 1]) },
      },
      series: [
        { value: '{D}. {M}. {YYYY}' },
        { label: 'příběh', stroke: T.story, width: 2.2, points: { show: false } },
        { label: 'dvojče bez příběhu', stroke: T.twin, width: 1.6, dash: [6, 4], points: { show: false } },
        ...(hasControl
          ? [{ label: `kontrola: ${controlLabel(v)}`, stroke: T.control, width: 1, alpha: 0.55, scale: 'c', points: { show: false } }]
          : []),
      ],
      axes: [
        axis,
        { ...axis, values: czNums, label: `${KPI_CS[v.kpi] ?? v.kpi}, 7 dní`, labelFont: '11px ui-sans-serif, system-ui, sans-serif', labelSize: 16 },
        ...(hasControl ? [{ ...axis, values: czNums, scale: 'c', side: 1, grid: { show: false }, stroke: T.control }] : []),
      ],
      cursor: { drag: { x: true, y: false } },
      legend: { show: false }, // the caption above the chart is the legend
      plugins: [gapPlugin(start, 1, 2), markerPlugin(start, `událost ${dateCs(v.start)}`)],
    }
    const plot = new uPlot(opts, data, box)
    const ro = new ResizeObserver(() => plot.setSize({ width: box.clientWidth, height }))
    ro.observe(box)
    return () => {
      ro.disconnect()
      plot.destroy()
    }
  }, [data, v, hasControl, height])
  return <div ref={el} className="uplot-dark w-full" />
}

const nf = new Intl.NumberFormat('cs-CZ', { maximumFractionDigits: 2 })
const czNums = (_u: uPlot, ticks: number[]) => ticks.map((t) => nf.format(t))

const ys = (rows: Cell[][], i: number) => rows.map((r) => (r[i] === null ? null : Number(r[i])))

/**
 * The row's daily KPI in the story and in its twin (the same company without the story), 7-day
 * means, the gap after the event shaded; the control (its own scale) for reference.
 */
export function KpiChart({ jobId, v, height = 200 }: { jobId: string; v: VerificationRow; height?: number }) {
  const sql = useMemo(() => dailySql(v), [v])
  const story = useQuery(sqlOptions(jobId, sql, 'story'))
  const twin = useQuery(sqlOptions(jobId, sql, 'twin'))
  const series = useMemo(() => {
    if (!story.data) return undefined
    const rows = story.data.rows
    const xs = rows.map((r) => daySec(String(r[0])))
    // the twin by day (same calendar, but do not trust the order)
    const tw = new Map((twin.data?.rows ?? []).map((r) => [String(r[0]), r[1] === null ? null : Number(r[1])]))
    const twinYs = rows.map((r) => tw.get(String(r[0])) ?? null)
    const c = ys(rows, 2)
    const hasControl = c.some((y) => y !== null)
    const data: uPlot.AlignedData = hasControl
      ? [xs, rolling(ys(rows, 1), 7), rolling(twinYs, 7), rolling(c, 7)]
      : [xs, rolling(ys(rows, 1), 7), rolling(twinYs, 7)]
    return { data, hasControl }
  }, [story.data, twin.data])

  if (!sql) return <p className="text-sm text-muted">Tato událost nemá denní řadu (jiný typ ověření).</p>
  if (story.error) return <Alert>{story.error.message}</Alert>
  if (!series || (twin.isPending && !twin.error))
    return (
      <p className="grid place-items-center text-sm text-muted" style={{ height: height + 40 }}>
        <span>
          <Spinner /> Počítám denní řadu příběhu a dvojčete…
        </span>
      </p>
    )
  return (
    <>
      <SplitPlot data={series.data} v={v} hasControl={series.hasControl} height={height} />
      {twin.error && <p className="text-xs text-amber-300">Dvojče se nenačetlo: {twin.error.message}</p>}
    </>
  )
}
