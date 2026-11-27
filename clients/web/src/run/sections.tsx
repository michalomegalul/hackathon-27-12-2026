// The six sections of the run view, in order. Each is a grey placeholder (RunView.Section) until
// its stage is done. Data and Summary are lazy chunks (React Flow, TanStack Table, uPlot, anime.js).
import { Suspense, lazy, useState, type ReactNode } from 'react'
import { type DetectEvent, type DetectScore, type JobResult, type Step } from '../api'
import { Notes, VerificationTable } from '../components/Result'
import { ShowMore, Spinner } from '../components/ui'
import { KIND_CS, KPI_CS, METRIC_CS, dateCs, duration, intCs, num, withUnit } from '../format'
import { useSpec, type Spec } from '../spec'
import { Section } from './RunView'
import { sectionId } from './useRun'
import { SpecView } from './SpecView'
import type { Run } from './useRun'

const DataView = lazy(async () => ({ default: (await import('./DataView')).DataView }))
const Summary = lazy(() => import('./Summary'))
const RevSummary = lazy(() => import('./RevSummary'))

const frac = (s: string) => s.split('/').map(Number) as [number, number]
const kpi = (k: string) => KPI_CS[k] ?? k

function Waiting({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-center gap-2 text-sm text-muted">
      <Spinner /> {children}
    </p>
  )
}

// ---- 1. Prompt -------------------------------------------------------------------------

export function PromptSection({ run, specName, composer }: { run: Run; specName?: string; composer?: ReactNode }) {
  const i = run.input
  // a new run: the prompt is typed right here
  if (composer)
    return (
      <section id={sectionId('prompt')} className="scroll-mt-32 border-t border-line pt-5 lg:scroll-mt-20">
        <header className="mb-3 flex items-baseline gap-2">
          <span className="font-mono text-xs text-slate-500">1</span>
          <h2 className="font-semibold">Prompt</h2>
        </header>
        {composer}
      </section>
    )
  return (
    <Section run={run} id="prompt" title="Prompt" hint={run.id && <span className="font-mono">{run.id}</span>}>
      {!i ? (
        <Waiting>Loading the prompt…</Waiting>
      ) : i.spec_given ? (
        <p className="text-sm text-slate-300">
          Ready-made spec{specName ? <span className="font-mono"> {specName}</span> : null}, no LLM.
        </p>
      ) : (
        <div className="grid max-w-3xl gap-2 border-l-2 border-line py-1 pl-4 text-sm leading-relaxed">
          <p className="text-slate-300">{i.company}</p>
          {i.story && i.story !== i.company && <p className="whitespace-pre-line text-slate-100">{i.story}</p>}
        </div>
      )}
    </Section>
  )
}

// ---- 2. Spec ---------------------------------------------------------------------------

function EventsTable({ r }: { r: JobResult }) {
  // one event can give several rows (one per KPI it moves): list each event once
  const seen = new Set<string>()
  const rows = r.verification.filter((v) => (seen.has(v.event_id) ? false : (seen.add(v.event_id), true)))
  if (!rows.length) return <p className="text-sm text-muted">The story contains no verifiable events.</p>
  return (
    <>
      <ul className="grid gap-2 md:hidden">
        {rows.map((v) => (
          <li key={v.event_id} className="border-l-2 border-line py-1 pl-3 text-sm">
            <div className="flex gap-2">
              <span className="font-mono text-xs text-muted">{v.event_id}</span>
              <span className="flex-1">{v.claim_cs}</span>
            </div>
            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted">
              <span>{kpi(v.kpi)}</span>
              <span className="font-mono">{v.target || 'everyone'}</span>
              <span>od {dateCs(v.start)}</span>
              <span className="tabular-nums text-slate-300">{withUnit(v.story_size, v.story_unit)}</span>
            </div>
          </li>
        ))}
      </ul>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="py-2 pr-3 font-medium">Event</th>
              <th className="py-2 pr-3 font-medium">KPI</th>
              <th className="py-2 pr-3 font-medium">Koho</th>
              <th className="py-2 pr-3 font-medium">Od</th>
              <th className="py-2 text-right font-medium whitespace-nowrap">Size in the story</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((v) => (
              <tr key={v.event_id} className="border-b border-line/50 align-top last:border-0">
                <td className="py-2 pr-3">
                  <span className="mr-2 font-mono text-xs text-muted">{v.event_id}</span>
                  {v.claim_cs}
                </td>
                <td className="py-2 pr-3 whitespace-nowrap">{kpi(v.kpi)}</td>
                <td className="py-2 pr-3 font-mono text-xs leading-5">{v.target || 'everyone'}</td>
                <td className="py-2 pr-3 whitespace-nowrap tabular-nums">{dateCs(v.start)}</td>
                <td className="py-2 text-right whitespace-nowrap tabular-nums">{withUnit(v.story_size, v.story_unit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

export function SpecSection({ run, spec }: { run: Run; spec: Spec | null }) {
  const step = run.job?.steps[0]
  const note = step?.done ? step.note : ''
  return (
    <Section
      run={run}
      id="spec"
      title="Spec"
      hint={note}
      waiting={<Waiting>The LLM is reading the story and writing the spec…</Waiting>}
    >
      {run.result ? (
        <div className="grid gap-4">
          <SpecView
            r={run.result}
            spec={spec}
            fallback={<EventsTable r={run.result} />}
          />
          <Notes r={run.result} />
        </div>
      ) : run.stages.data.state === 'error' ? (
        <p className="text-sm text-muted">The spec is ready; its parameters appear with the result.</p>
      ) : (
        <p className="text-sm text-muted">
          The spec is generated. The API returns its parameters and events together with the result, so they appear when the data is generated and verified.
        </p>
      )}
    </Section>
  )
}

// ---- 3. Data ---------------------------------------------------------------------------

function SubSteps({ steps, current }: { steps: Step[]; current: number }) {
  return (
    <ol className="grid gap-1 text-sm">
      {steps.map((s, i) => {
        const n = i + 2 // API steps 2..5
        const running = !s.done && n === current
        return (
          <li key={s.name} className="flex items-center gap-2.5">
            <span className={`w-4 text-center text-xs ${s.done ? 'text-accent' : running ? 'text-accent' : 'text-slate-600'}`}>
              {s.done ? '✓' : running ? <Spinner /> : '·'}
            </span>
            <span className={s.done ? 'text-slate-300' : running ? 'text-white' : 'text-slate-500'}>{s.name}</span>
            {s.done && s.note && <span className="truncate text-xs text-muted">{s.note}</span>}
            <span className="ml-auto shrink-0 text-xs tabular-nums text-muted">{s.done ? duration(s.s) : `~${duration(s.eta_s)}`}</span>
          </li>
        )
      })}
    </ol>
  )
}

export function DataSection({ run }: { run: Run }) {
  const steps = run.job?.steps.slice(1) ?? []
  const total = run.result ? Object.values(run.result.rows).reduce((a, b) => a + b, 0) : 0
  return (
    <Section
      run={run}
      id="data"
      title="Data"
      hint={total > 0 && `${intCs(total)} rows`}
      waiting={<SubSteps steps={steps} current={run.job?.step_index ?? 0} />}
    >
      {run.id && (
        <Suspense fallback={<Waiting>Loading tables…</Waiting>}>
          <DataView id={run.id} />
        </Suspense>
      )}
    </Section>
  )
}

// ---- 4. Detective -----------------------------------------------------------------------

const arrow = (d: string) => (d === 'up' ? '↑' : d === 'down' ? '↓' : '·')

function FoundEvent({ e }: { e: DetectEvent }) {
  return (
    <li className="grid gap-1 border-l-2 border-line py-1 pl-3 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <span className="font-mono text-xs text-muted">{e.id}</span>
        <span title={KIND_CS[e.kind] ?? e.kind}>
          {METRIC_CS[e.metric] ?? e.metric} <span className={e.direction === 'down' ? 'text-rose-300' : 'text-emerald-300'}>{arrow(e.direction)}</span>
        </span>
        <span className="font-mono text-xs text-slate-400">{e.segment || 'everyone'}</span>
        <span className="text-xs text-muted">
          {KIND_CS[e.kind] ?? e.kind}, od {dateCs(e.start_date)}
          {e.end_date && ` do ${dateCs(e.end_date)}`}
        </span>
        {e.magnitude_pct !== null && <span className="ml-auto tabular-nums">{withUnit(e.magnitude_pct, '%')}</span>}
        <span className="text-xs tabular-nums text-muted" title="detective confidence">
          {Math.round(e.confidence * 100)} %
        </span>
      </div>
    </li>
  )
}

const FIRST_FOUND = 10

export function DetectSection({ run }: { run: Run }) {
  const d = run.detect
  const [all, setAll] = useState(false)
  const found = d?.events ?? []
  return (
    <Section
      run={run}
      id="detect"
      title="Detective"
      hint={d && `${d.events?.length ?? 0} findings in ${duration(d.elapsed_s)}`}
      waiting={
        <Waiting>
          {d?.status === 'queued' ? 'The detective is queued…' : 'The detective is searching the data without knowing the story…'}
        </Waiting>
      }
    >
      {d && (
        <div className="grid gap-4">
          {found.length ? (
            <div className="grid gap-2">
              <ul className="grid gap-1.5">
                {(all ? found : found.slice(0, FIRST_FOUND)).map((e) => (
                  <FoundEvent key={e.id} e={e} />
                ))}
              </ul>
              {found.length > FIRST_FOUND && (
                <ShowMore open={all} onClick={() => setAll((a) => !a)} more={found.length - FIRST_FOUND} noun={['finding', 'findings']} />
              )}
            </div>
          ) : (
            <p className="text-sm text-muted">The detective found nothing in the data.</p>
          )}
          {d.narrative?.text && (
            <blockquote className="border-l-2 border-line pl-3 text-sm leading-relaxed whitespace-pre-line text-slate-300">
              {d.narrative.text}
              {d.narrative.source && <footer className="mt-2 text-xs text-slate-500">{d.narrative.source}</footer>}
            </blockquote>
          )}
        </div>
      )}
    </Section>
  )
}

// ---- 5. Score --------------------------------------------------------------------------

type Light = 'green' | 'amber' | 'red' | null
const LIGHT: Record<string, [string, string]> = {
  green: ['border-emerald-500/70', 'text-emerald-300'],
  amber: ['border-amber-500/70', 'text-amber-300'],
  red: ['border-rose-500/70', 'text-rose-300'],
}

function Tile({ label, value, sub, good, light }: { label: string; value: ReactNode; sub: string; good?: boolean | null; light?: Light }) {
  const l = light !== undefined ? light : good === null || good === undefined ? null : good ? 'green' : 'amber'
  const [border, text] = l ? LIGHT[l] : ['border-line', '']
  return (
    <div className={`border-l-2 py-1 pl-3 ${border}`}>
      <div className="text-xs text-muted">{label}</div>
      <div className={`text-2xl font-semibold tabular-nums ${text}`}>{value}</div>
      <div className="text-xs text-muted">{sub}</div>
    </div>
  )
}

function DetectiveTiles({ s }: { s: DetectScore | null }) {
  if (!s)
    return <Tile label="detective" value="–" sub="only the teacher sees the score" good={null} />
  return (
    <Tile
      label="detective P / R / F1"
      value={`${num(s.precision, 2)} / ${num(s.recall, 2)} / ${num(s.f1, 2)}`}
      sub="precision / recall / F1 against the key"
      good={s.f1 >= 0.6}
    />
  )
}

export function ScoreSection({ run }: { run: Run }) {
  const r = run.result
  return (
    <Section run={run} id="score" title="Score">
      {r && (
        <div className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-3">
            {(() => {
              const [ok, all] = frac(r.summary.story)
              const [hit] = frac(r.summary.twin)
              return (
                <>
                  <Tile label="story" value={`${ok}/${all}`} sub="events confirmed in the data" good={all > 0 && ok === all} />
                  <Tile
                    label="unidentified events"
                    value={hit}
                    sub="found in the twin, which has no story (should be 0)"
                    light={hit === 0 ? 'green' : hit === 1 ? 'amber' : 'red'}
                  />
                </>
              )
            })()}
            <DetectiveTiles s={run.detect?.score ?? null} />
          </div>
          {r.verification.length > 0 && (
            <details className="group">
              <summary className="cursor-pointer text-sm text-muted select-none hover:text-white">
                Verification event by event (measured, 95% CI, z, SQL)
              </summary>
              <div className="mt-3">
                <VerificationTable rows={r.verification} jobId={r.job_id} />
              </div>
            </details>
          )}
        </div>
      )}
    </Section>
  )
}

// ---- 6. Summary ------------------------------------------------------------------------

export function SummarySection({ run, spec, mode = 'story' }: { run: Run; spec: Spec | null; mode?: Mode }) {
  return (
    <Section run={run} id="summary" title="Summary" hint={mode === 'rev' && 'detective vs. prompt'}>
      {run.result && run.id && (
        <Suspense fallback={<Waiting>Preparing the summary…</Waiting>}>
          {mode === 'rev' && run.detect ? <RevSummary run={run} /> : <Summary run={run} spec={spec} />}
        </Suspense>
      )}
    </Section>
  )
}

/** story: Summary links the prompt to charts and tables; rev: the detective's story against the prompt. */
export type Mode = 'story' | 'rev'

export function Sections({ run, specName, mode = 'story', composer }: { run: Run; specName?: string; mode?: Mode; composer?: ReactNode }) {
  const spec = useSpec(run.result?.spec_yaml)
  return (
    <>
      <PromptSection run={run} specName={specName} composer={composer} />
      <SpecSection run={run} spec={spec} />
      <DataSection run={run} />
      <DetectSection run={run} />
      <ScoreSection run={run} />
      <SummarySection run={run} spec={spec} mode={mode} />
    </>
  )
}
