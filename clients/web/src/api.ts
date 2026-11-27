// Typed client for docs/API.md. All URLs are relative (/v1/...): the Vite dev proxy and
// nginx in production both route them to the API.
import { queryOptions } from '@tanstack/react-query'

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
export type TableInfo = { name: string; rows: number; columns: Column[] }
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

// ---- errors ----------------------------------------------------------------------------

/** FastAPI 422 item: `detail` is a list of these. */
export type ValidationIssue = { type: string; loc: (string | number)[]; msg: string; input?: unknown }

export class ApiError extends Error {
  status: number
  detail: string | ValidationIssue[]
  constructor(status: number, detail: string | ValidationIssue[]) {
    super(
      typeof detail === 'string'
        ? detail
        : detail.map((d) => `${d.loc.filter((l) => l !== 'body').join('.') || 'požadavek'}: ${d.msg}`).join('; '),
    )
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

// ---- transport -------------------------------------------------------------------------

const TOKEN = import.meta.env.VITE_API_TOKEN ?? ''

async function request(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(path, {
    ...init,
    headers: {
      ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: string | ValidationIssue[] } | null
    throw new ApiError(res.status, body?.detail ?? res.statusText ?? `HTTP ${res.status}`)
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

export const listJobs = () => api<{ jobs: JobListItem[] }>('/v1/jobs')
export const getJob = (id: string) => api<Job>(`/v1/jobs/${encodeURIComponent(id)}`)
export const getResult = (id: string) => api<JobResult>(`/v1/jobs/${encodeURIComponent(id)}/result`)
export const getTables = (id: string) => api<{ tables: TableInfo[] }>(`/v1/jobs/${encodeURIComponent(id)}/tables`)
export const getTable = (id: string, name: string, limit = 100, offset = 0) =>
  api<TablePage>(
    `/v1/jobs/${encodeURIComponent(id)}/tables/${encodeURIComponent(name)}?limit=${limit}&offset=${offset}`,
  )
export const runQuery = (id: string, sql: string) =>
  api<QueryResult>(`/v1/jobs/${encodeURIComponent(id)}/query`, { method: 'POST', body: JSON.stringify({ sql }) })

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
    retry: (n, err) => !(err instanceof ApiError && err.status < 500) && n < 3,
  })

/** /result is 409 until the job is done: only enable it then. */
export const resultOptions = (id: string, enabled: boolean) =>
  queryOptions({
    queryKey: ['result', id],
    queryFn: () => getResult(id),
    enabled,
    staleTime: Infinity, // a finished job's result never changes
    retry: (n, err) => !(err instanceof ApiError && err.status < 500) && n < 3,
  })

export const jobsOptions = () =>
  queryOptions({
    queryKey: ['jobs'],
    queryFn: listJobs,
    // keep the list fresh while something is still queued/running
    refetchInterval: (query) => (query.state.data?.jobs.some((j) => !finished(j.status)) ? 3000 : false),
  })

export const hasToken = TOKEN !== ''
