// The whole run in one hook: poll the job, fetch /result when it is done, start the detective
// automatically, poll it, and derive the six stages the sidebar and the sections show.
// API steps → stages: step 1 (specifikace) is Spec, steps 2–5 (simulace, dvojče, ověření,
// český příběh) are Data. The user never clicks "next".
import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  detectOptions,
  inputOptions,
  isStatus,
  jobOptions,
  resultOptions,
  startDetect,
  type Detect,
  type Job,
  type JobInput,
  type JobResult,
} from '../api'
import { duration } from '../format'

export type StageId = 'prompt' | 'spec' | 'data' | 'detect' | 'score' | 'summary'
export type StageState = 'pending' | 'running' | 'done' | 'error'

export const STAGES: { id: StageId; label: string }[] = [
  { id: 'prompt', label: 'Prompt' },
  { id: 'spec', label: 'Spec' },
  { id: 'data', label: 'Data' },
  { id: 'detect', label: 'Detektiv' },
  { id: 'score', label: 'Skóre' },
  { id: 'summary', label: 'Shrnutí' },
]

export const sectionId = (s: StageId) => `s-${s}`

const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches

export function scrollToStage(id: StageId) {
  document.getElementById(sectionId(id))?.scrollIntoView({ behavior: reduceMotion() ? 'auto' : 'smooth', block: 'start' })
}


/** The detective takes about 40 s (API.md); there is no eta for it, so estimate from that. */
const DETECT_S = 40

export type Stage = { state: StageState; error?: string; retry?: () => void; sub?: string }

export type Status = {
  title: string
  detail?: string
  progress: number | null // 0..1, null = no bar
  etaS: number | null
  position: number | null // jobs ahead in the queue
  tone: 'idle' | 'busy' | 'done' | 'error'
}

export type Run = {
  id: string | undefined
  job?: Job
  input?: JobInput
  result?: JobResult
  detect?: Detect
  stages: Record<StageId, Stage>
  status: Status
}

const pending: Stage = { state: 'pending' }

function idleRun(): Run {
  const stages = Object.fromEntries(STAGES.map((s) => [s.id, pending])) as Record<StageId, Stage>
  return {
    id: undefined,
    stages,
    status: { title: 'Připraveno', detail: 'Napište firmu a příběh do pole dole.', progress: null, etaS: null, position: null, tone: 'idle' },
  }
}

/** `retryJob` resends the prompt (a failed job cannot be resumed): the page creates a new run. */
export function useRun(id: string | undefined, retryJob?: () => void): Run {
  const qc = useQueryClient()
  const job = useQuery({ ...jobOptions(id ?? ''), enabled: Boolean(id) })
  const input = useQuery({ ...inputOptions(id ?? ''), enabled: Boolean(id) })
  const j = job.data
  const jobDone = j?.status === 'done'
  const result = useQuery(resultOptions(id ?? '', Boolean(id) && jobDone))

  // the detective starts by itself once the result is in (POST is idempotent: an existing run is returned)
  const start = useMutation({
    mutationFn: (jid: string) => startDetect(jid),
    onSuccess: (_d, jid) => void qc.invalidateQueries({ queryKey: ['detect', jid] }),
  })
  const { mutate: startMutate } = start
  const started = useRef<string | null>(null)
  useEffect(() => {
    if (!id || !result.data || started.current === id) return
    started.current = id
    startMutate(id)
  }, [id, result.data, startMutate])
  // mutation state belongs to the run it was started for (/run/A → /run/B reuses this hook)
  const startedHere = Boolean(id) && start.variables === id
  const detect = useQuery(detectOptions(id ?? '', startedHere && start.isSuccess))

  if (!id) return idleRun()

  const d = detect.data
  const r = result.data
  const steps = j?.steps ?? []
  const specStepDone = Boolean(steps[0]?.done)
  const failedAt = j?.status === 'error' ? Math.max(1, j.step_index || steps.findIndex((s) => !s.done) + 1) : 0
  const jobErr = j?.error ?? 'Úloha skončila chybou.'
  const retryDetect = () => {
    start.reset()
    startMutate(id)
  }
  const retryResult = () => void result.refetch()

  const stages: Record<StageId, Stage> = {
    prompt: job.error
      ? { state: 'error', error: job.error.message }
      : j || input.data
        ? { state: 'done' }
        : { state: 'running' },
    spec: !j
      ? pending
      : failedAt === 1 && !specStepDone
        ? { state: 'error', error: jobErr, retry: retryJob }
        : specStepDone
          ? { state: 'done' }
          : j.status === 'running'
            ? { state: 'running', sub: steps[0]?.name }
            : pending,
    data: !j || !specStepDone
      ? pending
      : failedAt > 1
        ? { state: 'error', error: jobErr, retry: retryJob }
        : result.error
          ? { state: 'error', error: result.error.message, retry: retryResult }
          : r
            ? { state: 'done' }
            : { state: 'running', sub: j.step ?? (jobDone ? 'načítám výsledek' : undefined) },
    detect: !r
      ? pending
      : startedHere && start.error
        ? { state: 'error', error: start.error.message, retry: retryDetect }
        : d?.status === 'error'
          ? { state: 'error', error: d.error ?? 'Detektiv skončil chybou.', retry: retryDetect }
          : detect.error && !isStatus(detect.error, 404)
            ? { state: 'error', error: detect.error.message, retry: () => void detect.refetch() }
            : d?.status === 'done'
              ? { state: 'done' }
              : { state: 'running', sub: d?.status === 'queued' ? 've frontě' : 'hledá v datech' },
    score: r && d?.status === 'done' ? { state: 'done' } : pending,
    summary: r && d?.status === 'done' ? { state: 'done' } : pending,
  }

  return { id, job: j, input: input.data, result: r, detect: d, stages, status: status(j, d, Boolean(r), stages) }
}

function status(j: Job | undefined, d: Detect | undefined, haveResult: boolean, stages: Record<StageId, Stage>): Status {
  const err = Object.entries(stages).find(([, s]) => s.state === 'error')
  if (err) {
    const label = STAGES.find((s) => s.id === err[0])?.label ?? err[0]
    return { title: `Chyba: ${label}`, detail: err[1].error, progress: null, etaS: null, position: null, tone: 'error' }
  }
  if (!j) return { title: 'Načítám…', progress: null, etaS: null, position: null, tone: 'busy' }

  // one bar for the whole run: the job's own estimate plus ~40 s of detective
  const detElapsed = d?.elapsed_s ?? 0
  const detTotal = d?.status === 'done' ? detElapsed : Math.max(DETECT_S, detElapsed + 5)
  const jobTotal = j.elapsed_s + j.eta_s
  const elapsed = j.elapsed_s + detElapsed
  const total = jobTotal + detTotal
  const progress = Math.min(1, total > 0 ? elapsed / total : 0)
  const etaS = Math.max(0, Math.round(total - elapsed))

  if (j.status === 'queued')
    return {
      title: 'Ve frontě',
      detail: j.position > 0 ? `před vámi ${j.position} ${j.position === 1 ? 'úloha' : j.position < 5 ? 'úlohy' : 'úloh'}` : 'jste na řadě',
      progress: 0,
      etaS,
      position: j.position,
      tone: 'busy',
    }
  if (j.status === 'running') {
    return {
      title: `${j.step_index <= 1 ? 'Spec' : 'Data'}: ${j.step ?? ''}`,
      detail: `krok ${j.step_index}/${j.steps_total}`,
      progress,
      etaS,
      position: null,
      tone: 'busy',
    }
  }
  if (!haveResult) return { title: 'Data: načítám výsledek', progress, etaS, position: null, tone: 'busy' }
  if (!d || d.status === 'queued')
    return {
      title: 'Detektiv: ve frontě',
      detail: d && d.position > 0 ? `před ním ${d.position}` : undefined,
      progress,
      etaS,
      position: d?.position ?? null,
      tone: 'busy',
    }
  if (d.status === 'running') return { title: 'Detektiv hledá příběh', detail: 'bez znalosti příběhu', progress, etaS, position: null, tone: 'busy' }
  return { title: 'Hotovo', detail: `za ${duration(elapsed)}`, progress: 1, etaS: null, position: null, tone: 'done' }
}
