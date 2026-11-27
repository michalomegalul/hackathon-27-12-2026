// ---- formatting (Czech) ----------------------------------------------------------------

const nf1 = new Intl.NumberFormat('cs-CZ', { maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('cs-CZ', { maximumFractionDigits: 2 })

/** Signed number with a real minus sign: −13,1 */
export function signed(n: number, digits: 1 | 2 = 1): string {
  const s = (digits === 1 ? nf1 : nf2).format(Math.abs(n))
  return n > 0 ? `+${s}` : n < 0 ? `−${s}` : s
}

const UNIT_CS: Record<string, string> = { pp: 'p. b.', d: 'dní' }
export const unitCs = (u: string) => UNIT_CS[u] ?? u

/** −13,1 % · +0,4 p. b. · −3 dní; "–" for null */
export function withUnit(n: number | null | undefined, unit: string, digits: 1 | 2 = 1): string {
  if (n === null || n === undefined) return '–'
  const u = unitCs(unit)
  return u.startsWith('/') ? `${signed(n, digits)}${u}` : `${signed(n, digits)} ${u}`
}

export const num = (n: number | null | undefined, digits: 1 | 2 = 1) =>
  n === null || n === undefined ? '–' : (digits === 1 ? nf1 : nf2).format(n)

export const intCs = (n: number) => new Intl.NumberFormat('cs-CZ').format(n)

/** 1 řádek · 3 řádky · 5 řádků */
export const rowsCs = (n: number) => `${intCs(n)} ${n === 1 ? 'řádek' : n >= 2 && n <= 4 ? 'řádky' : 'řádků'}`

export function dateCs(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('cs-CZ', { day: 'numeric', month: 'numeric', year: 'numeric' })
}

export function dateTimeCs(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString('cs-CZ', { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/** 75 → "1 min 15 s", 40 → "40 s" */
export function duration(s: number): string {
  const r = Math.max(0, Math.round(s))
  return r < 90 ? `${r} s` : `${Math.floor(r / 60)} min ${r % 60} s`
}

export const KPI_CS: Record<string, string> = {
  orders: 'objednávky',
  leavers: 'odchody zákazníků',
  new_customers: 'noví zákazníci',
  late_share: 'podíl pozdních zásilek',
  rating: 'průměrné hodnocení',
  late_churn: 'odchody po pozdní zásilce',
  cancellations: 'zrušená předplatná',
  tickets: 'tikety na podporu',
  stockout_days: 'podíl vyprodaných produktů',
}

export const CONTROL_CS: Record<string, string> = {
  vary: 'srovnání s ostatními hodnotami stejné dimenze',
  rest: 'srovnání se vším mimo cíl',
  yoy: 'meziročně (stejné dny o 364 dní dříve)',
  none: 'jen před / po',
}

/** The detective's metrics and kinds (s2d/detective/narrate.py METRIC_CS, KIND_CS). */
export const METRIC_CS: Record<string, string> = {
  purchase_rate: 'objednávky',
  churn_hazard: 'odchod zákazníků',
  acquisition_rate: 'noví zákazníci',
  rating_mean: 'hodnocení',
  ticket_rate: 'tikety',
  delivery_days: 'doba doručení',
}
export const KIND_CS: Record<string, string> = { shift: 'trvalejší změna', spike: 'krátký výkyv', stockout: 'výpadek zásob' }

/** DuckDB type → the Postgres type /ddl uses (docs/API.md, GET /ddl). */
export function pgType(t: string): string {
  const u = t.toUpperCase()
  if (u === 'VARCHAR') return 'text'
  if (u === 'DOUBLE' || u === 'FLOAT') return 'double precision'
  if (u.startsWith('DECIMAL')) return u.replace('DECIMAL', 'numeric').toLowerCase()
  if (['BIGINT', 'INTEGER', 'DATE', 'TIMESTAMP', 'BOOLEAN'].includes(u)) return u.toLowerCase()
  return 'text'
}
