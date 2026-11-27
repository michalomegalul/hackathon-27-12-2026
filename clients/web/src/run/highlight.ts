// Where in the user's prompt each verification row's event is told: the clause (or 2–3
// neighbouring clauses) that shares the most words with the row's claim_cs, its KPI, its target
// and its start month. Czech is inflected, so words compare by their first 5 letters without
// diacritics ("tržby" = "tržeb", "Plzni" = "Plzeň"). No match good enough: the event becomes a
// chip under the prompt instead.
import type { VerificationRow } from '../api'

export type Span = { start: number; end: number; events: string[]; rows: string[] }
export type Highlights = { spans: Span[]; unmatched: string[] }

export const rowKey = (v: VerificationRow) => `${v.event_id}·${v.kpi}·${v.target}`

const fold = (s: string) => s.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '')
const stem = (w: string) => fold(w).slice(0, 5)

const STOP = new Set(
  'který která které kvůli které jsou bude budou jako jeho jejich také tento tato toto proto nebo když protože však ještě již přes pouze data zboží vede'
    .split(' ')
    .map(stem),
)

/** words a story uses for each KPI (stems) */
const KPI_WORDS: Record<string, string[]> = {
  orders: ['objed', 'tržb', 'trzb', 'prode', 'nákup', 'nakup', 'klesl', 'pokle', 'kupuj', 'utrž'],
  leavers: ['odchá', 'odcha', 'odejd', 'odcho', 'odešl', 'odesl', 'ztrác', 'ztrat', 'zákaz', 'zakaz'],
  new_customers: ['noví', 'novi', 'novýc', 'novyc', 'regis', 'přibý', 'pribý'],
  late_share: ['pozdě', 'pozde', 'pozdn', 'zpožd', 'zpozd', 'kurýr', 'kuryr', 'doruč', 'doruc', 'balík', 'balik', 'zásil', 'zasil', 'chodí', 'chodi'],
  late_churn: ['pozdě', 'pozde', 'zpožd', 'zpozd', 'odchá', 'odcha'],
  rating: ['hodno', 'recen', 'spoko', 'hvězd', 'hvezd'],
  cancellations: ['zruš', 'zrus', 'předp', 'predp', 'odhlá', 'odhla'],
  tickets: ['stížn', 'stizn', 'tiket', 'rekla', 'podpo', 'stěžu', 'stezu'],
  stockout_days: ['chybí', 'chybi', 'vypro', 'došl', 'dosl', 'zásob', 'zasob', 'dodáv', 'dodav'],
}

const MONTHS = ['led', 'únor', 'břez', 'dub', 'květ', 'červ', 'červen', 'srp', 'září', 'říj', 'listop', 'prosin']

function words(s: string): string[] {
  return (s.match(/[\p{L}\d]+/gu) ?? []).filter((w) => /\d/.test(w) || w.length >= 3).map(stem).filter((w) => !STOP.has(w))
}

type Clause = { start: number; end: number; words: string[]; sentence: number }

/** Clauses: split at sentence ends, commas, semicolons, dashes and " a " / " ale ". */
function clauses(text: string): Clause[] {
  const out: Clause[] = []
  // a "." between digits ("1. 3. 2026") or after a lone number is not a sentence end
  const re = /([.!?](?=\s+\p{Lu}|\s*$))|([,;:–—])|(\s(?:a|ale|i|že)\s)|(\n+)/gu
  let from = 0
  let sentence = 0
  let m: RegExpExecArray | null
  const push = (to: number) => {
    const raw = text.slice(from, to)
    const lead = raw.length - raw.trimStart().length
    const s = from + lead
    const e = from + raw.trimEnd().length
    if (e > s) out.push({ start: s, end: e, words: words(text.slice(s, e)), sentence })
  }
  while ((m = re.exec(text))) {
    push(m.index)
    from = m.index + m[0].length
    if (m[1] || m[4]) sentence++
  }
  push(text.length)
  return out
}

function hits(ws: string[], keys: Set<string>): number {
  let n = 0
  for (const w of new Set(ws))
    for (const k of keys)
      if (w === k || (k.length < 5 && w.startsWith(k))) {
        n++
        break
      }
  return n
}

function rowKeys(v: VerificationRow): { claim: Set<string>; kpi: Set<string>; when: Set<string> } {
  const d = new Date(`${v.start.slice(0, 10)}T00:00:00Z`)
  const when = new Set<string>()
  if (!Number.isNaN(d.getTime())) {
    when.add(stem(MONTHS[d.getUTCMonth()]))
    when.add(String(d.getUTCFullYear()))
  }
  const target = v.target.replace(/[a-z_]+=/g, ' ').replace(/[,;]/g, ' ')
  return {
    claim: new Set([...words(v.claim_cs), ...words(target)]),
    kpi: new Set((KPI_WORDS[v.kpi] ?? []).map(stem)),
    when,
  }
}

/** Score a candidate span for a row: shared words, KPI words count triple, a shorter span wins ties. */
function score(ws: string[], k: ReturnType<typeof rowKeys>): number {
  return hits(ws, k.claim) + 2 * hits(ws, k.kpi) + 1.5 * hits(ws, k.when) - 0.08 * ws.length
}

const MIN_SCORE = 2.2

export function findHighlights(text: string, rows: VerificationRow[]): Highlights {
  const cs = clauses(text)
  // candidates: 1 to 3 neighbouring clauses of one sentence
  const cand: { start: number; end: number; words: string[] }[] = []
  for (let i = 0; i < cs.length; i++)
    for (let n = 1; n <= 3 && i + n <= cs.length; n++) {
      const part = cs.slice(i, i + n)
      if (part.some((c) => c.sentence !== cs[i].sentence)) break
      cand.push({ start: part[0].start, end: part[n - 1].end, words: part.flatMap((c) => c.words) })
    }

  // best candidate per row, strongest rows first; a row may not take text another event holds
  const scored = rows.map((v) => {
    const k = rowKeys(v)
    const ranked = cand.map((c) => ({ c, s: score(c.words, k) })).sort((a, b) => b.s - a.s)
    return { v, ranked }
  })
  scored.sort((a, b) => (b.ranked[0]?.s ?? 0) - (a.ranked[0]?.s ?? 0))

  const spans: Span[] = []
  const overlaps = (a: { start: number; end: number }, b: { start: number; end: number }) => a.start < b.end && b.start < a.end
  for (const { v, ranked } of scored) {
    for (const { c, s } of ranked) {
      if (s < MIN_SCORE) break
      const clash = spans.filter((x) => overlaps(x, c))
      // the same span (or one inside a span) of the same event: share it
      const same = clash.find((x) => x.events.includes(v.event_id) && x.start <= c.start && x.end >= c.end)
      if (same) {
        same.rows.push(rowKey(v))
        break
      }
      if (clash.length) continue
      spans.push({ start: c.start, end: c.end, events: [v.event_id], rows: [rowKey(v)] })
      break
    }
  }
  spans.sort((a, b) => a.start - b.start)
  const placed = new Set(spans.flatMap((s) => s.rows))
  const unmatched = [...new Set(rows.filter((v) => !placed.has(rowKey(v))).map((v) => v.event_id))]
  return { spans, unmatched }
}
