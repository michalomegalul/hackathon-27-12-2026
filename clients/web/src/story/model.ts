// Pure helpers for the Summary: the KPI column an event moved and the daily series SQL derived from a
// verification row.
import type { TableInfo, VerificationRow } from '../api'

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
