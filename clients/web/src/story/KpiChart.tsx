// Daily KPI of the target vs the control for one event, with a marker at `start` (uPlot, dark).
// Data: the row's own SQL cut at its `daily` CTE (model.dailySql), run through POST /query.
import { useEffect, useMemo, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { retryTransient, runQuery, type VerificationRow } from '../api'
import { KPI_CS, dateCs, withUnit } from '../format'
import { Alert, Spinner } from '../components/ui'
import { dailySql, daySec, rolling } from './model'

const C = { target: '#73bf69', control: '#8ab8ff', marker: '#f2cc0c', grid: '#2c3235', text: '#9fa7b3' }
const DAY = 86_400
const HEIGHT = 220

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

function Plot({ data, v, hasControl }: { data: uPlot.AlignedData; v: VerificationRow; hasControl: boolean }) {
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
    const kpi = KPI_CS[v.kpi] ?? v.kpi
    const opts: uPlot.Options = {
      width: box.clientWidth,
      height: HEIGHT,
      tzDate: (ts) => uPlot.tzDate(new Date(ts * 1000), 'UTC'),
      // the 8 weeks either side of `start`; drag to zoom, double-click for everything
      scales: {
        x: { min: Math.max(xs[0], start - 56 * DAY), max: Math.min(xs[xs.length - 1], start + 56 * DAY) },
        y: { range: (_u, min, max) => [Math.min(0, min), max + (max - min) * 0.1 || 1] },
      },
      series: [
        { value: '{D}. {M}. {YYYY}' },
        { label: `cíl: ${v.target}`, stroke: C.target, width: 0.8, alpha: 0.35, points: { show: false } },
        { label: 'cíl, 7 dní', stroke: C.target, width: 2, fill: 'rgba(115,191,105,0.10)', points: { show: false } },
        ...(hasControl
          ? [
              { label: `kontrola: ${controlLabel(v)}`, stroke: C.control, width: 0.8, alpha: 0.35, scale: 'c', points: { show: false } },
              { label: 'kontrola, 7 dní', stroke: C.control, width: 2, scale: 'c', points: { show: false } },
            ]
          : []),
      ],
      axes: [
        axis,
        { ...axis, label: kpi, labelFont: '11px ui-sans-serif, system-ui, sans-serif', labelSize: 16, stroke: C.target },
        ...(hasControl ? [{ ...axis, scale: 'c', side: 1, grid: { show: false }, stroke: C.control }] : []),
      ],
      cursor: { drag: { x: true, y: false } },
      legend: { live: true },
      plugins: [markerPlugin(start, `start ${dateCs(v.start)}`)],
    }
    const plot = new uPlot(opts, data, box)
    const ro = new ResizeObserver(() => plot.setSize({ width: box.clientWidth, height: HEIGHT }))
    ro.observe(box)
    return () => {
      ro.disconnect()
      plot.destroy()
    }
  }, [data, v, hasControl])
  return <div ref={el} className="uplot-dark w-full" />
}

export function KpiChart({ jobId, v }: { jobId: string; v: VerificationRow }) {
  const sql = useMemo(() => dailySql(v), [v])
  const q = useQuery({
    queryKey: ['daily', jobId, v.event_id, v.kpi, v.target],
    queryFn: () => runQuery(jobId, sql!),
    enabled: Boolean(sql),
    staleTime: Infinity, // a finished job's data never changes
    retry: retryTransient,
  })
  const series = useMemo(() => {
    if (!q.data) return undefined
    const xs = q.data.rows.map((r) => daySec(String(r[0])))
    const t = q.data.rows.map((r) => (r[1] === null ? null : Number(r[1])))
    const c = q.data.rows.map((r) => (r[2] === null ? null : Number(r[2])))
    const hasControl = c.some((y) => y !== null)
    const data: uPlot.AlignedData = hasControl ? [xs, t, rolling(t, 7), c, rolling(c, 7)] : [xs, t, rolling(t, 7)]
    return { data, hasControl }
  }, [q.data])

  return (
    <figure className="grid gap-2 rounded-xl border border-line bg-[#181b1f] p-3">
      <figcaption className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        <span className="font-mono text-xs text-muted">{v.event_id}</span>
        <span className="font-medium">{KPI_CS[v.kpi] ?? v.kpi}</span>
        <span className="font-mono text-xs text-muted">{v.target}</span>
        <span className="ml-auto tabular-nums text-accent">{withUnit(v.measured, v.measured_unit)}</span>
      </figcaption>
      {!sql ? (
        <p className="text-sm text-muted">Tato událost nemá denní řadu (jiný typ ověření).</p>
      ) : q.error ? (
        <Alert>{q.error.message}</Alert>
      ) : !series ? (
        <p className="grid h-[260px] place-items-center text-sm text-muted">
          <span>
            <Spinner /> Počítám denní řadu…
          </span>
        </p>
      ) : (
        <Plot data={series.data} v={v} hasControl={series.hasControl} />
      )}
      {q.data?.truncated && <p className="text-xs text-amber-300">Řada byla zkrácena na 1000 dní.</p>}
    </figure>
  )
}
