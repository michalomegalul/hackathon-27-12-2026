// Which runs are "mine" and which are demos, for the History filter and the Rev story picker.
// In public mode every visitor is the API user "public", so the API cannot say whose a run is:
// this browser remembers the ids it created (localStorage). Demo runs are the ones made with a
// team token (docs/API.md, scope=all; DECISIONS 126): owner other than "public".
import type { JobListItem } from '../api'

const KEY = 's2d_mine'

function read(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? '[]') as unknown
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

export function rememberMine(id: string) {
  try {
    localStorage.setItem(KEY, JSON.stringify([id, ...read().filter((x) => x !== id)].slice(0, 500)))
  } catch {
    /* private mode: the filter "moje" just stays empty */
  }
}

export const mineIds = () => new Set(read())

export const isDemo = (j: JobListItem) => j.owner !== 'public'

/** Case- and diacritics-insensitive search over the title, the story preview and the id. */
const fold = (s: string) => s.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '')
export function matchesQuery(j: JobListItem, q: string): boolean {
  const words = fold(q).split(/\s+/).filter(Boolean)
  if (!words.length) return true
  const hay = fold(`${j.title} ${j.story_preview ?? ''} ${j.job_id}`)
  return words.every((w) => hay.includes(w))
}
