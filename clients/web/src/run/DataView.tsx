// Data: the generated database as Postgres tables. Tabs: psql-style cards (columns, types,
// keys, the first 5 rows; the first 3 tables, the rest behind "show more") and the grid + SQL box.
// Lazy chunk: TanStack Table loads only with this section.
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { tableHeadOptions, tablesOptions, type Cell, type TableInfo } from '../api'
import { DownloadButton } from '../components/Download'
import { Alert, ShowMore, Spinner } from '../components/ui'
import { intCs, pgType, rowsCs } from '../format'
import { DataBrowser } from '../pages/DataPage'

export function KeyBadge({ kind, title }: { kind: 'PK' | 'FK'; title?: string }) {
  return (
    <span
      title={title}
      className={`px-1 text-[9.5px] font-semibold leading-4 ${kind === 'PK' ? 'bg-amber-400/15 text-amber-300' : 'bg-sky-400/15 text-sky-300'}`}
    >
      {kind}
    </span>
  )
}

const isNum = (t: string) => /INT|DOUBLE|FLOAT|DECIMAL|NUMERIC/i.test(t)

function cell(v: Cell) {
  if (v === null) return <span className="text-slate-600">null</span>
  if (typeof v === 'boolean') return v ? 't' : 'f' // psql prints booleans as t / f
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100)
  return v
}

/**
 * One table the way psql shows it: names, types and keys in the header, then `SELECT * … LIMIT 5`.
 * `lit` lights a column (the Shrnutí points at the one an event changed).
 */
export function PsqlTable({
  id,
  t: full,
  lit,
  rows = 5,
  only,
}: {
  id: string
  t: TableInfo
  lit?: string
  rows?: number
  /** show just these columns (in table order) */
  only?: string[]
}) {
  const q = useQuery(tableHeadOptions(id, full.name, rows))
  const keep = full.columns.map((c, i) => [c, i] as const).filter(([c]) => !only || only.includes(c.name))
  const t = { ...full, columns: keep.map(([c]) => c) }
  const pick = (r: Cell[]) => keep.map(([, i]) => r[i])
  const pk = new Set(t.primary_key ?? [])
  const fk = new Map((t.foreign_keys ?? []).map((f) => [f.column, `${f.references.table}.${f.references.column}`]))
  return (
    <div className="min-w-0 overflow-x-auto">
      <table className="font-mono text-[11px] leading-[18px] whitespace-nowrap">
        <thead>
          <tr>
            {t.columns.map((c, i) => (
              <th
                key={c.name}
                data-col={c.name}
                className={`px-2 pt-1 text-left align-bottom font-semibold transition-colors duration-300 ${i ? 'border-l border-line/70' : ''} ${
                  lit === c.name ? 'bg-accent/15 text-accent' : 'text-slate-200'
                }`}
              >
                {c.name}
              </th>
            ))}
          </tr>
          <tr className="border-b border-line">
            {t.columns.map((c, i) => (
              <th
                key={c.name}
                className={`px-2 pb-1 text-left font-normal transition-colors duration-300 ${i ? 'border-l border-line/70' : ''} ${
                  lit === c.name ? 'bg-accent/15 text-accent/80' : 'text-muted'
                }`}
              >
                <span className="inline-flex items-center gap-1">
                  {pgType(c.type)}
                  {pk.has(c.name) && <KeyBadge kind="PK" title="primární klíč" />}
                  {fk.has(c.name) && <KeyBadge kind="FK" title={`cizí klíč → ${fk.get(c.name)}`} />}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {q.data?.rows.map((r, j) => (
            <tr key={j}>
              {pick(r).map((v, i) => (
                <td
                  key={i}
                  className={`max-w-56 truncate px-2 ${i ? 'border-l border-line/70' : ''} ${isNum(t.columns[i]?.type ?? '') ? 'text-right tabular-nums' : ''} ${
                    lit === t.columns[i]?.name ? 'bg-accent/[0.07] text-accent' : 'text-slate-300'
                  }`}
                >
                  {cell(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {q.isPending && (
        <p className="px-2 py-1 text-xs text-muted">
          <Spinner /> Načítám první řádky…
        </p>
      )}
      {q.error && <p className="px-2 py-1 text-xs text-rose-300">{q.error.message}</p>}
      {q.data && (
        <p className="px-2 pt-1 font-mono text-[11px] text-muted">
          ({rowsCs(q.data.rows.length)} z {intCs(t.rows)}{only && keep.length < full.columns.length ? `, ${keep.length} z ${full.columns.length} sloupců` : ''})
        </p>
      )}
    </div>
  )
}

export function PsqlCard({ id, t, lit }: { id: string; t: TableInfo; lit?: string }) {
  return (
    <article className="grid min-w-0 gap-2 border-l-2 border-line py-1 pl-3">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <h3 className="font-mono text-sm font-semibold">
          <span className="text-slate-500">public.</span>
          {t.name}
        </h3>
        <span className="text-xs tabular-nums text-muted">{rowsCs(t.rows)}</span>
        {(t.foreign_keys?.length ?? 0) > 0 && (
          <span className="ml-auto font-mono text-[11px] text-slate-500">
            {t.foreign_keys!.map((f) => `${f.column} → ${f.references.table}`).join(' · ')}
          </span>
        )}
      </header>
      <PsqlTable id={id} t={t} lit={lit} />
    </article>
  )
}

type Tab = 'tables' | 'browse'
const TABS: [Tab, string][] = [
  ['tables', 'Tabulky'],
  ['browse', 'Hledat a SQL'],
]
const FIRST_TABLES = 3

export function DataView({ id }: { id: string }) {
  const q = useQuery(tablesOptions(id, true))
  const [tab, setTab] = useState<Tab>('tables')
  const [all, setAll] = useState(false)
  if (q.error) return <Alert>{q.error.message}</Alert>
  if (!q.data)
    return (
      <p className="text-sm text-muted">
        <Spinner /> Načítám tabulky…
      </p>
    )
  const tables = q.data.tables
  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex flex-wrap items-center gap-1" role="tablist">
        {TABS.map(([k, label]) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={`px-2.5 py-1 text-sm ${tab === k ? 'bg-white/10 text-white' : 'text-muted hover:text-white'}`}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto flex items-center gap-2">
          <Link to={`/run/${id}/data`} className="text-xs text-muted hover:text-white">
            celá stránka ↗
          </Link>
          <DownloadButton id={id} />
        </span>
      </div>
      {tab === 'tables' && (
        <div className="grid min-w-0 gap-3">
          {(all ? tables : tables.slice(0, FIRST_TABLES)).map((t) => (
            <PsqlCard key={t.name} id={id} t={t} />
          ))}
          {tables.length > FIRST_TABLES && (
            <ShowMore open={all} onClick={() => setAll((a) => !a)} more={tables.length - FIRST_TABLES} noun={['tabulku', 'tabulky', 'tabulek']} />
          )}
        </div>
      )}
      {tab === 'browse' && <DataBrowser id={id} />}
    </div>
  )
}
