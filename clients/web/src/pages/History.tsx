import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { jobsOptions } from '../api'
import { RunView } from '../run/RunView'
import { Sections } from '../run/sections'
import { useRun } from '../run/useRun'
import { recallSent } from '../run/useSend'
import { Alert, Card, JobStatusBadge, Spinner } from '../components/ui'
import { dateTimeCs, duration } from '../format'

// History "/history": every run (GET /v1/jobs?scope=all; Prompt 3 adds search and filters).
export function History() {
  const { data, error, isPending } = useQuery(jobsOptions('all'))

  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold tracking-tight">History</h1>
        <Link to="/" className="text-sm text-muted hover:text-white">
          Nový příběh →
        </Link>
      </div>
      {error && <Alert>{error.message}</Alert>}
      {isPending && (
        <p className="text-muted">
          <Spinner /> Načítám…
        </p>
      )}
      {data && data.jobs.length === 0 && (
        <Card>
          <p className="text-muted">Zatím žádné úlohy.</p>
        </Card>
      )}
      {data && data.jobs.length > 0 && (
        <ul className="grid gap-2">
          {data.jobs.map((j) => (
            <li key={j.job_id}>
              <Link
                to={`/history/${j.job_id}`}
                className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 rounded-xl border border-line bg-panel px-4 py-3 hover:border-slate-500 sm:grid-cols-[1fr_auto_auto]"
              >
                <div className="min-w-0">
                  <div className="truncate font-medium">{j.title || 'Bez názvu'}</div>
                  {j.story_preview && <div className="truncate text-sm text-slate-400">{j.story_preview}</div>}
                  <div className="truncate font-mono text-xs text-muted">
                    {j.job_id} · {dateTimeCs(j.created)}
                    {j.status === 'done' && ` · ${duration(j.elapsed_s)}`}
                  </div>
                </div>
                <div className="col-start-1 text-sm text-muted sm:col-start-auto">
                  {j.summary ? (
                    <>
                      příběh <b className="text-slate-100">{j.summary.story}</b>, dvojče{' '}
                      <b className="text-slate-100">{j.summary.twin}</b>
                    </>
                  ) : null}
                </div>
                <div className="col-start-2 row-span-2 row-start-1 sm:row-span-1 sm:col-start-auto">
                  <JobStatusBadge s={j.status} />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** "/history/:id": an earlier run in the same view as Story, rebuilt from /input, /result and /detect. */
export function HistoryRun() {
  const { id } = useParams()
  const run = useRun(id)
  return (
    <RunView
      run={run}
      top={
        <Link to="/history" className="px-1 text-sm text-muted hover:text-white">
          ← History
        </Link>
      }
    >
      <Sections run={run} specName={recallSent(id)?.specName} />
    </RunView>
  )
}
