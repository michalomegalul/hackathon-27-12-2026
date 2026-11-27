// Where the Story and Rev story tabs lead back to, and the run the header chip follows.
// Per browser tab (sessionStorage): leaving a run for History or About and clicking "Story"
// reopens it instead of an empty composer. "+ Nový příběh" / "Vybrat jinou databázi" forget it.
import { useEffect, useSyncExternalStore } from 'react'
import { useQuery } from '@tanstack/react-query'
import { isStatus, jobOptions } from '../api'

export type Tab = 'story' | 'rev'
/** The run started last in this browser tab, at its own page (`/run/:id` or `/rev/:id`). */
export type Active = { id: string; path: string }

const KEY = { story: 's2d_last_story', rev: 's2d_last_rev', active: 's2d_active' } as const

const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())
const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

function get(k: string): string | null {
  try {
    return sessionStorage.getItem(k)
  } catch {
    return null
  }
}
function set(k: string, v: string | null) {
  if (get(k) === v) return
  try {
    if (v === null) sessionStorage.removeItem(k)
    else sessionStorage.setItem(k, v)
  } catch {
    /* private mode: the tabs just go to their start pages */
  }
  emit()
}

export const rememberLast = (tab: Tab, id: string) => set(KEY[tab], id)
export const forgetLast = (tab: Tab) => set(KEY[tab], null)
export const useLastRun = (tab: Tab) => useSyncExternalStore(subscribe, () => get(KEY[tab]))

/** `path` is the run's page, e.g. "/run/<id>" (useSend knows which). */
export const setActive = (id: string, path: string) => set(KEY.active, JSON.stringify({ id, path } satisfies Active))
export const clearActive = () => set(KEY.active, null)

const activeRaw = () => get(KEY.active)
export function useActive(): Active | null {
  const raw = useSyncExternalStore(subscribe, activeRaw)
  if (!raw) return null
  try {
    const v = JSON.parse(raw) as Partial<Active>
    return typeof v.id === 'string' && typeof v.path === 'string' ? { id: v.id, path: v.path } : null
  } catch {
    return null
  }
}

/** The tab's link leads back to this run; a run that no longer exists (404) is forgotten. */
export function useRememberLast(tab: Tab, id: string | undefined) {
  const job = useQuery({ ...jobOptions(id ?? ''), enabled: Boolean(id) }) // same cache entry as useRun
  const gone = isStatus(job.error, 404)
  useEffect(() => {
    if (!id) return
    if (gone) forgetLast(tab)
    else rememberLast(tab, id)
  }, [tab, id, gone])
}
