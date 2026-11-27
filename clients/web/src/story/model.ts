// Pure helpers for the ERD and the Summary: FK edges and layout from /tables' keys, the KPI column an event
// moved, and the daily series SQL derived from a verification row.
import type { TableInfo, VerificationRow } from '../api'

// ---- schema ----------------------------------------------------------------------------

export type Fk = { child: string; column: string; parent: string; parentColumn: string }

/** FK edges from the keys /tables reports (the Postgres export's constraints), no name guessing. */
export function keyFks(tables: TableInfo[]): Fk[] {
  const names = new Set(tables.map((t) => t.name))
  return tables.flatMap((t) =>
    (t.foreign_keys ?? [])
      .filter((f) => names.has(f.references.table) && f.references.table !== t.name)
      .map((f) => ({ child: t.name, column: f.column, parent: f.references.table, parentColumn: f.references.column })),
  )
}

/** Left to right by FK depth: parents in column 0, their children after them. */
export function layout(tables: TableInfo[], fks: Fk[]): Map<string, { x: number; y: number }> {
  const parents = new Map<string, string[]>()
  for (const f of fks) parents.set(f.child, [...(parents.get(f.child) ?? []), f.parent])
  const depth = new Map<string, number>()
  const visit = (name: string, seen: Set<string>): number => {
    if (depth.has(name)) return depth.get(name)!
    if (seen.has(name)) return 0 // a cycle: stop here
    seen.add(name)
    const d = Math.max(-1, ...(parents.get(name) ?? []).map((p) => visit(p, seen))) + 1
    depth.set(name, d)
    return d
  }
  tables.forEach((t) => visit(t.name, new Set()))

  const ROW = 21, HEAD = 34, GAP = 28, COL = 300
  const colY: number[] = []
  const pos = new Map<string, { x: number; y: number }>()
  for (const t of [...tables].sort((a, b) => b.columns.length - a.columns.length)) {
    const d = depth.get(t.name) ?? 0
    const y = colY[d] ?? 0
    pos.set(t.name, { x: d * COL, y })
    colY[d] = y + HEAD + t.columns.length * ROW + GAP
  }
  // centre each column vertically on the tallest one
  const tallest = Math.max(...colY.filter((v) => v !== undefined))
  for (const [name, p] of pos) p.y += (tallest - (colY[depth.get(name) ?? 0] ?? 0)) / 2
  return pos
}

// ---- KPI → the column it moved ---------------------------------------------------------

const KPI_COLUMN: Record<string, [table: string, column: string]> = {
  orders: ['orders', 'order_id'],
  leavers: ['orders', 'customer_id'],
  new_customers: ['customers', 'signup_date'],
  late_share: ['deliveries', 'late'],
  late_churn: ['deliveries', 'late'],
  rating: ['reviews', 'rating'],
  cancellations: ['subscriptions', 'cancelled_at'],
  tickets: ['tickets', 'ticket_id'],
  stockout_days: ['inventory_daily', 'stock_units'],
}

/** [table, column] the event's KPI lives in, if the job has that table and column. */
export function kpiColumn(kpi: string, tables: TableInfo[]): [string, string] | undefined {
  const hit = KPI_COLUMN[kpi]
  if (!hit) return undefined
  const t = tables.find((x) => x.name === hit[0])
  return t?.columns.some((c) => c.name === hit[1]) ? hit : undefined
}

// ---- daily series ----------------------------------------------------------------------

/**
 * The row's SQL builds `daily(day, treated, control)` and then aggregates it in `windows`.
 * Keep everything up to `daily` and select it per day instead: the same groups, the same filter.
 */
export function dailySql(v: VerificationRow): string | undefined {
  const sql = v.sql
  if (!sql || !/\bdaily AS \(/.test(sql)) return undefined
  const cut = sql.search(/\n\s*windows AS \(/)
  if (cut < 0) return undefined
  return `${sql.slice(0, cut).replace(/,\s*$/, '')}\nSELECT day, treated, control FROM daily ORDER BY day`
}

/** Trailing mean over `n` points, skipping nulls; null until there is a value. */
export function rolling(ys: (number | null)[], n: number): (number | null)[] {
  return ys.map((_, i) => {
    let s = 0, k = 0
    for (let j = Math.max(0, i - n + 1); j <= i; j++) {
      const y = ys[j]
      if (y !== null && y !== undefined) {
        s += y
        k++
      }
    }
    return k ? s / k : null
  })
}

/** "2026-03-01" → unix seconds at UTC midnight (uPlot's x). */
export const daySec = (iso: string) => Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) / 1000
