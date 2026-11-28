// Spec "/spec": the page for the projector. What the system is built from, and how hard it works
// right now (GET /v1/system, the last 15 minutes, redrawn every 2 s) plus the totals of GET /v1/stats.
// Big numbers, thick lines and near-white text: it has to read from the back of a room.
import { useEffect, useRef, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { healthOptions, statsOptions, systemOptions, type SystemSample } from '../api'
import { duration } from '../format'
import '../story/story.css'

const nf = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 })
const int = new Intl.NumberFormat('en-GB')

const COLOR = { cpu: '#73bf69', mem: '#8ab8ff', customers: '#f2cc0c', gpu: '#c8a7ff' }
const TEXT = '#e5e7eb'
const GRID = 'rgba(255,255,255,0.14)'

/** One filled line chart. Created once; each poll only calls setData (re-creating it would flicker). */
function Trend({ xs, ys, color, max, unit }: { xs: number[]; ys: (number | null)[]; color: string; max?: number; unit: string }) {
  const box = useRef<HTMLDivElement>(null)
  const plot = useRef<uPlot | null>(null)
  const last = useRef<uPlot.AlignedData>([xs, ys])
  last.current = [xs, ys]
  useEffect(() => {
    const el = box.current
    if (!el) return
    const axis = { stroke: TEXT, grid: { stroke: GRID, width: 1 }, ticks: { show: false }, font: '14px ui-sans-serif, system-ui, sans-serif' }
    const u = new uPlot(
      {
        width: el.clientWidth,
        height: 150,
        padding: [8, 8, 0, 0],
        cursor: { show: false },
        legend: { show: false },
        select: { show: false, left: 0, top: 0, width: 0, height: 0 },
        scales: { x: { time: true }, y: { range: (_u, _lo, hi) => [0, max ?? Math.max(hi * 1.25, 1)] } },
        axes: [
          { ...axis, size: 28, space: 90, grid: { show: false }, values: (_u, t) => t.map((s) => new Date(s * 1000).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })) },
          { ...axis, size: 52, space: 38, values: (_u, t) => t.map((v) => `${nf.format(v)}`), label: unit, labelSize: 0 },
        ],
        series: [
          {},
          {
            stroke: color,
            width: 2.5,
            points: { show: false },
            fill: (self) => {
              const g = self.ctx.createLinearGradient(0, self.bbox.top, 0, self.bbox.top + self.bbox.height)
              g.addColorStop(0, `${color}66`)
              g.addColorStop(1, `${color}05`)
              return g
            },
          },
        ],
      },
      last.current,
      el,
    )
    plot.current = u
    const ro = new ResizeObserver(() => u.setSize({ width: el.clientWidth, height: 150 }))
    ro.observe(el)
    return () => {
      ro.disconnect()
      u.destroy()
      plot.current = null
    }
  }, [color, max, unit])
  useEffect(() => {
    plot.current?.setData([xs, ys])
  }, [xs, ys])
  return <div ref={box} className="uplot-dark w-full" />
}

function Card({ title, value, unit, sub, children }: { title: string; value: ReactNode; unit?: string; sub?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-panel p-4 sm:p-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-base font-medium tracking-wide text-slate-200 uppercase">{title}</h2>
        {sub && <span className="truncate text-sm text-slate-300">{sub}</span>}
      </div>
      <div className="mt-1 mb-2 flex items-baseline gap-2">
        <span className="text-5xl font-semibold tabular-nums sm:text-6xl">{value}</span>
        {unit && <span className="text-xl text-slate-300">{unit}</span>}
      </div>
      {children}
    </section>
  )
}

function Tile({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className="rounded-2xl border border-line bg-panel px-4 py-3">
      <div className="text-sm tracking-wide text-slate-300 uppercase">{label}</div>
      <div className="text-4xl font-semibold tabular-nums sm:text-5xl" style={{ color: tone }}>
        {value}
      </div>
      {sub && <div className="truncate text-sm text-slate-300">{sub}</div>}
    </div>
  )
}

const STACK: [name: string, what: string][] = [
  ['Gemma 4 26b · Ollama', 'writes the spec and the Czech summary, nothing else'],
  ['numpy', 'day-by-day simulation over customer arrays'],
  ['DuckDB', 'working store and SQL sandbox, export to Postgres'],
  ['statsmodels · ruptures · scipy', 'STL, change points, difference-in-differences'],
  ['FastAPI', 'queued jobs, status with ETA, queries, ZIP'],
  ['React · Vite · uPlot', 'this site'],
]

const col = (s: SystemSample[], k: keyof SystemSample) => s.map((x) => x[k] as number | null)

export function Spec() {
  const sys = useQuery(systemOptions()).data
  const stats = useQuery(statsOptions()).data
  const llm = useQuery(healthOptions()).data?.llm
  const s = sys?.samples ?? []
  const xs = s.map((x) => x.t)
  const now = s.at(-1)
  const cpuNow = now?.cpu ?? null
  const customersNow = sys?.customers_now ?? 0
  const running = stats?.running

  return (
    <div className="grid gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">What it runs on, live</h1>
        <button
          className="rounded-lg border border-line px-3 py-1.5 text-sm text-slate-200 hover:bg-white/10"
          onClick={() => (document.fullscreenElement ? void document.exitFullscreen() : void document.documentElement.requestFullscreen())}
        >
          Full screen
        </button>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Server CPU" value={cpuNow === null ? '–' : nf.format(cpuNow)} unit="%" sub={sys?.cores ? `${sys.cores} cores · load ${now?.load ?? '–'}` : undefined}>
          <Trend xs={xs} ys={col(s, 'cpu')} color={COLOR.cpu} max={100} unit="%" />
        </Card>
        <Card
          title="Customers simulated right now"
          value={int.format(customersNow)}
          sub={running ? `${running.step ?? ''} · ${Math.round(running.progress * 100)} %${running.eta_s ? ` · ${duration(running.eta_s)} left` : ''}` : sys?.waiting ? `${sys.waiting} waiting` : 'idle'}
        >
          <Trend xs={xs} ys={col(s, 'customers')} color={COLOR.customers} unit="customers" />
        </Card>
        <Card title="Server memory" value={now?.mem_gb == null ? '–' : nf.format(now.mem_gb)} unit="GB" sub={sys?.mem_total_gb ? `of ${nf.format(sys.mem_total_gb)} GB` : undefined}>
          <Trend xs={xs} ys={col(s, 'mem_gb')} color={COLOR.mem} max={sys?.mem_total_gb ?? undefined} unit="GB" />
        </Card>
        <Card
          title="Model on the GPU"
          value={now?.vram_gb == null ? '–' : nf.format(now.vram_gb)}
          unit="GB VRAM"
          sub={llm ? `${llm.model} · ${sys?.gpu ? (sys.gpu.loaded ? 'loaded' : 'not loaded') : llm.backend}` : undefined}
        >
          <Trend xs={xs} ys={col(s, 'vram_gb')} color={COLOR.gpu} unit="GB" />
        </Card>
      </div>

      {stats && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Tile label="Customers simulated" value={int.format(stats.customers_simulated)} sub="all runs together" />
          <Tile label="Rows generated" value={int.format(stats.rows_generated)} sub="in all tables" />
          <Tile label="Runs" value={int.format(stats.jobs_done)} sub={`${int.format(stats.jobs_today)} today · median ${stats.median_run_s === null ? '–' : duration(stats.median_run_s)}`} />
          <Tile label="Events confirmed" value={stats.events_confirmed_pct === null ? '–' : `${nf.format(stats.events_confirmed_pct)} %`} sub="detective finds the planted story" tone={COLOR.cpu} />
          <Tile label="Twin false alarms" value={stats.twin_false_pct === null ? '–' : `${nf.format(stats.twin_false_pct)} %`} sub="same data, no story" tone={COLOR.customers} />
        </div>
      )}

      <section className="rounded-2xl border border-line bg-panel p-4 sm:p-5">
        <h2 className="mb-3 text-base font-medium tracking-wide text-slate-200 uppercase">What we use</h2>
        <ul className="grid gap-x-8 gap-y-2 text-lg md:grid-cols-2">
          {STACK.map(([name, what]) => (
            <li key={name}>
              <b className="text-white">{name}</b> <span className="text-slate-300">– {what}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
