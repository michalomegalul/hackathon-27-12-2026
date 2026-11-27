// The API token lives in the browser (localStorage), not in the bundle: the site is public, so a
// token compiled in with VITE_API_TOKEN would be readable by every visitor. VITE_API_TOKEN from
// .env.local is used only by `npm run dev`.
import { useSyncExternalStore } from 'react'

const KEY = 's2d_token'
const devToken = import.meta.env.DEV ? (import.meta.env.VITE_API_TOKEN ?? '') : ''

/** A link like https://…/web/#token=abc logs in (the hash never reaches the server) and is then removed. */
function fromHash(): string | null {
  const m = /(?:^#|&)token=([^&]+)/.exec(location.hash)
  if (!m) return null
  history.replaceState(null, '', location.pathname + location.search)
  return decodeURIComponent(m[1])
}

function read(): string {
  try {
    const h = fromHash()
    if (h) localStorage.setItem(KEY, h)
    return localStorage.getItem(KEY) ?? devToken
  } catch {
    return devToken
  }
}

let token = read()
const listeners = new Set<() => void>()

export const getToken = () => token

export function setToken(t: string) {
  token = t.trim()
  try {
    if (token) localStorage.setItem(KEY, token)
    else localStorage.removeItem(KEY)
  } catch {
    /* private mode: keep it in memory */
  }
  listeners.forEach((l) => l())
}

const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

export const useToken = () => useSyncExternalStore(subscribe, getToken)

// The API may run in public mode (API_PUBLIC_ROLE): then no token is needed and the page opens
// directly. The token form shows only after a request without a token got 401.
let loginRequired = false
export function setLoginRequired() {
  if (loginRequired) return
  loginRequired = true
  listeners.forEach((l) => l())
}
export const useLoginRequired = () => useSyncExternalStore(subscribe, () => loginRequired)
