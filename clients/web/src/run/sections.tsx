// The six sections of the run view, in order. Each is a grey placeholder (RunView.Section) until
// its stage is done. Prompt 2 of docs/prompts/06-web-v2.md makes Spec, Data and Shrnutí rich.
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { tablesOptions, type DetectEvent, type DetectScore, type JobResult, type Step } from '../api'
import { DownloadButton } from '../components/Download'
import { Notes, VerificationTable } from '../components/Result'
import { Alert, Spinner } from '../components/ui'
import { KIND_CS, KPI_CS, METRIC_CS, dateCs, duration, intCs, num, withUnit } from '../format'
import { Section } from './RunView'
import type { Run } from './useRun'

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

export function PromptSection({ run, specName }: { run: Run; specName?: string }) {
  const i = run.input
  return (
    <Section run={run} id="prompt" title="Prompt" hint={run.id && <span className="font-mono">{run.id}</span>}>
      {!i ? (
        <Waiting>Načítám zadání…</Waiting>
      ) : i.spec_given ? (
        <p className="text-sm text-slate-300">
          Hotová specifikace{specName ? <span className="font-mono"> {specName}</span> : null}, bez AI.
        </p>
      ) : (
        <div className="ml-auto grid max-w-3xl gap-2 rounded-xl rounded-tr-sm border border-line bg-bg/60 px-4 py-3 text-sm leading-relaxed">
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
  if (!rows.length) return <p className="text-sm text-muted">Příběh neobsahuje žádné ověřitelné události.</p>
  return (
    <>
      <ul className="grid gap-2 md:hidden">
        {rows.map((v) => (
          <li key={v.event_id} className="rounded-lg border border-line bg-bg/40 p-3 text-sm">
            <div className="flex gap-2">
              <span className="font-mono text-xs text-muted">{v.event_id}</span>
              <span className="flex-1">{v.claim_cs}</span>
            </div>
            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted">
              <span>{kpi(v.kpi)}</span>
              <span className="font-mono">{v.target || 'všichni'}</span>
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
              <th className="py-2 pr-3 font-medium">Událost</th>
              <th className="py-2 pr-3 font-medium">KPI</th>
              <th className="py-2 pr-3 font-medium">Koho</th>
              <th className="py-2 pr-3 font-medium">Od</th>
              <th className="py-2 text-right font-medium whitespace-nowrap">Velikost v příběhu</th>
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
                <td className="py-2 pr-3 font-mono text-xs leading-5">{v.target || 'všichni'}</td>
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

export function SpecSection({ run }: { run: Run }) {
  const step = run.job?.steps[0]
  const note = step?.done ? step.note : ''
  return (
    <Section
      run={run}
      id="spec"
      title="Spec"
      hint={note}
      waiting={<Waiting>AI čte příběh a píše specifikaci…</Waiting>}
    >
      {run.result ? (
        <div className="grid gap-4">
          <EventsTable r={run.result} />
          <Notes r={run.result} />
        </div>
      ) : run.stages.data.state === 'error' ? (
        <p className="text-sm text-muted">Specifikace je hotová; tabulka událostí se ukáže s výsledkem.</p>
      ) : (
        <Waiting>Specifikace je hotová. Události se ukážou, až simulátor data vyrobí a ověří.</Waiting>
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

function TableList({ id }: { id: string }) {
  const q = useQuery(tablesOptions(id, true))
  if (q.error) return <Alert>{q.error.message}</Alert>
  if (!q.data) return <Waiting>Načítám tabulky…</Waiting>
  return (
    <ul className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
      {q.data.tables.map((t) => (
        <li key={t.name}>
          <Link
            to={`/run/${id}/data?t=${encodeURIComponent(t.name)}`}
            className="flex items-baseline gap-2 rounded-lg border border-line bg-bg/40 px-3 py-2 hover:border-slate-500"
          >
            <span className="truncate font-mono text-sm">{t.name}</span>
            <span className="text-xs text-slate-500">{t.columns.length} sl.</span>
            <span className="ml-auto text-sm tabular-nums text-slate-300">{intCs(t.rows)}</span>
          </Link>
        </li>
      ))}
    </ul>
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
      hint={total > 0 && `${intCs(total)} řádků`}
      waiting={<SubSteps steps={steps} current={run.job?.step_index ?? 0} />}
    >
      {run.id && (
        <div className="grid gap-3">
          <TableList id={run.id} />
          <div className="flex flex-wrap items-center gap-2">
            <Link to={`/run/${run.id}/data`} className="rounded-lg border border-line px-3 py-1.5 text-sm hover:border-slate-500">
              Prohlížet data a SQL
            </Link>
            <DownloadButton id={run.id} />
          </div>
        </div>
      )}
    </Section>
  )
}

// ---- 4. Detektiv -----------------------------------------------------------------------

const arrow = (d: string) => (d === 'up' ? '↑' : d === 'down' ? '↓' : '·')

function FoundEvent({ e }: { e: DetectEvent }) {
  return (
    <li className="grid gap-1 rounded-lg border border-line bg-bg/40 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <span className="font-mono text-xs text-muted">{e.id}</span>
        <span title={KIND_CS[e.kind] ?? e.kind}>
          {METRIC_CS[e.metric] ?? e.metric} <span className={e.direction === 'down' ? 'text-rose-300' : 'text-emerald-300'}>{arrow(e.direction)}</span>
        </span>
        <span className="font-mono text-xs text-slate-400">{e.segment || 'všichni'}</span>
        <span className="text-xs text-muted">
          {KIND_CS[e.kind] ?? e.kind}, od {dateCs(e.start_date)}
          {e.end_date && ` do ${dateCs(e.end_date)}`}
        </span>
        {e.magnitude_pct !== null && <span className="ml-auto tabular-nums">{withUnit(e.magnitude_pct, '%')}</span>}
        <span className="text-xs tabular-nums text-muted" title="jistota detektivu">
          {Math.round(e.confidence * 100)} %
        </span>
      </div>
    </li>
  )
}

export function DetectSection({ run }: { run: Run }) {
  const d = run.detect
  return (
    <Section
      run={run}
      id="detect"
      title="Detektiv"
      hint={d && `${d.events?.length ?? 0} nálezů za ${duration(d.elapsed_s)}`}
      waiting={
        <Waiting>
          {d?.status === 'queued' ? 'Detektiv čeká ve frontě…' : 'Detektiv prohledává data, aniž by znal příběh…'}
        </Waiting>
      }
    >
      {d && (
        <div className="grid gap-4">
          {d.events?.length ? (
            <ul className="grid gap-1.5">
              {d.events.map((e) => (
                <FoundEvent key={e.id} e={e} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">Detektiv v datech nic nenašel.</p>
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

// ---- 5. Skóre --------------------------------------------------------------------------

function Tile({ label, value, sub, good }: { label: string; value: ReactNode; sub: string; good: boolean | null }) {
  return (
    <div className="rounded-xl border border-line bg-bg/40 p-3.5">
      <div className="text-xs text-muted">{label}</div>
      <div className={`text-2xl font-semibold tabular-nums ${good === null ? '' : good ? 'text-accent' : 'text-amber-300'}`}>{value}</div>
      <div className="text-xs text-muted">{sub}</div>
    </div>
  )
}

function DetectiveTiles({ s }: { s: DetectScore | null }) {
  if (!s)
    return <Tile label="detektiv" value="–" sub="skóre vidí jen učitel" good={null} />
  return (
    <Tile
      label="detektiv P / R / F1"
      value={`${num(s.precision, 2)} / ${num(s.recall, 2)} / ${num(s.f1, 2)}`}
      sub="přesnost / úplnost / F1 proti klíči"
      good={s.f1 >= 0.6}
    />
  )
}

export function ScoreSection({ run }: { run: Run }) {
  const r = run.result
  return (
    <Section run={run} id="score" title="Skóre">
      {r && (
        <div className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-3">
            {(() => {
              const [ok, all] = frac(r.summary.story)
              const [hit, tAll] = frac(r.summary.twin)
              return (
                <>
                  <Tile label="příběh" value={`${ok}/${all}`} sub="událostí potvrzeno v datech" good={all > 0 && ok === all} />
                  <Tile label="dvojče" value={`${hit}/${tAll}`} sub="falešných poplachů bez příběhu" good={hit === 0} />
                </>
              )
            })()}
            <DetectiveTiles s={run.detect?.score ?? null} />
          </div>
          {r.verification.length > 0 && (
            <details className="group">
              <summary className="cursor-pointer text-sm text-muted select-none hover:text-white">
                Ověření událost po události (naměřeno, 95% CI, z, SQL)
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

// ---- 6. Shrnutí ------------------------------------------------------------------------

export function SummarySection({ run }: { run: Run }) {
  const r = run.result
  return (
    <Section run={run} id="summary" title="Shrnutí">
      {r && (
        <div className="grid gap-3 text-sm">
          <p className="font-medium">
            Příběh {r.summary.story} potvrzeno, dvojče {r.summary.twin} falešných poplachů.
          </p>
          {r.narrative?.text && <p className="leading-relaxed whitespace-pre-line text-slate-300">{r.narrative.text}</p>}
          <p className="text-xs text-slate-500">Zvýrazněný prompt se šipkami ke grafům a tabulkám přibude v další verzi.</p>
        </div>
      )}
    </Section>
  )
}

export function Sections({ run, specName }: { run: Run; specName?: string }) {
  return (
    <>
      <PromptSection run={run} specName={specName} />
      <SpecSection run={run} />
      <DataSection run={run} />
      <DetectSection run={run} />
      <ScoreSection run={run} />
      <SummarySection run={run} />
    </>
  )
}
