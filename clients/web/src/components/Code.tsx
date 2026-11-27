// SQL on screen: a light highlighter (keywords, types, strings, numbers, comments, "quoted"
// identifiers) and a copy button. No library: the SQL here is our own DDL and DuckDB queries.
import { useState, type ReactNode } from 'react'

export function CopyButton({ text, label = 'Copy', className = '' }: { text: string; label?: string; className?: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setDone(true)
          setTimeout(() => setDone(false), 1500)
        })
      }}
      className={`border border-line px-2 py-0.5 text-xs text-slate-300 hover:border-slate-500 hover:text-white ${className}`}
    >
      {done ? 'Copied ✓' : label}
    </button>
  )
}

const KEYWORDS = new Set(
  `select from where and or not null is in as on join left right inner outer full cross using group by order having limit offset
  with case when then else end distinct union all create table primary key foreign references constraint filter over partition
  asc desc nulls last first true false between like ilike cast interval date exists`
    .split(/\s+/)
    .filter(Boolean),
)
const TYPES = new Set('bigint integer int double precision numeric text date timestamp boolean varchar real smallint'.split(' '))

const TOKEN = /(--[^\n]*)|('(?:[^']|'')*')|("(?:[^"]|"")*")|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+|.)/g

function highlight(sql: string): ReactNode[] {
  const out: ReactNode[] = []
  let k = 0
  for (const m of sql.matchAll(TOKEN)) {
    const [t, comment, str, ident, n, word] = m
    const cls = comment
      ? 'text-slate-500 italic'
      : str
        ? 'text-amber-200'
        : ident
          ? 'text-sky-200'
          : n
            ? 'text-violet-300'
            : word && KEYWORDS.has(word.toLowerCase())
              ? 'text-rose-300'
              : word && TYPES.has(word.toLowerCase())
                ? 'text-emerald-300'
                : ''
    out.push(cls ? <span key={k++} className={cls}>{t}</span> : t)
  }
  return out
}

/** Highlighted SQL in a scrolling box, with a copy button in its corner. */
export function SqlBlock({ sql, maxH = 'max-h-96', title }: { sql: string; maxH?: string; title?: ReactNode }) {
  return (
    <div className="relative min-w-0 border border-line bg-bg/70">
      <div className="flex items-center gap-2 border-b border-line/70 px-3 py-1.5 text-xs text-muted">
        <span className="min-w-0 flex-1 truncate">{title ?? 'SQL'}</span>
        <CopyButton text={sql} />
      </div>
      <pre className={`${maxH} overflow-auto px-3 py-2 font-mono text-[11.5px] leading-relaxed text-slate-300`}>
        <code>{highlight(sql)}</code>
      </pre>
    </div>
  )
}
