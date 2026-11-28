// Rev story "/rev" and "/rev/:id": data → story. Its input is the data: drop the download ZIP of a
// run (or its CSVs), the browser fingerprints it and the API finds the run that made it (run/
// dataFile.ts, POST /v1/jobs/match); demos and earlier runs can be opened directly. "Run again"
// makes a new run of the same prompt with a new seed even when identical runs exist. On /rev/:id
// the detective starts by itself (useRun), and Summary sets the
// detective's story against the original prompt (RevSummary). Same run view as Story, in the
// order it happens here (REV_ORDER): data, detective, score, then the prompt and the summary.
import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router'
import { jobsOptions, matchJobs, type JobListItem, type MatchedJob } from '../api'
import { RunView } from '../run/RunView'
import { Sections } from '../run/sections'
import { REV_ORDER, useRun } from '../run/useRun'
import { fingerprint } from '../run/dataFile'
import { recallSent, rerunBody, useResend, useSend } from '../run/useSend'
import { isDemo, matchesQuery } from '../run/jobs'
import { forgetLast, useRememberLast } from '../run/lastRun'
import { Alert, Badge, Spinner } from '../components/ui'
import { dateTimeCs } from '../format'

function Pick({ j, onPick }: { j: JobListItem; onPick: () => void }) {
  return (
    <li>
      <button
        onClick={onPick}
        className="grid w-full gap-0.5 border-b border-line px-1 py-2 text-left hover:bg-white/[0.03] sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-x-3"
      >
        <span className="grid min-w-0 gap-0.5">
          <span className="flex min-w-0 items-baseline gap-2">
            <span className="truncate font-medium">{j.title || 'Untitled'}</span>
            {isDemo(j) && <Badge t="blue">demo</Badge>}
          </span>
          <span className="truncate text-xs text-muted">
            {j.story_preview ?? 'ready-made spec'} · {dateTimeCs(j.created)}
          </span>
        </span>
        {j.summary && (
          <span className="text-xs text-muted">
            story <b className="text-slate-200 tabular-nums">{j.summary.story}</b>
          </span>
        )}
      </button>
    </li>
  )
}

const btn = 'border border-line px-2.5 py-1 text-xs text-slate-300 hover:border-slate-500 hover:text-white disabled:opacity-50'

/** "Run again" in Rev story: the same prompt (or spec) as a new run with a new seed, opened here, so
 *  the detective gets fresh data even when an identical run exists. */
function useRunAgain() {
  const send = useSend('/rev')
  return useMutation({ mutationFn: async (id: string) => send.mutateAsync(await rerunBody(id)) })
}

type Drop =
  | { phase: 'idle' }
  | { phase: 'reading'; msg: string }
  | { phase: 'matched'; jobs: MatchedJob[] }
  | { phase: 'error'; msg: string }

/** Rev story's input: drop the data. The browser reads the ZIP itself (run/dataFile.ts) and asks
 *  the API which run made these data; one match opens it, several are listed, none is said. */
function DropData() {
  const navigate = useNavigate()
  const file = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [st, setSt] = useState<Drop>({ phase: 'idle' })
  const busy = st.phase === 'reading'
  const again = useRunAgain()

  async function take(list: FileList | null) {
    const files = [...(list ?? [])]
    if (!files.length || busy) return
    try {
      setSt({ phase: 'reading', msg: 'Reading the data…' })
      const fp = await fingerprint(files, (msg) => setSt({ phase: 'reading', msg }))
      setSt({ phase: 'reading', msg: 'Looking for the run that made these data…' })
      const { jobs } = await matchJobs(fp)
      if (jobs.length === 1) return void navigate(`/rev/${jobs[0].job_id}`)
      setSt({ phase: 'matched', jobs })
    } catch (e) {
      setSt({ phase: 'error', msg: e instanceof Error ? e.message : String(e) })
    }
  }

  return (
    <div className="grid gap-3">
      <button
        type="button"
        onClick={() => file.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setOver(false)
          void take(e.dataTransfer.files)
        }}
        disabled={busy}
        className={`grid min-h-40 place-items-center border border-dashed px-4 py-8 text-center transition-colors ${
          over ? 'border-accent bg-accent/[0.06]' : 'border-line hover:border-slate-500 hover:bg-white/[0.02]'
        }`}
      >
        {busy ? (
          <span className="text-sm text-slate-300">
            <Spinner /> {st.msg}
          </span>
        ) : (
          <span className="grid gap-1">
            <span className="font-medium">Drop the data here</span>
            <span className="text-sm text-muted">the ZIP you downloaded from a run, or its customers.csv and orders.csv · or click to choose</span>
          </span>
        )}
      </button>
      <input
        ref={file}
        type="file"
        multiple
        accept=".zip,.csv,application/zip,text/csv"
        className="hidden"
        onChange={(e) => {
          const files = e.target.files
          void take(files).finally(() => (e.target.value = ''))
        }}
      />
      <p className="text-[11px] text-slate-500">The file stays in your browser: it only counts the customers and orders and sends a sample of customers to find the run.</p>
      {st.phase === 'error' && <Alert>{st.msg}</Alert>}
      {st.phase === 'matched' &&
        (st.jobs.length === 0 ? (
          <Alert>
            These data were not made here, or by a run you cannot see. Rev story compares the detective's story with the prompt that made the data, so it
            needs a run of this site.
          </Alert>
        ) : (
          <div className="grid gap-1.5">
            <h2 className="text-xs text-muted">{st.jobs.length} runs made exactly these data (the same spec and seed); pick one</h2>
            <ul className="grid gap-1.5 md:grid-cols-2">
              {st.jobs.map((j) => (
                <li key={j.job_id}>
                  <button
                    onClick={() => void navigate(`/rev/${j.job_id}`)}
                    className="grid w-full gap-0.5 border-b border-line px-1 py-2 text-left hover:bg-white/[0.03]"
                  >
                    <span className="truncate font-medium">{j.title || 'Untitled'}</span>
                    <span className="truncate text-xs text-muted">
                      {j.story_preview ?? 'ready-made spec'} · {dateTimeCs(j.created)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-center gap-2">
              <button className={btn} disabled={again.isPending} onClick={() => again.mutate(st.jobs[0].job_id)} title="Same prompt, new seed: new data">
                {again.isPending ? <Spinner /> : 'Or generate a new run (new seed)'}
              </button>
              {again.error && <span className="text-xs text-rose-300">{again.error.message}</span>}
            </div>
          </div>
        ))}
    </div>
  )
}

/** Story takes a prompt, Rev story takes data: the drop zone first, the demos as a quick start,
 *  earlier runs folded under them. */
function Picker() {
  const { data, error, isPending } = useQuery(jobsOptions('all'))
  const [q, setQ] = useState('')
  const navigate = useNavigate()
  const jobs = useMemo(
    () =>
      (data?.jobs ?? [])
        .filter((j) => j.status === 'done' && matchesQuery(j, q))
        .sort((a, b) => Number(isDemo(b)) - Number(isDemo(a)) || b.created.localeCompare(a.created)),
    [data, q],
  )
  const demos = (data?.jobs ?? []).filter((j) => j.status === 'done' && isDemo(j))
  const rest = jobs.filter((j) => !isDemo(j))

  return (
    <div className="grid gap-5 border-t border-line pt-5">
      <div>
        <h1 className="text-lg font-semibold">Rev story: data to story</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Story turns a prompt into data; Rev story goes back. Give it the data: the detective searches them blind for what happened to the company, and the
          Summary sets its story against the prompt that made them: what it found, what it missed and what it found on top.
        </p>
      </div>
      <DropData />
      {error && <Alert>{error.message}</Alert>}
      {demos.length > 0 && (
        <div className="grid gap-1.5">
          <h2 className="text-xs text-muted">No file at hand? Start from a demo</h2>
          <ul className="grid gap-1.5 md:grid-cols-2">
            {demos.map((j) => (
              <Pick key={j.job_id} j={j} onPick={() => void navigate(`/rev/${j.job_id}`)} />
            ))}
          </ul>
        </div>
      )}
      <details className="grid gap-2">
        <summary className="cursor-pointer text-xs text-muted select-none hover:text-white">Or open an earlier run</summary>
        <div className="mt-2 grid gap-2">
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by company or story…"
            aria-label="Search databases"
            className="min-w-0 border border-line bg-bg px-3 py-2 text-[16px] placeholder:text-slate-500 focus:border-slate-500 focus:outline-none sm:text-sm"
          />
          {isPending && (
            <p className="text-sm text-muted">
              <Spinner /> Loading databases…
            </p>
          )}
          {data && rest.length === 0 && <p className="text-sm text-muted">{q ? 'Nothing matches the search.' : 'No finished database yet.'}</p>}
          {rest.length > 0 && (
            <ul className="grid max-h-[26rem] gap-1.5 overflow-y-auto pr-1 md:grid-cols-2">
              {rest.map((j) => (
                <Pick key={j.job_id} j={j} onPick={() => void navigate(`/rev/${j.job_id}`)} />
              ))}
            </ul>
          )}
        </div>
      </details>
    </div>
  )
}

export function Rev() {
  const { id } = useParams()
  const send = useSend('/rev')
  const run = useRun(id, useResend(id, send))
  const again = useRunAgain()
  const { data } = useQuery({ ...jobsOptions('all'), enabled: Boolean(id) })
  const title = data?.jobs.find((j) => j.job_id === id)?.title
  useRememberLast('rev', id)

  if (!id) {
    return <Picker />
  }
  return (
    <RunView
      run={run}
      order={REV_ORDER}
      top={
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1">
          <Link to="/rev" onClick={() => forgetLast('rev')} className="text-sm text-muted hover:text-white">
            ← Pick another database
          </Link>
          {title && <span className="mr-auto text-sm font-medium">{title}</span>}
          {again.error && <span className="text-xs text-rose-300">{again.error.message}</span>}
          <button
            className={`${btn} ${title ? '' : 'ml-auto'}`}
            disabled={!run.input || again.isPending}
            onClick={() => again.mutate(id)}
            title="The same prompt as a new run with a new seed: new data, the detective runs on them"
          >
            {again.isPending ? <Spinner /> : 'Run again with a new seed'}
          </button>
        </div>
      }
    >
      <Sections run={run} specName={recallSent(id)?.specName} mode="rev" />
    </RunView>
  )
}
