import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { ApiError, downloadZip, jobOptions, resultOptions, type Job, type Step } from '../api'
import { Alert, Card, JobStatusBadge, Spinner } from '../components/ui'
import { duration } from '../format'
import { Result } from '../components/Result'

function StepRow({ step, i, job }: { step: Step; i: number; job: Job }) {
  const running = job.status === 'running' && job.step_index === i + 1
  const failed = job.status === 'error' && !step.done && job.step_index === i + 1
  return (
    <li
      className={`flex items-start gap-3 rounded-lg px-3 py-2 ${
        running ? 'bg-accent/10 ring-1 ring-accent/40' : failed ? 'bg-rose-500/10 ring-1 ring-rose-500/40' : ''
      }`}
    >
      <span
        className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-bold ${
          step.done ? 'bg-accent text-slate-950' : running ? 'text-accent' : failed ? 'bg-rose-500 text-white' : 'bg-white/10 text-muted'
        }`}
      >
        {step.done ? '✓' : running ? <Spinner /> : failed ? '!' : i + 1}
      </span>
      <div className="min-w-0 flex-1">
        <div className={`text-sm ${step.done || running ? 'text-slate-100' : 'text-muted'} ${running ? 'font-medium' : ''}`}>
          {step.name}
        </div>
        {step.done && step.note && <div className="text-xs text-muted">{step.note}</div>}
      </div>
      <span className="shrink-0 text-xs tabular-nums text-muted">
        {step.done ? duration(step.s) : `~${duration(step.eta_s)}`}
      </span>
    </li>
  )
}

function Progress({ job }: { job: Job }) {
  const pct = Math.round(Math.min(1, Math.max(0, job.progress)) * 100)
  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <JobStatusBadge s={job.status} />
        <span className="text-sm text-slate-200">
          {job.status === 'queued'
            ? job.position > 0
              ? `Ve frontě, před vámi ${job.position} ${job.position === 1 ? 'úloha' : job.position < 5 ? 'úlohy' : 'úloh'}`
              : 'Ve frontě, jste na řadě'
            : job.status === 'running'
              ? `Krok ${job.step_index}/${job.steps_total}: ${job.step ?? ''}`
              : job.status === 'done'
                ? `Hotovo za ${duration(job.elapsed_s)}`
                : 'Úloha skončila chybou'}
        </span>
        {(job.status === 'queued' || job.status === 'running') && (
          <span className="ml-auto text-sm tabular-nums text-accent">zbývá ~{job.eta_s} s</span>
        )}
      </div>
      <div
        className="h-2.5 overflow-hidden rounded-full bg-white/10"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
      >
        <div
          className={`h-full rounded-full transition-[width] duration-700 ease-out ${job.status === 'error' ? 'bg-rose-500' : 'bg-accent'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <ol className="mt-4 grid gap-1">
        {job.steps.map((s, i) => (
          <StepRow key={s.name} step={s} i={i} job={job} />
        ))}
      </ol>
      {job.status === 'error' && job.error && (
        <div className="mt-3">
          <Alert>{job.error}</Alert>
        </div>
      )}
    </Card>
  )
}

function DownloadButton({ id }: { id: string }) {
  const dl = useMutation({ mutationFn: () => downloadZip(id) })
  return (
    <div className="grid gap-1">
      <button
        onClick={() => dl.mutate()}
        disabled={dl.isPending}
        className="inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 font-medium text-slate-950 hover:brightness-110 disabled:opacity-60"
      >
        {dl.isPending ? <Spinner /> : '↓'} Stáhnout data (ZIP)
      </button>
      {dl.error && <span className="text-xs text-rose-300">{dl.error.message}</span>}
    </div>
  )
}

export function JobPage() {
  const { id = '' } = useParams()
  const job = useQuery(jobOptions(id))
  const done = job.data?.status === 'done'
  const result = useQuery(resultOptions(id, done))
  const [copied, setCopied] = useState(false)

  if (job.error) {
    const notFound = job.error instanceof ApiError && job.error.status === 404
    return (
      <div className="grid gap-4">
        <Alert>{notFound ? 'Úloha nenalezena (nebo není vaše).' : job.error.message}</Alert>
        <Link to="/jobs" className="text-accent hover:underline">
          ← Moje úlohy
        </Link>
      </div>
    )
  }
  if (!job.data)
    return (
      <p className="text-muted">
        <Spinner /> Načítám…
      </p>
    )

  return (
    <div className="grid grid-cols-1 gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="mr-auto min-w-0">
          <Link to="/jobs" className="text-sm text-muted hover:text-white">
            ← Moje úlohy
          </Link>
          <h1 className="flex items-center gap-2 truncate font-mono text-base text-slate-200 sm:text-lg">
            {id}
            <button
              className="rounded px-1.5 text-xs text-muted hover:bg-white/10 hover:text-white"
              title="Zkopírovat odkaz"
              onClick={() => {
                void navigator.clipboard?.writeText(location.href).then(() => {
                  setCopied(true)
                  setTimeout(() => setCopied(false), 1500)
                })
              }}
            >
              {copied ? 'zkopírováno' : 'odkaz'}
            </button>
          </h1>
        </div>
        {done && <DownloadButton id={id} />}
      </div>

      <Progress job={job.data} />

      {done &&
        (result.data ? (
          <Result r={result.data} />
        ) : result.error ? (
          <Alert>{result.error.message}</Alert>
        ) : (
          <p className="text-muted">
            <Spinner /> Načítám výsledek…
          </p>
        ))}
    </div>
  )
}
