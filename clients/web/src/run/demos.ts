// The finished runs behind the Example chip and the Demo page: found in the job list by what they
// were made from, so nothing has to be pasted in by hand after generating them. Opening one
// replays it (run/replay.ts), because a real run takes minutes.
import { useQuery } from '@tanstack/react-query'
import { jobsOptions, type JobListItem } from '../api'
import { BRIEF_EXAMPLE } from '../examples'
import { isDemo } from './jobs'

export type DemoKey = 'brief' | 'coffee' | 'nahapravda'

const fold = (s: string) => s.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '').replace(/\s+/g, ' ').trim()
const BRIEF_START = fold(BRIEF_EXAMPLE.story).slice(0, 40)

/** What each demo looks like in GET /v1/jobs: the story preview (text jobs) or the title (spec jobs). */
const MATCH: Record<DemoKey, (j: JobListItem) => boolean> = {
  brief: (j) => fold(j.story_preview ?? '').startsWith(BRIEF_START),
  coffee: (j) => fold(j.title) === 'prazirna zrnko',
  nahapravda: (j) => fold(j.title) === 'naha pravda',
}

const ratio = (j: JobListItem) => {
  const [ok, all] = (j.summary?.story ?? '0/0').split('/').map(Number)
  return all > 0 ? ok / all : 0
}

/** The best finished run of a demo: team runs first, then the most confirmed events, then the newest. */
export function findDemoRun(jobs: JobListItem[] | undefined, key: DemoKey): string | null {
  const hits = (jobs ?? []).filter((j) => j.status === 'done' && MATCH[key](j))
  hits.sort((a, b) => Number(isDemo(b)) - Number(isDemo(a)) || ratio(b) - ratio(a) || b.created.localeCompare(a.created))
  return hits[0]?.job_id ?? null
}

/** The run id of a demo, or null while the list loads or when none exists yet. */
export function useDemoRun(key: DemoKey): string | null {
  const { data } = useQuery(jobsOptions('all'))
  return findDemoRun(data?.jobs, key)
}

/** The router state that makes /run/:id play as a live run. */
export const REPLAY_STATE = { replay: true }
