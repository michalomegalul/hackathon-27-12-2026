// /run/:id/data: browse the analyst tables (GET /tables, /tables/{name}) and run SQL (POST /query).
// A verification row's "Spustit SQL" lands here with its SQL and expected result in the router state.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query'
import { Link, useLocation, useParams, useSearchParams } from 'react-router'
import {
  isStatus,
  jobOptions,
  runQuery,
  tableRowsOptions,
  tablesOptions,
  type Cell,
  type Column,
  type QueryResult,
  type TableInfo,
} from '../api'
import { DataGrid } from '../components/DataGrid'
import { Alert, Card, JobStatusBadge, Spinner } from '../components/ui'
import { intCs, num, rowsCs } from '../format'

/** What a verification row hands over: its SQL, and the row the pipeline got from it. */
export type SqlCheck = { sql: string; label?: string; expect?: Record<string, unknown> | null }

const quoteId = (s: string) => `"${s.replaceAll('"', '""')}"`

// ---- table list ------------------------------------------------------------------------

function TableList({ tables, active, onPick }: { tables: TableInfo[]; active?: string; onPick: (name: string) => void }) {
  return (
    // phones: one scrolling row; lg: a column beside the grid
    <ul className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1 lg:mx-0 lg:grid lg:overflow-visible lg:px-0 lg:pb-0">
      {tables.map((t) => (
        <li key={t.name} className="shrink-0">
          <button
            onClick={() => onPick(t.name)}
            title={t.columns.map((c) => `${c.name} ${c.type}`).join('\n')}
            className={`grid w-full grid-cols-[1fr_auto] items-baseline gap-x-2 rounded-lg px-3 py-1.5 text-left ${
              t.name === active ? 'bg-accent/15 ring-1 ring-accent/40' : 'hover:bg-white/5'
            }`}
          >
            <span className="truncate font-mono text-sm">{t.name}</span>
            <span className="text-xs tabular-nums text-muted">{intCs(t.rows)}</span>
            <span className="col-span-2 text-[11px] text-muted">
              {t.columns.length} {t.columns.length < 5 ? 'sloupce' : 'sloupců'}
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}

// ---- one table, paged by offset as you scroll --------------------------------------------

function TableView({ id, name, onSortAll }: { id: string; name: string; onSortAll: (col: string, desc: boolean) => void }) {
  const q = useInfiniteQuery(tableRowsOptions(id, name, true))
  const pages = q.data?.pages
  const rows = useMemo(() => pages?.flatMap((p) => p.rows) ?? [], [pages])
  const columns = useMemo<Column[]>(() => pages?.[0]?.columns ?? [], [pages])
  const { hasNextPage, isFetchingNextPage, fetchNextPage, isFetchNextPageError } = q
  const loadMore = useCallback(() => {
    if (!isFetchNextPageError) void fetchNextPage()
  }, [fetchNextPage, isFetchNextPageError])

  if (q.isPending)
    return (
      <p className="py-10 text-center text-sm text-muted">
        <Spinner /> Načítám {name}…
      </p>
    )
  if (q.isError && !pages) return <Alert>{q.error.message}</Alert>

  return (
    <DataGrid
      key={name}
      columns={columns}
      rows={rows}
      total={pages?.[0]?.total}
      hasMore={hasNextPage && !isFetchNextPageError}
      loadingMore={isFetchingNextPage}
      onLoadMore={loadMore}
      onSortAll={onSortAll}
      footer={
        isFetchNextPageError && (
          <span className="text-rose-300">
            Další řádky se nenačetly ({q.error?.message}).{' '}
            <button className="underline" onClick={() => void fetchNextPage()}>
              Zkusit znovu
            </button>
          </span>
        )
      }
    />
  )
}

// ---- SQL ---------------------------------------------------------------------------------

/** Compare the query's first row with the verification row's sql_result (2 decimals in the result). */
function CheckResult({ expect, res }: { expect: Record<string, unknown>; res: QueryResult }) {
  const first = res.rows[0]
  const keys = Object.keys(expect)
  return (
    <ul className="flex flex-wrap gap-1.5 text-xs">
      {keys.map((k) => {
        const i = res.columns.findIndex((c) => c.name === k)
        const want = expect[k]
        const got: Cell | undefined = i >= 0 && first ? first[i] : undefined
        const ok =
          typeof want === 'number' && typeof got === 'number'
            ? Math.abs(want - got) <= 0.0051 + Math.abs(want) * 1e-9
            : (want ?? null) === (got ?? null)
        const show = (v: unknown) => (typeof v === 'number' ? num(v, 2) : v === null || v === undefined ? 'null' : String(v))
        return (
          <li
            key={k}
            title={`ověření: ${show(want)} · dotaz: ${show(got)}`}
            className={`rounded-md px-2 py-0.5 font-mono ring-1 ring-inset ${
              ok ? 'bg-emerald-500/10 text-emerald-200 ring-emerald-500/30' : 'bg-rose-500/10 text-rose-200 ring-rose-500/30'
            } ${k === 'did_pct' ? 'font-semibold' : ''}`}
          >
            {k} {show(got)} {ok ? '✓' : `≠ ${show(want)}`}
          </li>
        )
      })}
    </ul>
  )
}

function QueryError({ err }: { err: Error }) {
  if (isStatus(err, 400))
    return (
      <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
        <div className="mb-1 font-medium">Chyba v SQL</div>
        <pre className="overflow-x-auto whitespace-pre font-mono text-xs leading-relaxed">{err.message}</pre>
      </div>
    )
  if (isStatus(err, 408)) return <Alert t="amber">{err.message}</Alert>
  return <Alert>{err.message}</Alert>
}

// ---- page --------------------------------------------------------------------------------

export function DataPage() {
  const { id = '' } = useParams()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const job = useQuery(jobOptions(id))
  const done = job.data?.status === 'done'
  const tables = useQuery(tablesOptions(id, done))

  const [sql, setSql] = useState('')
  const [check, setCheck] = useState<SqlCheck | null>(null)
  const [view, setView] = useState<'table' | 'query'>('table')
  const query = useMutation({ mutationFn: (s: string) => runQuery(id, s) })
  const { mutate } = query
  const sqlRef = useRef<HTMLTextAreaElement>(null)

  const list = tables.data?.tables
  const tableName = params.get('t') ?? list?.find((t) => t.name === 'orders')?.name ?? list?.[0]?.name

  const run = useCallback(
    (s: string) => {
      if (!s.trim()) return
      setView('query')
      mutate(s)
    },
    [mutate],
  )

  // "Spustit SQL" from a verification row: pre-fill and run once per navigation (StrictMode runs effects twice)
  const handled = useRef<string | null>(null)
  const incoming = (location.state as SqlCheck | null) ?? null
  useEffect(() => {
    if (!done || !incoming?.sql || handled.current === location.key) return
    handled.current = location.key
    setSql(incoming.sql)
    setCheck(incoming)
    run(incoming.sql)
    sqlRef.current?.scrollIntoView({ block: 'nearest' })
  }, [done, incoming, location.key, run])

  const pickTable = (name: string) => {
    setView('table')
    setParams({ t: name }, { replace: true, state: location.state })
  }
  const sortAll = (col: string, desc: boolean) => {
    if (!tableName) return
    const s = `SELECT *\nFROM ${quoteId(tableName)}\nORDER BY ${quoteId(col)} ${desc ? 'DESC' : 'ASC'} NULLS LAST\nLIMIT 1000`
    setSql(s)
    setCheck(null)
    run(s)
  }

  const back = (
    <Link to={`/run/${id}#s-data`} className="text-sm text-muted hover:text-white">
      ← Zpět na běh {id}
    </Link>
  )

  if (job.error)
    return (
      <div className="grid gap-4">
        <Alert>{job.error.message}</Alert>
        <Link to="/history" className="text-accent hover:underline">
          ← History
        </Link>
      </div>
    )
  if (!job.data)
    return (
      <p className="text-muted">
        <Spinner /> Načítám…
      </p>
    )
  if (!done)
    return (
      <div className="grid gap-4">
        {back}
        <Card>
          <div className="flex items-center gap-3">
            <JobStatusBadge s={job.data.status} />
            <span className="text-sm">
              {job.data.status === 'error' ? 'Úloha skončila chybou, data nejsou k dispozici.' : 'Data budou k dispozici, až úloha doběhne.'}
            </span>
          </div>
        </Card>
      </div>
    )

  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        {back}
        <h1 className="text-xl font-semibold tracking-tight">Data</h1>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[15rem_minmax(0,1fr)]">
        <Card className="self-start p-2 sm:p-2">
          <h2 className="px-3 pb-1 pt-1 text-xs uppercase tracking-wide text-muted">Tabulky</h2>
          {tables.data ? (
            <TableList tables={tables.data.tables} active={view === 'table' ? tableName : undefined} onPick={pickTable} />
          ) : tables.error ? (
            <div className="p-2">
              <Alert>{tables.error.message}</Alert>
            </div>
          ) : (
            <p className="px-3 py-2 text-sm text-muted">
              <Spinner /> Načítám…
            </p>
          )}
        </Card>

        <div className="grid min-w-0 grid-cols-1 gap-4">
          <Card>
            <form
              className="grid gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                setCheck(null)
                run(sql)
              }}
            >
              <label htmlFor="sql" className="flex items-baseline justify-between gap-2">
                <span className="font-semibold">SQL</span>
                <span className="text-xs text-muted">DuckDB · nejvýš 1000 řádků · limit 20 s · Ctrl+Enter spustí</span>
              </label>
              {check?.label && (
                <p className="text-xs text-muted">
                  Ověřujete <b className="text-slate-200">{check.label}</b>: dotaz má dát stejná čísla, jaká naměřilo ověření.
                </p>
              )}
              <textarea
                id="sql"
                ref={sqlRef}
                value={sql}
                onChange={(e) => {
                  setSql(e.target.value)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault()
                    e.currentTarget.form?.requestSubmit()
                  }
                }}
                rows={Math.min(16, Math.max(4, sql.split('\n').length + 1))}
                spellCheck={false}
                placeholder={`SELECT *\nFROM ${tableName ?? 'orders'}\nLIMIT 100`}
                className="w-full resize-y rounded-lg border border-line bg-bg px-3 py-2 font-mono text-[16px] leading-relaxed focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent sm:text-xs"
              />
              <div className="flex flex-wrap items-center gap-3">
                <button
                  disabled={query.isPending || !sql.trim()}
                  className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 font-medium text-slate-950 hover:brightness-110 disabled:opacity-60"
                >
                  {query.isPending ? <Spinner /> : '▶'} Spustit
                </button>
                {query.data && !query.isPending && (
                  <span className="text-xs tabular-nums text-muted">
                    {rowsCs(query.data.rows.length)} za {num(query.data.seconds, 2)} s
                  </span>
                )}
                {check?.expect && query.data && !query.isPending && <CheckResult expect={check.expect} res={query.data} />}
              </div>
              {query.error && !query.isPending && <QueryError err={query.error} />}
            </form>
          </Card>

          <Card className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-1 text-sm" role="tablist">
              {tableName && (
                <button
                  role="tab"
                  aria-selected={view === 'table'}
                  onClick={() => setView('table')}
                  className={`rounded-md px-2.5 py-1 font-mono ${view === 'table' ? 'bg-white/10 text-white' : 'text-muted hover:text-white'}`}
                >
                  {tableName}
                </button>
              )}
              {(query.data || query.isPending || query.error) && (
                <button
                  role="tab"
                  aria-selected={view === 'query'}
                  onClick={() => setView('query')}
                  className={`rounded-md px-2.5 py-1 ${view === 'query' ? 'bg-white/10 text-white' : 'text-muted hover:text-white'}`}
                >
                  Výsledek dotazu
                </button>
              )}
            </div>

            {view === 'table' && tableName && <TableView id={id} name={tableName} onSortAll={sortAll} />}
            {view === 'query' &&
              (query.isPending ? (
                <p className="py-10 text-center text-sm text-muted">
                  <Spinner /> Dotaz běží…
                </p>
              ) : query.data ? (
                <div className="grid gap-2">
                  {query.data.truncated && (
                    <Alert t="amber">
                      Výsledek je zkrácený na prvních {intCs(query.data.rows.length)} řádků. Pro celý výsledek přidejte agregaci, WHERE
                      nebo si stáhněte ZIP s analyst.duckdb.
                    </Alert>
                  )}
                  <DataGrid key={query.submittedAt} columns={query.data.columns} rows={query.data.rows} fit />
                </div>
              ) : query.error ? (
                <p className="py-6 text-center text-sm text-muted">Dotaz skončil chybou, viz výše.</p>
              ) : null)}
          </Card>
        </div>
      </div>
    </div>
  )
}
