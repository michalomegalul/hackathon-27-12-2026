import { Fragment, useState } from 'react'
import { Link } from 'react-router'
import type { JobResult, VerificationRow } from '../api'
import { CONTROL_CS, KPI_CS, dateCs, num, withUnit } from '../format'
import { Badge, VerificationBadge } from './ui'
import type { SqlCheck } from '../pages/DataPage'

/** "4/4" → [4, 4] */
const frac = (s: string) => s.split('/').map(Number) as [number, number]

export function SummaryTiles({ r }: { r: JobResult }) {
  const [sOk, sAll] = frac(r.summary.story)
  const [tHit] = frac(r.summary.twin)
  const storyGood = sAll > 0 && sOk === sAll
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className={`rounded-xl border p-4 ${storyGood ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-amber-500/40 bg-amber-500/10'}`}>
        <div className="text-xs uppercase tracking-wide text-muted">příběh</div>
        <div className="text-3xl font-semibold tabular-nums">{r.summary.story}</div>
        <div className="text-xs text-muted">událostí potvrzeno v datech</div>
      </div>
      <div className={`rounded-xl border p-4 ${tHit === 0 ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-rose-500/40 bg-rose-500/10'}`}>
        <div className="text-xs uppercase tracking-wide text-muted">dvojče</div>
        <div className="text-3xl font-semibold tabular-nums">{r.summary.twin}</div>
        <div className="text-xs text-muted">„nálezů“ v datech bez příběhu (má být 0)</div>
      </div>
    </div>
  )
}

const ci = (v: VerificationRow) =>
  v.ci ? `${withUnit(v.ci[0], v.measured_unit)} … ${withUnit(v.ci[1], v.measured_unit)}` : '–'

function Twin({ v }: { v: VerificationRow }) {
  if (v.twin_confirmed === null && v.twin_measured === null) return <span className="text-muted">–</span>
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className="tabular-nums">{withUnit(v.twin_measured, v.measured_unit)}</span>
      {v.twin_confirmed ? <Badge t="red">falešný nález</Badge> : <Badge t="green">nic</Badge>}
    </span>
  )
}

function Detail({ v }: { v: VerificationRow }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="grid grid-cols-1 gap-3 text-sm">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt className="text-muted">Kontrola</dt>
        <dd>
          {CONTROL_CS[v.control_mode] ?? v.control_mode}
          {v.control && <span className="ml-1 break-all font-mono text-xs text-muted">({v.control})</span>}
        </dd>
        <dt className="text-muted">Metrika</dt>
        <dd className="break-all font-mono text-xs leading-5">{v.metric}</dd>
        {v.expected_size !== null && (
          <>
            <dt className="text-muted">Očekáváno</dt>
            <dd className="tabular-nums">{withUnit(v.expected_size, v.measured_unit)}</dd>
          </>
        )}
        {v.p_placebo !== null && (
          <>
            <dt className="text-muted">p (placebo)</dt>
            <dd className="tabular-nums">{num(v.p_placebo, 2)}</dd>
          </>
        )}
        {v.twin_z !== null && (
          <>
            <dt className="text-muted">z dvojčete</dt>
            <dd className="tabular-nums">{num(v.twin_z)}</dd>
          </>
        )}
        {v.reason && (
          <>
            <dt className="text-muted">Proč</dt>
            <dd>{v.reason}</dd>
          </>
        )}
        {v.sql_matches !== null && (
          <>
            <dt className="text-muted">SQL</dt>
            <dd>{v.sql_matches ? 'dává stejné číslo jako ověření' : <span className="text-amber-300">nedává stejné číslo</span>}</dd>
          </>
        )}
      </dl>
      {v.sql ? (
        <div className="relative">
          <button
            className="absolute right-2 top-2 rounded bg-white/10 px-2 py-0.5 text-xs hover:bg-white/20"
            onClick={() => {
              void navigator.clipboard?.writeText(v.sql ?? '').then(() => {
                setCopied(true)
                setTimeout(() => setCopied(false), 1500)
              })
            }}
          >
            {copied ? 'zkopírováno' : 'kopírovat'}
          </button>
          <pre className="max-h-96 overflow-auto rounded-lg bg-bg p-3 pr-20 font-mono text-xs leading-relaxed text-slate-300">
            {v.sql}
          </pre>
        </div>
      ) : (
        <p className="text-muted">Bez SQL: událost nešla ověřit.</p>
      )}
    </div>
  )
}

/** Opens /run/:id/data with this row's SQL pre-filled and run, and its sql_result to compare against. */
function RunSql({ jobId, v, className = '' }: { jobId: string; v: VerificationRow; className?: string }) {
  if (!v.sql) return null
  const state: SqlCheck = { sql: v.sql, label: `${v.event_id} · ${KPI_CS[v.kpi] ?? v.kpi}`, expect: v.sql_result }
  return (
    <Link
      to={`/run/${jobId}/data`}
      state={state}
      onClick={(e) => e.stopPropagation()}
      title="Spustí SQL tohoto řádku nad daty úlohy a porovná výsledek"
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md bg-accent/15 px-2 py-1 text-xs font-medium text-accent ring-1 ring-inset ring-accent/30 hover:bg-accent/25 ${className}`}
    >
      ▶ Spustit SQL
    </Link>
  )
}

const Chevron = ({ open }: { open: boolean }) => (
  <span className={`inline-block text-muted transition-transform ${open ? 'rotate-90' : ''}`}>›</span>
)

export function VerificationTable({ rows, jobId }: { rows: VerificationRow[]; jobId: string }) {
  // one event can give several rows (e.g. tickets and stockouts), so rows are keyed by index
  const [open, setOpen] = useState<Set<number>>(new Set())
  const toggle = (id: number) =>
    setOpen((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })

  return (
    <>
      {/* phones: one card per event */}
      <ul className="grid grid-cols-1 gap-3 md:hidden">
        {rows.map((v, i) => (
          <li key={i} className="rounded-lg border border-line bg-bg/40">
            <button className="grid w-full grid-cols-1 gap-2 p-3 text-left" onClick={() => toggle(i)} aria-expanded={open.has(i)}>
              <div className="flex items-start gap-2">
                <span className="font-mono text-xs text-muted">{v.event_id}</span>
                <span className="flex-1 text-sm">{v.claim_cs}</span>
                <VerificationBadge s={v.status} />
              </div>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                <dt className="text-muted">KPI</dt>
                <dd>{KPI_CS[v.kpi] ?? v.kpi}</dd>
                <dt className="text-muted">Cíl · od</dt>
                <dd>
                  <span className="break-all font-mono">{v.target || 'všichni'}</span> · {dateCs(v.start)}
                </dd>
                <dt className="text-muted">Příběh → naměřeno</dt>
                <dd className="tabular-nums">
                  {withUnit(v.story_size, v.story_unit)} → <b>{withUnit(v.measured, v.measured_unit)}</b>
                </dd>
                <dt className="text-muted">95% CI · z</dt>
                <dd className="tabular-nums">
                  {ci(v)} · {num(v.z)}
                </dd>
                <dt className="text-muted">Dvojče</dt>
                <dd>
                  <Twin v={v} />
                </dd>
              </dl>
              {v.status === 'not_testable' && v.reason && <p className="text-xs text-muted">{v.reason}</p>}
              <span className="text-xs text-accent">
                <Chevron open={open.has(i)} /> {open.has(i) ? 'skrýt SQL' : 'zobrazit SQL a detail'}
              </span>
            </button>
            {v.sql && (
              <div className="px-3 pb-3">
                <RunSql jobId={jobId} v={v} />
              </div>
            )}
            {open.has(i) && (
              <div className="border-t border-line p-3">
                <Detail v={v} />
              </div>
            )}
          </li>
        ))}
      </ul>

      {/* tablets and up: a real table */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="w-6 py-2" />
              <th className="py-2 pr-3 font-medium">Událost</th>
              <th className="py-2 pr-3 font-medium">KPI</th>
              <th className="py-2 pr-3 font-medium">Cíl</th>
              <th className="py-2 pr-3 text-right font-medium">Příběh</th>
              <th className="py-2 pr-3 text-right font-medium">Naměřeno</th>
              <th className="py-2 pr-3 text-right font-medium">95% CI</th>
              <th className="py-2 pr-3 text-right font-medium">z</th>
              <th className="py-2 pr-3 font-medium">Stav</th>
              <th className="py-2 pr-3 font-medium">Dvojče</th>
              <th className="py-2 font-medium">
                <span className="sr-only">SQL</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((v, i) => {
              const isOpen = open.has(i)
              return (
                <Fragment key={i}>
                  <tr
                    className="cursor-pointer border-b border-line/60 align-top hover:bg-white/[0.03]"
                    onClick={() => toggle(i)}
                    aria-expanded={isOpen}
                  >
                    <td className="py-2.5">
                      <Chevron open={isOpen} />
                    </td>
                    <td className="min-w-64 py-2.5 pr-3">
                      <div className="font-mono text-xs text-muted">
                        {v.event_id} · od {dateCs(v.start)}
                      </div>
                      <div>{v.claim_cs}</div>
                      {v.status === 'not_testable' && v.reason && <div className="mt-0.5 text-xs text-muted">{v.reason}</div>}
                    </td>
                    <td className="py-2.5 pr-3">{KPI_CS[v.kpi] ?? v.kpi}</td>
                    <td className="py-2.5 pr-3 font-mono text-xs leading-5">{v.target || 'všichni'}</td>
                    <td className="whitespace-nowrap py-2.5 pr-3 text-right tabular-nums text-muted">{withUnit(v.story_size, v.story_unit)}</td>
                    <td className="whitespace-nowrap py-2.5 pr-3 text-right font-medium tabular-nums">{withUnit(v.measured, v.measured_unit)}</td>
                    <td className="whitespace-nowrap py-2.5 pr-3 text-right text-xs tabular-nums text-muted">{ci(v)}</td>
                    <td className="py-2.5 pr-3 text-right tabular-nums">{num(v.z)}</td>
                    <td className="py-2.5 pr-3">
                      <VerificationBadge s={v.status} />
                    </td>
                    <td className="py-2.5 pr-3 text-xs">
                      <Twin v={v} />
                    </td>
                    <td className="py-2 text-right">
                      <RunSql jobId={jobId} v={v} />
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="border-b border-line/60 bg-bg/40">
                      <td />
                      <td colSpan={10} className="py-3 pr-3">
                        <Detail v={v} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

/** Events the simulator cannot model, and the pipeline's warnings. */
export function Notes({ r }: { r: JobResult }) {
  if (!r.untested.length && !r.warnings.length) return null
  return (
    <div className="grid gap-3">
      {r.untested.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Neověřitelné události</h3>
          <ul className="grid gap-1.5 text-sm">
            {r.untested.map((u, i) => (
              <li key={i} className="rounded-lg border border-line px-3 py-2">
                <span className="mr-2 font-mono text-xs text-muted">{u.event_id}</span>
                {u.claim_cs || u.type}
                <div className="text-xs text-muted">{u.reason}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {r.warnings.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">Upozornění</h3>
          <ul className="grid gap-1 text-sm text-amber-100/90">
            {r.warnings.map((w, i) => (
              <li key={i}>⚠ {w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
