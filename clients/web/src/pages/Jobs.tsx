import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { jobsOptions } from '../api'
import { Alert, Card, JobStatusBadge, Spinner } from '../components/ui'
import { dateTimeCs, duration } from '../format'

export function Jobs() {
  const { data, error, isPending } = useQuery(jobsOptions())

  return (
    <div className="grid gap-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold tracking-tight">Moje úlohy</h1>
        <Link to="/" className="text-sm text-accent hover:underline">
          + Nová úloha
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
                to={`/jobs/${j.job_id}`}
                className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 rounded-xl border border-line bg-panel px-4 py-3 hover:border-accent/60 sm:grid-cols-[1fr_auto_auto]"
              >
                <div className="min-w-0">
                  <div className="truncate font-medium">{j.title || 'Bez názvu'}</div>
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
