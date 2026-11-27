// Replay of a finished run. A demo run is already done on the server, but a real run takes minutes,
// so opening one from Example / Demo plays the stages in about 16 s: Spec, then the Data
// sub-steps with their real names, then the detective, then the finished page. Everything shown is
// the real result; only the timing is compressed. Played once per browser tab and run, so a
// reload or a shared link shows the finished run at once.
import { useEffect, useState } from 'react'
import type { Job } from '../api'
import { stepEn } from '../format'
import { STAGES, type Run, type Stage, type StageId } from './useRun'

const SPEC_END = 3
const DATA_END = 12
const TOTAL = 17

const KEY = 's2d_replayed'
const seen = (id: string) => {
  try {
    return (sessionStorage.getItem(KEY) ?? '').split(',').includes(id)
  } catch {
    return false
  }
}
const markSeen = (id: string) => {
  try {
    sessionStorage.setItem(KEY, `${sessionStorage.getItem(KEY) ?? ''},${id}`)
  } catch {
    /* private mode: a reload replays again, nothing breaks */
  }
}

/** `run` as it looks `e` seconds into the replay. */
export function replayAt(run: Run, e: number): Run {
  const job = run.job
  const stage = (s: Partial<Record<StageId, Stage>>): Run['stages'] => {
    const out = {} as Run['stages']
    for (const { id } of STAGES) out[id] = s[id] ?? { state: 'pending' }
    return out
  }
  const dataSteps = job?.steps.slice(1) ?? []
  const k = Math.min(Math.max(dataSteps.length - 1, 0), Math.floor(((e - SPEC_END) / (DATA_END - SPEC_END)) * dataSteps.length))
  const phase = e < SPEC_END ? 'spec' : e < DATA_END ? 'data' : 'detect'

  const fakeJob: Job | undefined = job && {
    ...job,
    status: 'running',
    position: 0,
    step: phase === 'spec' ? (job.steps[0]?.name ?? null) : (dataSteps[k]?.name ?? null),
    step_index: phase === 'spec' ? 1 : k + 2,
    progress: e / TOTAL,
    steps: job.steps.map((s, i) => {
      const done = phase !== 'spec' && (i === 0 || (phase === 'detect' ? true : i - 1 < k))
      return done && !s.done ? ({ name: s.name, done: true, s: 1, note: '' } as const) : done ? s : s.done ? { name: s.name, done: false, eta_s: Math.max(1, s.s) } : s
    }),
  }
  const title = phase === 'spec' ? 'Spec: the LLM is writing it' : phase === 'data' ? `Data: ${stepEn(dataSteps[k]?.name ?? 'generating')}` : 'Detective: searching the data'
  return {
    ...run,
    job: fakeJob,
    result: phase === 'detect' ? run.result : undefined,
    detect: undefined,
    stages: stage({
      prompt: { state: 'done' },
      spec: phase === 'spec' ? { state: 'running', sub: job?.steps[0]?.name } : { state: 'done' },
      data: phase === 'spec' ? { state: 'pending' } : phase === 'data' ? { state: 'running', sub: dataSteps[k]?.name } : { state: 'done' },
      detect: phase === 'detect' ? { state: 'running', sub: 'searching the data' } : { state: 'pending' },
    }),
    status: {
      title,
      detail: 'Saved demo run, replayed: the numbers are real, the timing is compressed.',
      progress: e / TOTAL,
      etaS: Math.max(1, TOTAL - e),
      position: null,
      tone: 'busy',
    },
  }
}

/** Plays `run` from the start when `enabled` (opened from Example/Demo) and it has not played in this tab yet. */
export function useReplay(run: Run, enabled: boolean): Run {
  const id = run.id
  const [clock, setClock] = useState<{ id: string; t0: number; now: number } | null>(null)
  // not played yet in this tab: until the clock exists, show second 0 (never a flash of the finished page)
  const eligible = enabled && Boolean(id) && run.job?.status === 'done' && !(id && seen(id))
  const e = clock && clock.id === id ? (clock.now - clock.t0) / 1000 : eligible ? 0 : Infinity
  const playing = e < TOTAL
  useEffect(() => {
    if (eligible && id && clock?.id !== id) setClock({ id, t0: Date.now(), now: Date.now() })
  }, [eligible, id, clock?.id])
  useEffect(() => {
    if (!playing) {
      if (id && clock?.id === id) markSeen(id)
      return
    }
    const h = setInterval(() => setClock((c) => (c ? { ...c, now: Date.now() } : c)), 250)
    return () => clearInterval(h)
  }, [playing, id, clock?.id])
  return playing ? replayAt(run, e) : run
}
