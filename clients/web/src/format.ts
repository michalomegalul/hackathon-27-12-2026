// ---- formatting (English) ----------------------------------------------------------------

const nf1 = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 2 })

/** Signed number with a real minus sign: −13,1 */
export function signed(n: number, digits: 1 | 2 = 1): string {
  const s = (digits === 1 ? nf1 : nf2).format(Math.abs(n))
  return n > 0 ? `+${s}` : n < 0 ? `−${s}` : s
}

const UNIT_CS: Record<string, string> = { pp: 'pp', d: 'days' }
export const unitCs = (u: string) => UNIT_CS[u] ?? u

/** −13.1 % · +0.4 pp · −3 days; "–" for null */
export function withUnit(n: number | null | undefined, unit: string, digits: 1 | 2 = 1): string {
  if (n === null || n === undefined) return '–'
  const u = unitCs(unit)
  return u.startsWith('/') ? `${signed(n, digits)}${u}` : `${signed(n, digits)} ${u}`
}

export const num = (n: number | null | undefined, digits: 1 | 2 = 1) =>
  n === null || n === undefined ? '–' : (digits === 1 ? nf1 : nf2).format(n)

export const intCs = (n: number) => new Intl.NumberFormat('en-GB').format(n)

/** 1 row · 3 rows */
export const rowsCs = (n: number) => `${intCs(n)} ${n === 1 ? 'row' : 'rows'}`

export function dateCs(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'numeric', year: 'numeric' })
}

export function dateTimeCs(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString('en-GB', { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/** The API's step names and notes are Czech (docs/API.md); the pages show them in English. */
const STEP_EN: Record<string, string> = {
  'specifikace (AI)': 'spec (LLM)',
  'kalibrace a simulace': 'calibration and simulation',
  'dvojče bez příběhu': 'twin without the story',
  'ověření': 'verification',
  'český příběh (AI)': 'Czech story (LLM)',
  detektiv: 'detective',
}
export function stepEn(s: string): string {
  return (
    STEP_EN[s] ??
    s
      .replace(/^platná na (\d+)\. pokus/, 'valid on attempt $1')
      .replace('spec zadán (bez AI)', 'spec given (no LLM)')
      .replace('(z cache)', '(cached)')
      .replace(/(\d+) zákazníků/, '$1 customers')
      .replace(/(\d+) dní/, '$1 days')
  )
}

/** 75 → "1 min 15 s", 40 → "40 s" */
export function duration(s: number): string {
  const r = Math.max(0, Math.round(s))
  return r < 90 ? `${r} s` : `${Math.floor(r / 60)} min ${r % 60} s`
}

export const KPI_CS: Record<string, string> = {
  orders: 'orders',
  leavers: 'customers leaving',
  new_customers: 'new customers',
  late_share: 'share of late shipments',
  rating: 'average rating',
  late_churn: 'churn after a late shipment',
  cancellations: 'cancelled subscriptions',
  tickets: 'support tickets',
  stockout_days: 'share of products out of stock',
}

export const CONTROL_CS: Record<string, string> = {
  vary: 'compared with the other values of the same dimension',
  rest: 'compared with everything outside the target',
  yoy: 'year over year (same days 364 days earlier)',
  none: 'before / after only',
}

/** The detective's metrics and kinds (s2d/detective/narrate.py METRIC_CS, KIND_CS). */
export const METRIC_CS: Record<string, string> = {
  purchase_rate: 'orders',
  churn_hazard: 'customer churn',
  acquisition_rate: 'new customers',
  rating_mean: 'rating',
  ticket_rate: 'tickets',
  delivery_days: 'delivery time',
}
export const KIND_CS: Record<string, string> = { shift: 'level shift', spike: 'short spike', stockout: 'stock-out' }

/** DuckDB type → the Postgres type /ddl uses (docs/API.md, GET /ddl). */
export function pgType(t: string): string {
  const u = t.toUpperCase()
  if (u === 'VARCHAR') return 'text'
  if (u === 'DOUBLE' || u === 'FLOAT') return 'double precision'
  if (u.startsWith('DECIMAL')) return u.replace('DECIMAL', 'numeric').toLowerCase()
  if (['BIGINT', 'INTEGER', 'DATE', 'TIMESTAMP', 'BOOLEAN'].includes(u)) return u.toLowerCase()
  return 'text'
}

/** English plural: [1, other] */
export const plural = (n: number, [one, many]: [string, string]) => (n === 1 ? one : many)
