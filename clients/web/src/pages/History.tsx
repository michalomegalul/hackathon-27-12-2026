import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router'
import { jobsOptions, type JobListItem } from '../api'
import { RunView } from '../run/RunView'
import { Sections } from '../run/sections'
import { useRun } from '../run/useRun'
import { draftOf, recallSent, rerunBody, useResend, useSend } from '../run/useSend'
import { isDemo, matchesQuery, mineIds } from '../run/jobs'
import { Alert, Badge, Card, JobStatusBadge, Spinner } from '../components/ui'
import { dateTimeCs, duration } from '../format'

type Filter = 'all' | 'mine' | 'demo'
const FILTERS: [Filter, string][] = [
  ['mine', 'moje'],
  ['all', 'všechny'],
  ['demo', 'ukázky'],
]

const btn = 'rounded-md border border-line px-2.5 py-1 text-xs text-slate-300 hover:border-slate-500 hover:text-white disabled:opacity-50'

/** "Znovu" (same prompt, new seed: a new run in Story) and "Upravit" (the prompt into the Story input). */
function Actions({ j }: { j: JobListItem }) {
  const send = useSend()
  const navigate = useNavigate()
  const again = useMutation({ mutationFn: async () => send.mutateAsync(await rerunBody(j.job_id)) })
  const edit = useMutation({
    mutationFn: () => draftOf(j.job_id),
    onSuccess: (draft) => void navigate('/', { state: { draft } }),
  })
  const err = again.error ?? edit.error
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <button className={btn} disabled={again.isPending} onClick={() => again.mutate()} title="Stejné zadání, nový seed: nová data">
        {again.isPending ? <Spinner /> : 'Znovu'}
      </button>
      <button className={btn} disabled={edit.isPending} onClick={() => edit.mutate()} title="Vloží zadání do pole ve Story">
        {edit.isPending ? <Spinner /> : 'Upravit'}
      </button>
      {err && <span className="text-xs text-rose-300">{err.message}</span>}
    </div>
  )
}

function Row({ j }: { j: JobListItem }) {
  return (
    <li className="grid gap-x-4 gap-y-2 rounded-xl border border-line bg-panel px-4 py-3 hover:border-slate-500 sm:grid-cols-[minmax(0,1fr)_auto]">
      <Link to={`/history/${j.job_id}`} className="grid min-w-0 gap-0.5">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="truncate font-medium">{j.title || 'Bez názvu'}</span>
          {isDemo(j) && <Badge t="blue">ukázka</Badge>}
        </div>
        <div className="truncate text-sm text-slate-400">{j.story_preview ?? <span className="italic text-slate-500">hotová specifikace, bez textu</span>}</div>
        <div className="truncate font-mono text-xs text-muted">
          {j.job_id} · {dateTimeCs(j.created)}
          {j.status === 'done' && ` · ${duration(j.elapsed_s)}`}
        </div>
      </Link>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 sm:justify-end">
        {j.summary && (
          <span className="text-sm text-muted">
            příběh <b className="text-slate-100 tabular-nums">{j.summary.story}</b>, dvojče <b className="text-slate-100 tabular-nums">{j.summary.twin}</b>
          </span>
        )}
        <JobStatusBadge s={j.status} />
        <Actions j={j} />
      </div>
    </li>
  )
}

// History "/history": every run (GET /v1/jobs?scope=all), newest first, with search and filters.
export function History() {
  const { data, error, isPending } = useQuery(jobsOptions('all'))
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const mine = useMemo(() => mineIds(), [])
  const jobs = useMemo(() => {
    const all = [...(data?.jobs ?? [])].sort((a, b) => b.created.localeCompare(a.created))
    return all.filter((j) => (filter === 'mine' ? mine.has(j.job_id) : filter === 'demo' ? isDemo(j) : true) && matchesQuery(j, q))
  }, [data, filter, q, mine])
  const count = (f: Filter) => (data?.jobs ?? []).filter((j) => (f === 'mine' ? mine.has(j.job_id) : f === 'demo' ? isDemo(j) : true)).length

  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold tracking-tight">History</h1>
        <Link to="/" className="text-sm text-muted hover:text-white">
          Nový příběh →
        </Link>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Hledat firmu nebo příběh…"
          aria-label="Hledat"
          className="min-w-0 flex-1 basis-full rounded-lg border border-line bg-panel px-3 py-2 text-[16px] placeholder:text-slate-500 focus:border-slate-500 focus:outline-none sm:max-w-sm sm:basis-auto sm:text-sm"
        />
        <div role="radiogroup" aria-label="Filtr" className="flex rounded-lg border border-line bg-panel p-0.5">
          {FILTERS.map(([f, label]) => (
            <button
              key={f}
              role="radio"
              aria-checked={filter === f}
              onClick={() => setFilter(f)}
              className={`rounded-md px-3 py-1.5 text-sm ${filter === f ? 'bg-white/[0.08] text-white' : 'text-muted hover:text-white'}`}
            >
              {label}
              {data && <span className="ml-1.5 text-xs tabular-nums text-slate-500">{count(f)}</span>}
            </button>
          ))}
        </div>
      </div>
      {error && <Alert>{error.message}</Alert>}
      {isPending && (
        <p className="text-muted">
          <Spinner /> Načítám…
        </p>
      )}
      {data && jobs.length === 0 && (
        <Card>
          <p className="text-muted">
            {data.jobs.length === 0
              ? 'Zatím žádné běhy.'
              : filter === 'mine' && !q
                ? 'Z tohoto prohlížeče jste zatím nic nespustili.'
                : 'Nic neodpovídá hledání.'}
          </p>
        </Card>
      )}
      {jobs.length > 0 && (
        <ul className="grid gap-2">
          {jobs.map((j) => (
            <Row key={j.job_id} j={j} />
          ))}
        </ul>
      )}
    </div>
  )
}

/** "/history/:id": an earlier run in the same view as Story, rebuilt from /input, /result and /detect. */
export function HistoryRun() {
  const { id } = useParams()
  const send = useSend() // a resent prompt is a new run: it opens in Story
  const run = useRun(id, useResend(id, send))
  const navigate = useNavigate()
  const again = useMutation({ mutationFn: async () => send.mutateAsync(await rerunBody(id!)) })
  const edit = useMutation({ mutationFn: () => draftOf(id!), onSuccess: (draft) => void navigate('/', { state: { draft } }) })
  const err = again.error ?? edit.error
  return (
    <RunView
      run={run}
      top={
        <div className="flex flex-wrap items-center gap-2 px-1">
          <Link to="/history" className="mr-auto text-sm text-muted hover:text-white">
            ← History
          </Link>
          {err && <span className="text-xs text-rose-300">{err.message}</span>}
          <button className={btn} disabled={!run.input || again.isPending} onClick={() => again.mutate()} title="Stejné zadání, nový seed">
            {again.isPending ? <Spinner /> : 'Znovu'}
          </button>
          <button className={btn} disabled={!run.input || edit.isPending} onClick={() => edit.mutate()} title="Vloží zadání do pole ve Story">
            {edit.isPending ? <Spinner /> : 'Upravit'}
          </button>
        </div>
      }
    >
      <Sections run={run} specName={recallSent(id)?.specName} />
    </RunView>
  )
}
