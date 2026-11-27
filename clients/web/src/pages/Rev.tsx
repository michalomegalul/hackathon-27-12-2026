// Rev story "/rev" and "/rev/:id": data → story. Pick a finished database (or attach a .yaml spec,
// which runs as a job first), the detective starts by itself (useRun), and Shrnutí sets the
// detective's story against the original prompt (RevSummary). Same run view as Story.
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router'
import { jobsOptions, type JobListItem } from '../api'
import { RunView } from '../run/RunView'
import { Sections } from '../run/sections'
import { useRun } from '../run/useRun'
import { recallSent, useResend, useSend } from '../run/useSend'
import { isDemo, matchesQuery } from '../run/jobs'
import { Alert, Badge, Spinner } from '../components/ui'
import { dateTimeCs } from '../format'

function Pick({ j, onPick }: { j: JobListItem; onPick: () => void }) {
  return (
    <li>
      <button
        onClick={onPick}
        className="grid w-full gap-0.5 rounded-lg border border-line bg-bg/40 px-3 py-2 text-left hover:border-slate-500 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-x-3"
      >
        <span className="grid min-w-0 gap-0.5">
          <span className="flex min-w-0 items-baseline gap-2">
            <span className="truncate font-medium">{j.title || 'Bez názvu'}</span>
            {isDemo(j) && <Badge t="blue">ukázka</Badge>}
          </span>
          <span className="truncate text-xs text-muted">
            {j.story_preview ?? 'hotová specifikace'} · {dateTimeCs(j.created)}
          </span>
        </span>
        {j.summary && (
          <span className="text-xs text-muted">
            příběh <b className="text-slate-200 tabular-nums">{j.summary.story}</b>
          </span>
        )}
      </button>
    </li>
  )
}

/** The database picker: finished runs (demos pinned on top), search, or a .yaml spec to run first. */
function Picker() {
  const { data, error, isPending } = useQuery(jobsOptions('all'))
  const [q, setQ] = useState('')
  const navigate = useNavigate()
  const send = useSend('/rev')
  const file = useRef<HTMLInputElement>(null)
  const [fileErr, setFileErr] = useState<string | null>(null)
  const jobs = useMemo(
    () =>
      (data?.jobs ?? [])
        .filter((j) => j.status === 'done' && matchesQuery(j, q))
        .sort((a, b) => Number(isDemo(b)) - Number(isDemo(a)) || b.created.localeCompare(a.created)),
    [data, q],
  )
  const demos = jobs.filter(isDemo)
  const rest = jobs.filter((j) => !isDemo(j))

  return (
    <div className="grid gap-4 rounded-xl border border-line bg-panel p-4 sm:p-5">
      <div>
        <h1 className="text-lg font-semibold">Rev story: z dat příběh</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Vyberte hotovou databázi. Detektiv v ní naslepo hledá, co se firmě stalo, a Shrnutí jeho příběh porovná s původním zadáním: co našel, co mu uteklo a
          co si vymyslel.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Hledat podle firmy nebo příběhu…"
          aria-label="Hledat databázi"
          className="min-w-0 flex-1 rounded-lg border border-line bg-bg px-3 py-2 text-[16px] placeholder:text-slate-500 focus:border-slate-500 focus:outline-none sm:text-sm"
        />
        <button
          onClick={() => file.current?.click()}
          disabled={send.isPending}
          className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 text-sm text-slate-300 hover:border-slate-500 hover:text-white disabled:opacity-50"
          title="Přiložit specifikaci (.yaml): nejdřív se z ní vyrobí data, pak detektiv"
        >
          {send.isPending ? (
            <Spinner />
          ) : (
            <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M21 11.5 12.6 19.9a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8" />
            </svg>
          )}{' '}
          Přiložit .yaml
        </button>
        <input
          ref={file}
          type="file"
          accept=".yaml,.yml,application/yaml,text/yaml"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            e.target.value = ''
            if (!f) return
            setFileErr(null)
            if (!/\.ya?ml$/i.test(f.name)) return setFileErr('Přiložte soubor .yaml se specifikací.')
            void f.text().then((yaml) => send.mutate({ body: { spec_yaml: yaml }, specName: f.name }))
          }}
        />
      </div>
      {(fileErr || send.error) && <Alert>{fileErr ?? send.error?.message}</Alert>}
      {error && <Alert>{error.message}</Alert>}
      {isPending && (
        <p className="text-sm text-muted">
          <Spinner /> Načítám databáze…
        </p>
      )}
      {data && jobs.length === 0 && <p className="text-sm text-muted">{q ? 'Nic neodpovídá hledání.' : 'Zatím žádná hotová databáze.'}</p>}
      {demos.length > 0 && (
        <div className="grid gap-1.5">
          <h2 className="text-xs text-muted">Ukázky</h2>
          <ul className="grid gap-1.5 md:grid-cols-2">
            {demos.map((j) => (
              <Pick key={j.job_id} j={j} onPick={() => void navigate(`/rev/${j.job_id}`)} />
            ))}
          </ul>
        </div>
      )}
      {rest.length > 0 && (
        <div className="grid gap-1.5">
          <h2 className="text-xs text-muted">Další databáze</h2>
          <ul className="grid max-h-[26rem] gap-1.5 overflow-y-auto pr-1 md:grid-cols-2">
            {rest.map((j) => (
              <Pick key={j.job_id} j={j} onPick={() => void navigate(`/rev/${j.job_id}`)} />
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export function Rev() {
  const { id } = useParams()
  const send = useSend('/rev')
  const run = useRun(id, useResend(id, send))
  const { data } = useQuery({ ...jobsOptions('all'), enabled: Boolean(id) })
  const title = data?.jobs.find((j) => j.job_id === id)?.title

  if (!id) {
    const idle = { ...run, status: { ...run.status, detail: 'Vyberte databázi nebo přiložte specifikaci.' } }
    return (
      <RunView run={idle} top={<Picker />}>
        <Sections run={idle} mode="rev" />
      </RunView>
    )
  }
  return (
    <RunView
      run={run}
      top={
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-1">
          <Link to="/rev" className="text-sm text-muted hover:text-white">
            ← Vybrat jinou databázi
          </Link>
          {title && <span className="text-sm font-medium">{title}</span>}
        </div>
      }
    >
      <Sections run={run} specName={recallSent(id)?.specName} mode="rev" />
    </RunView>
  )
}
