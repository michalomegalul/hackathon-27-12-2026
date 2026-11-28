// Typed client for docs/API.md. All URLs are relative (/v1/...): the Vite dev proxy and
// nginx in production both route them to the API.
import { infiniteQueryOptions, queryOptions } from '@tanstack/react-query'
import { getToken, markTokenInvalid, setLoginRequired } from './token'

// ---- shapes ----------------------------------------------------------------------------

export type JobStatus = 'queued' | 'running' | 'done' | 'error'
export type Difficulty = 'easy' | 'medium' | 'hard'
export type Dirt = 'none' | 'low' | 'medium' | 'high'

export type Step =
  | { name: string; done: true; s: number; note: string }
  | { name: string; done: false; eta_s: number }

export type Job = {
  job_id: string
  status: JobStatus
  position: number
  step: string | null
  step_index: number
  steps_total: number
  progress: number
  elapsed_s: number
  eta_s: number
  steps: Step[]
  error: string | null
}

type JobOptions = { difficulty?: Difficulty; seed?: number; n_customers?: number; dirt?: Dirt }
export type NewJob =
  | ({ company: string; story: string } & JobOptions)
  | ({ spec_yaml: string } & JobOptions)

export type JobCreated = { job_id: string; status: JobStatus; position: number }

export type Summary = { story: string; twin: string }

export type JobListItem = {
  job_id: string
  status: JobStatus
  title: string
  owner: string
  created: string
  elapsed_s: number
  summary: Summary | null
  story_preview?: string | null
}

/** GET /v1/jobs/{id}/input: the POST body as given (null when left out). */
export type JobInput = {
  company: string | null
  story: string | null
  difficulty: Difficulty | null
  seed: number | null
  n_customers: number | null
  dirt: Dirt | null
  spec_given: boolean
}

export type VerificationStatus = 'confirmed' | 'not_confirmed' | 'not_testable'
export type ControlMode = 'vary' | 'rest' | 'yoy' | 'none'

export type VerificationRow = {
  event_id: string
  claim_cs: string
  kpi: string
  metric: string
  target: string
  start: string
  direction: 'up' | 'down' | string
  story_size: number | null
  story_unit: string
  expected_size: number | null
  measured: number | null
  measured_unit: string
  ci: [number, number] | null
  z: number | null
  p_placebo: number | null
  confirmed: boolean
  status: VerificationStatus
  reason: string
  control_mode: ControlMode
  control: string
  twin_measured: number | null
  twin_z: number | null
  twin_confirmed: boolean | null
  sql: string | null
  sql_result: Record<string, unknown> | null
  sql_matches: boolean | null
}

export type UntestedEvent = { event_id: string; type: string; claim_cs: string; reason: string }

export type JobResult = {
  job_id: string
  spec_yaml: string
  summary: Summary
  narrative: { text: string; source: string } | null
  verification: VerificationRow[]
  untested: UntestedEvent[]
  warnings: string[]
  rows: Record<string, number>
}

export type Column = { name: string; type: string }
export type ForeignKey = { column: string; references: { table: string; column: string } }
export type TableInfo = {
  name: string
  rows: number
  columns: Column[]
  primary_key?: string[]
  foreign_keys?: ForeignKey[]
}
export type World = 'story' | 'twin'
export type Cell = string | number | boolean | null
export type TablePage = {
  name: string
  total: number
  limit: number
  offset: number
  columns: Column[]
  rows: Cell[][]
}
export type QueryResult = { columns: Column[]; rows: Cell[][]; truncated: boolean; seconds: number }

export type Health = {
  ok: boolean
  llm: { backend: string; model: string; reachable: boolean }
  queue: { running: string | null; waiting: number }
}

export type DetectEvent = {
  id: string
  metric: string
  segment: string | null
  start_date: string
  end_date: string | null
  direction: 'up' | 'down' | string
  magnitude_pct: number | null
  lag_days: number | null
  caused_by: string | null
  kind: string
  confidence: number
  evidence: string
}
export type DetectScore = {
  precision: number
  recall: number
  f1: number
  /** precision and F1 when consequences and finds the twin has too are left out */
  precision_cons?: number
  f1_cons?: number
  twin_false_events_per_year: number | null
  placebo_p: number | null
}
/** s2d/score.py's pairing of finds and planted events (teacher and admin only). */
export type DetectMatching = {
  pairs: { found_id: string; event_id: string; score: number; timing: number; delta_days: number; segment: number; magnitude: number }[]
  missed: string[]
  false_finds: { found_id: string; decoy: string | null }[]
  consequences: { found_id: string; of: string }[]
  background: { found_id: string; twin_id: string; twin_start_date: string }[]
}
export type Detect = {
  job_id: string
  status: JobStatus
  position: number
  elapsed_s: number
  error: string | null
  events: DetectEvent[] | null
  narrative: { text: string; source: string } | null
  score: DetectScore | null
  matching?: DetectMatching | null
}

/** GET /answer-key row: an event the story planted (the hidden truth; teacher and admin). */
export type PlantedEvent = {
  event_id: string
  type: string
  metric: string
  segment: string | null
  start_date: string
  lag_days: number | null
  magnitude_pct: number | null
  direction: 'up' | 'down' | string
  caused_by: string | null
  simulated: boolean
  narrative_cs: string
}
export type Decoy = { type: string; date: string; [k: string]: unknown }
export type AnswerKey = { job_id: string; answer_key: PlantedEvent[]; decoys: Decoy[] }

/** GET /v1/stats: the live dashboard (no auth, cached 5 s on the server). */
export type Stats = {
  jobs_total: number
  jobs_done: number
  jobs_today: number
  running: { job_id: string; step: string | null; step_index: number; progress: number; eta_s: number } | null
  waiting: number
  median_run_s: number | null
  events_confirmed_pct: number | null
  twin_false_pct: number | null
  customers_simulated: number
  rows_generated: number
  recent: { job_id: string; title: string; finished: string; elapsed_s: number; summary: Summary | null }[]
  timeline: { hour: string; jobs: number; median_run_s: number | null }[]
}

// ---- errors ----------------------------------------------------------------------------

/** FastAPI 422 item: `detail` is a list of these. */
export type ValidationIssue = { type: string; loc: (string | number)[]; msg: string; input?: unknown }

export class ApiError extends Error {
  status: number
  detail: string | ValidationIssue[]
  constructor(status: number, detail: string | ValidationIssue[], message?: string) {
    super(
      message ??
        (typeof detail === 'string'
          ? detail
          : detail.map((d) => `${d.loc.filter((l) => l !== 'body').join('.') || 'request'}: ${d.msg}`).join('; ')),
    )
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** The request never got an answer from the API (offline, DNS, or nginx 502/503/504 while the API restarts). */
export class NetworkError extends Error {
  constructor(message = 'The server is unreachable. Check your connection.') {
    super(message)
    this.name = 'NetworkError'
  }
}

/** Czech text for the errors every page can meet; other details (e.g. DuckDB's 400) pass through as-is. */
function czech(status: number, detail: string | ValidationIssue[]): string | undefined {
  const d = typeof detail === 'string' ? detail : ''
  if (status === 401) return 'Invalid token.'
  if (status === 404 && d === 'job not found') return 'Job not found (or not yours).'
  if (status === 404 && d === 'table not found') return 'Tabulka nenalezena.'
  if (status === 408) return 'The query ran longer than 20 s and was cancelled. Narrow it down (WHERE, LIMIT).'
  if (status === 409) return 'The job has not finished yet, so the data is not available.'
  return undefined
}

export const isStatus = (err: unknown, status: number) => err instanceof ApiError && err.status === status

/** Don't retry answers that won't change (4xx); retry network trouble and 5xx a few times. */
export const retryTransient = (n: number, err: Error) => !(err instanceof ApiError && err.status < 500) && n < 3

// ---- network state (drives the retry banner) ------------------------------------------

let netDown = false
const netListeners = new Set<() => void>()
function setNetDown(v: boolean) {
  if (v === netDown) return
  netDown = v
  netListeners.forEach((l) => l())
}
export const subscribeNet = (l: () => void) => {
  netListeners.add(l)
  return () => {
    netListeners.delete(l)
  }
}
export const getNetDown = () => netDown

// ---- transport -------------------------------------------------------------------------

async function request(path: string, init?: RequestInit): Promise<Response> {
  const token = getToken()
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    setNetDown(true)
    throw new NetworkError()
  }
  if (res.status === 502 || res.status === 503 || res.status === 504) {
    setNetDown(true)
    throw new NetworkError('The server is temporarily unreachable.')
  }
  setNetDown(false)
  if (res.status === 401) {
    // a token was sent and is unknown: forget it (the API may be public and work without one);
    // no token and still 401: the API is not public, so the token form shows
    if (token) markTokenInvalid()
    else setLoginRequired()
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: string | ValidationIssue[] } | null
    const detail = body?.detail ?? res.statusText ?? `HTTP ${res.status}`
    throw new ApiError(res.status, detail, czech(res.status, detail))
  }
  return res
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  return (await (await request(path, init)).json()) as T
}

// ---- endpoints -------------------------------------------------------------------------

export const getHealth = () => api<Health>('/v1/health')

export const createJob = (body: NewJob) =>
  api<JobCreated>('/v1/jobs', { method: 'POST', body: JSON.stringify(body) })

export const listJobs = (scope: 'mine' | 'all' = 'mine') => api<{ jobs: JobListItem[] }>(`/v1/jobs?scope=${scope}`)
export const getJob = (id: string) => api<Job>(`/v1/jobs/${encodeURIComponent(id)}`)
export const getInput = (id: string) => api<JobInput>(`/v1/jobs/${encodeURIComponent(id)}/input`)
export const startDetect = (id: string) =>
  api<{ job_id: string; status: JobStatus; position: number }>(`/v1/jobs/${encodeURIComponent(id)}/detect`, { method: 'POST' })
export const getDetect = (id: string) => api<Detect>(`/v1/jobs/${encodeURIComponent(id)}/detect`)
export const getResult = (id: string) => api<JobResult>(`/v1/jobs/${encodeURIComponent(id)}/result`)
export const getAnswerKey = (id: string) => api<AnswerKey>(`/v1/jobs/${encodeURIComponent(id)}/answer-key`)
export const getStats = () => api<Stats>('/v1/stats')
export const getTables = (id: string) => api<{ tables: TableInfo[] }>(`/v1/jobs/${encodeURIComponent(id)}/tables`)
export const getTable = (id: string, name: string, limit = 100, offset = 0, signal?: AbortSignal, world: World = 'story') =>
  api<TablePage>(
    `/v1/jobs/${encodeURIComponent(id)}/tables/${encodeURIComponent(name)}?limit=${limit}&offset=${offset}&world=${world}`,
    { signal },
  )
/** GET /ddl: the analyst tables as Postgres CREATE TABLE statements (text/plain). */
export const getDdl = async (id: string) => (await request(`/v1/jobs/${encodeURIComponent(id)}/ddl`)).text()
export const runQuery = (id: string, sql: string, world: World = 'story') =>
  api<QueryResult>(`/v1/jobs/${encodeURIComponent(id)}/query`, { method: 'POST', body: JSON.stringify({ sql, world }) })

/** The ZIP needs the Bearer header, so a plain <a href> cannot download it: fetch a blob and save it. */
export async function downloadZip(id: string): Promise<void> {
  const res = await request(`/v1/jobs/${encodeURIComponent(id)}/download`)
  const blob = await res.blob()
  const name =
    /filename="?([^";]+)"?/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? `story2data-${id}.zip`
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.append(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

// ---- query options ---------------------------------------------------------------------

const finished = (s: JobStatus | undefined) => s === 'done' || s === 'error'

/** Poll every 2 s until done/error (API.md: "every 2 s is fine"). */
export const jobOptions = (id: string) =>
  queryOptions({
    queryKey: ['job', id],
    queryFn: () => getJob(id),
    refetchInterval: (query) => (finished(query.state.data?.status) ? false : 2000),
    retry: retryTransient,
  })

/** /result is 409 until the job is done: only enable it then. */
export const resultOptions = (id: string, enabled: boolean) =>
  queryOptions({
    queryKey: ['result', id],
    queryFn: () => getResult(id),
    enabled,
    staleTime: Infinity, // a finished job's result never changes
    retry: retryTransient,
  })

export const jobsOptions = (scope: 'mine' | 'all' = 'mine') =>
  queryOptions({
    queryKey: ['jobs', scope],
    queryFn: () => listJobs(scope),
    retry: retryTransient,
    // keep the list fresh while something is still queued/running
    refetchInterval: (query) => (query.state.data?.jobs.some((j) => !finished(j.status)) ? 3000 : false),
  })

/** The planted events (403 for a student: the caller falls back to the verification rows). */
export const answerKeyOptions = (id: string, enabled: boolean) =>
  queryOptions({
    queryKey: ['answer-key', id],
    queryFn: () => getAnswerKey(id),
    enabled,
    staleTime: Infinity,
    retry: retryTransient,
  })

/** Live stats: the server recomputes them at most every 5 s, so poll at that pace. */
export const statsOptions = () =>
  queryOptions({ queryKey: ['stats'], queryFn: getStats, refetchInterval: 5000, retry: retryTransient })

/** The prompt as sent: any status, and it never changes. */
export const inputOptions = (id: string) =>
  queryOptions({ queryKey: ['input', id], queryFn: () => getInput(id), staleTime: Infinity, retry: retryTransient })

/** The detective (404 before a POST): poll every 2 s while it is queued or running. */
export const detectOptions = (id: string, enabled: boolean) =>
  queryOptions({
    queryKey: ['detect', id],
    queryFn: () => getDetect(id),
    enabled,
    refetchInterval: (query) => (finished(query.state.data?.status) ? false : 2000),
    retry: retryTransient,
  })

/** /tables and /query answer 409 until the job is done: enable them only then. */
export const tablesOptions = (id: string, enabled: boolean) =>
  queryOptions({
    queryKey: ['tables', id],
    queryFn: () => getTables(id),
    enabled,
    staleTime: Infinity,
    retry: retryTransient,
  })

export const ddlOptions = (id: string) =>
  queryOptions({ queryKey: ['ddl', id], queryFn: () => getDdl(id), staleTime: Infinity, retry: retryTransient })

/** The first `n` rows of a table, like `SELECT * FROM t LIMIT n` in psql. */
export const tableHeadOptions = (id: string, name: string, n = 5, world: World = 'story') =>
  queryOptions({
    queryKey: ['tablehead', id, name, n, world],
    queryFn: ({ signal }) => getTable(id, name, n, 0, signal, world),
    staleTime: Infinity,
    retry: retryTransient,
  })

/** A query whose answer never changes (a finished job's data). */
export const sqlOptions = (id: string, sql: string | undefined, world: World = 'story') =>
  queryOptions({
    queryKey: ['sql', id, world, sql],
    queryFn: () => runQuery(id, sql!, world),
    enabled: Boolean(sql),
    staleTime: Infinity,
    retry: retryTransient,
  })

/** The API caps `limit` at 1000 (more is a 422). */
export const PAGE = 1000

/** Rows of one table, a page of 1000 at a time, by offset; `total` comes from the first page. */
export const tableRowsOptions = (id: string, name: string, enabled: boolean) =>
  infiniteQueryOptions({
    queryKey: ['table', id, name],
    queryFn: ({ pageParam, signal }) => getTable(id, name, PAGE, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.rows.length < last.total && last.rows.length > 0 ? last.offset + last.rows.length : undefined),
    enabled,
    staleTime: Infinity, // a finished job's data never changes
    retry: retryTransient,
  })
