// Virtualized, sortable grid for /tables/{name} pages and /query results (TanStack Table 9 +
// Virtual 3, after docs/research/web-stack.md). Rows are arrays in column order, as the API sends them.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  createSortedRowModel,
  rowSortingFeature,
  sortFn_basic,
  tableFeatures,
  useTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { Cell, Column } from '../api'
import { intCs, rowsCs } from '../format'
import { Spinner } from './ui'

type Row = Cell[]

const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
})

// ---- cell formatting -------------------------------------------------------------------

type Kind = 'int' | 'float' | 'date' | 'ts' | 'bool' | 'text'

function kindOf(type: string): Kind {
  const t = type.toUpperCase()
  if (t.startsWith('TIMESTAMP')) return 'ts'
  if (t === 'DATE') return 'date'
  if (t === 'BOOLEAN') return 'bool'
  if (/^(U?(BIG|SMALL|TINY|HUGE)?INT(EGER)?\d*|U?HUGEINT)$/.test(t)) return 'int'
  if (/^(DOUBLE|FLOAT|REAL|DECIMAL|NUMERIC)/.test(t)) return 'float'
  return 'text'
}

const WIDTH: Record<Kind, number> = { int: 7, float: 8, date: 7, ts: 10.5, bool: 5, text: 11 }
const NUM_W = 4.5 // the row-number column

const flt = new Intl.NumberFormat('cs-CZ', { maximumFractionDigits: 4, useGrouping: false })

/** "2025-01-01" → 1. 1. 2025; "2025-01-01T19:05:13" → 1. 1. 2025 19:05:13. Parsed by hand: no time-zone shift. */
const ISO = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?))?/
function fmtDate(v: string, withTime: boolean): string {
  const m = ISO.exec(v)
  if (!m) return v
  const d = `${+m[3]}. ${+m[2]}. ${m[1]}`
  return withTime && m[4] ? `${d} ${m[4]}` : d
}

function fmt(v: Cell | undefined, kind: Kind): ReactNode {
  if (v === null || v === undefined) return <span className="italic text-muted/50">null</span>
  if (typeof v === 'boolean') return v ? 'ano' : 'ne'
  if (typeof v === 'number') return kind === 'float' || !Number.isInteger(v) ? flt.format(v) : String(v)
  if (typeof v === 'string') return kind === 'date' || kind === 'ts' ? fmtDate(v, kind === 'ts') : v
  return JSON.stringify(v) // LIST / STRUCT from a query
}

const plain = (v: Cell | undefined) => (v === null || v === undefined ? 'null' : typeof v === 'object' ? JSON.stringify(v) : String(v))

// ---- grid --------------------------------------------------------------------------------

const ROW_H = 28

export type DataGridProps = {
  columns: Column[]
  rows: Row[]
  /** Rows in the source (a table's `total`); more than `rows.length` means more pages to load. */
  total?: number
  hasMore?: boolean
  loadingMore?: boolean
  onLoadMore?: () => void
  /** Sorting only sees the loaded rows: offer an ORDER BY over the whole table instead. */
  onSortAll?: (column: string, desc: boolean) => void
  footer?: ReactNode
  /** Shrink to the rows instead of a fixed 60vh (query results are often one row). */
  fit?: boolean
}

export function DataGrid({ columns, rows, total, hasMore = false, loadingMore = false, onLoadMore, onSortAll, footer, fit = false }: DataGridProps) {
  const [sorting, setSorting] = useState<SortingState>([])
  const sorted = sorting.length > 0

  // stable references (web-stack.md): rebuilt only when the columns change
  const defs = useMemo<ColumnDef<typeof features, Row>[]>(
    () => [
      {
        id: '__n',
        header: '#',
        enableSorting: false,
        cell: ({ row }) => <span className="text-muted/60">{row.index + 1}</span>,
      },
      ...columns.map((c, i): ColumnDef<typeof features, Row> => {
        const kind = kindOf(c.type)
        return {
          id: `c${i}`, // a query may return two columns with the same name
          accessorFn: (r: Row) => r[i] ?? undefined, // null → undefined, so sortUndefined puts it last
          header: c.name,
          sortFn: sortFn_basic, // numbers, ISO dates and strings all compare with < and >
          sortUndefined: 'last',
          sortDescFirst: kind === 'int' || kind === 'float',
          cell: ({ row }) => fmt(row.original[i], kind),
        }
      }),
    ],
    [columns],
  )
  const kinds = useMemo(() => columns.map((c) => kindOf(c.type)), [columns])
  // wide enough for the header name too (bold mono 11px ≈ 0.42rem a character, plus padding and the sort arrow)
  const widths = useMemo(() => columns.map((c, i) => Math.max(WIDTH[kinds[i]], Math.min(16, c.name.length * 0.42 + 1.75))), [columns, kinds])

  const table = useTable({
    features,
    columns: defs,
    data: rows,
    state: { sorting },
    onSortingChange: setSorting,
  })
  const { rows: tableRows } = table.getRowModel()

  const scrollRef = useRef<HTMLDivElement>(null)
  const loading = hasMore && !sorted // while sorted, loading more would reshuffle what is on screen
  // The React Compiler would skip this component; the app doesn't use the compiler, so this is fine.
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: tableRows.length + (loading ? 20 : 0), // a few placeholder rows at the end while more pages exist
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_H, // fixed row height: no measureElement needed
    overscan: 12,
    useFlushSync: false, // avoids the React 19 flushSync warning while scrolling
  })
  const items = virtualizer.getVirtualItems()
  const lastIndex = items.at(-1)?.index ?? 0

  // fetch the next page when the viewport comes within ~300 rows of the end of what is loaded
  useEffect(() => {
    if (loading && !loadingMore && lastIndex >= tableRows.length - 300) onLoadMore?.()
  }, [loading, loadingMore, lastIndex, tableRows.length, onLoadMore])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
  }, [sorting])

  const template = [`${NUM_W}rem`, ...kinds.map((k, i) => `minmax(${widths[i]}rem, ${k === 'text' ? 2 : 1}fr)`)].join(' ')
  const minWidth = `${NUM_W + widths.reduce((s, w) => s + w, 0)}rem`
  const right = (i: number) => kinds[i] === 'int' || kinds[i] === 'float'

  const sortCol = sorting[0]
  const sortName = sortCol ? columns[Number(sortCol.id.slice(1))]?.name : undefined
  const partial = total !== undefined && rows.length < total

  return (
    <div className="grid gap-2">
      {sorted && partial && (
        <div className="flex flex-wrap items-center gap-2 border-l-2 border-amber-500/70 py-1 pl-3 text-xs text-amber-100">
          Řazeno jen {intCs(rows.length)} načtených řádků z {intCs(total)}; další se během řazení nenačítají.
          {onSortAll && sortName && (
            <button
              className="bg-white/10 px-2 py-0.5 font-medium hover:bg-white/20"
              onClick={() => onSortAll(sortName, sortCol.desc)}
            >
              Seřadit celou tabulku v SQL
            </button>
          )}
          <button className="px-2 py-0.5 hover:bg-white/10" onClick={() => setSorting([])}>
            Zrušit řazení
          </button>
        </div>
      )}

      <div ref={scrollRef} className={`${fit ? 'max-h-[60vh]' : 'h-[60vh] min-h-72'} overflow-auto border border-line bg-bg/40 font-mono text-xs`}>
        <div style={{ minWidth }}>
          {/* display:grid rows so absolutely positioned rows keep the column widths */}
          <div
            className="sticky top-0 z-10 grid border-b border-line bg-panel text-[11px] text-slate-300"
            style={{ gridTemplateColumns: template }}
            role="row"
          >
            {table.getHeaderGroups()[0].headers.map((header, hi) => {
              const canSort = header.column.getCanSort()
              const dir = header.column.getIsSorted()
              const c = hi > 0 ? columns[hi - 1] : undefined
              return (
                <div
                  key={header.id}
                  role="columnheader"
                  aria-sort={dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : undefined}
                  title={c ? `${c.name} · ${c.type}` : undefined}
                  className={`flex min-w-0 select-none items-baseline gap-1 px-2 py-1.5 ${hi > 0 && right(hi - 1) ? 'justify-end' : ''} ${
                    canSort ? 'cursor-pointer hover:bg-white/5' : 'text-muted/60'
                  }`}
                  onClick={canSort ? header.column.getToggleSortingHandler() : undefined}
                >
                  <span className="truncate font-semibold">
                    <table.FlexRender header={header} />
                  </span>
                  {dir && <span className="text-accent">{dir === 'asc' ? '▲' : '▼'}</span>}
                </div>
              )
            })}
          </div>

          <div className="relative" style={{ height: virtualizer.getTotalSize() }}>
            {items.map((vi) => {
              const row = tableRows[vi.index]
              if (!row)
                return (
                  <div
                    key={`p${vi.index}`}
                    className="absolute inset-x-0 flex items-center px-2 text-muted/50"
                    style={{ height: vi.size, transform: `translateY(${vi.start}px)` }}
                  >
                    {vi.index === tableRows.length ? (
                      <>
                        <Spinner /> <span className="ml-2">načítám další řádky…</span>
                      </>
                    ) : (
                      <span className="h-2 w-1/3 bg-white/5" />
                    )}
                  </div>
                )
              return (
                <div
                  key={row.id}
                  role="row"
                  className={`absolute inset-x-0 grid items-center hover:bg-white/[0.04] ${vi.index % 2 ? 'bg-white/[0.015]' : ''}`}
                  style={{ gridTemplateColumns: template, height: vi.size, transform: `translateY(${vi.start}px)` }}
                >
                  {row.getAllCells().map((cell, ci) => (
                    <div
                      key={cell.id}
                      role="cell"
                      className={`truncate px-2 ${ci > 0 && right(ci - 1) ? 'text-right tabular-nums' : ''}`}
                      title={ci > 0 && kinds[ci - 1] === 'text' ? plain(row.original[ci - 1]) : undefined}
                    >
                      <table.FlexRender cell={cell} />
                    </div>
                  ))}
                </div>
              )
            })}
          </div>
          {rows.length === 0 && <div className="px-3 py-6 text-center font-sans text-sm text-muted">Žádné řádky.</div>}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 text-xs text-muted">
        <span className="tabular-nums">
          {total !== undefined && total !== rows.length
            ? `načteno ${intCs(rows.length)} z ${intCs(total)} řádků`
            : rowsCs(rows.length)}
        </span>
        {loadingMore && <Spinner />}
        <span className="hidden sm:inline">· klepnutím na záhlaví seřadíte</span>
        {footer}
      </div>
    </div>
  )
}
