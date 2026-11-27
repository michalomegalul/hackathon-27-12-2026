// The result's spec_yaml, read for the Spec section. It is always PyYAML's safe_dump of the
// validated spec (s2d/compiler.py spec_to_yaml: block style, `{}`/`[]` only when empty, long
// strings folded at 100 columns), so a small reader of that subset is enough: no YAML library.
// Anything it cannot read returns null and the section falls back to the verification rows.
import { useMemo } from 'react'

export type Yaml = string | number | boolean | null | Yaml[] | { [k: string]: Yaml }

type Line = { indent: number; text: string }

function unquote(s: string): string {
  if (s.startsWith("'")) return s.slice(1, -1).replaceAll("''", "'")
  if (s.startsWith('"'))
    try {
      return JSON.parse(s) as string
    } catch {
      return s.slice(1, -1)
    }
  return s
}

function scalar(raw: string): Yaml {
  const s = raw.trim()
  if (s === '' || s === '~' || s === 'null') return null
  if (s === '{}') return {}
  if (s === '[]') return []
  if (s === 'true') return true
  if (s === 'false') return false
  if (/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(s)) return Number(s)
  if (s.startsWith('[') && s.endsWith(']'))
    return s
      .slice(1, -1)
      .split(',')
      .map((x) => x.trim())
      .filter(Boolean)
      .map(scalar)
  return unquote(s)
}

/** `key: value` → [key, value]; a quoted key or a plain one, the value may be empty. */
function keyValue(text: string): [string, string] | null {
  const m = /^('(?:[^']|'')*'|"(?:[^"\\]|\\.)*"|[^\s'"#][^:#]*?):(?:\s+(.*))?$/.exec(text)
  return m ? [unquote(m[1]), m[2] ?? ''] : null
}

/** Join folded continuation lines onto the scalar they continue (a blank line is a newline). */
function logical(src: string): Line[] {
  const out: Line[] = []
  let open: Line | null = null // the last line whose value is a scalar that may continue
  let openCol = 0 // the column of its key (or its item, after "- ")
  let blank = false
  for (const raw of src.split('\n')) {
    if (/^\s*#/.test(raw)) continue
    if (raw.trim() === '') {
      blank = true
      continue
    }
    const indent = raw.length - raw.trimStart().length
    const text = raw.trim()
    if (open && indent > openCol) {
      open.text += blank ? `\n${text}` : ` ${text}`
      blank = false
      continue
    }
    blank = false
    const line = { indent, text }
    out.push(line)
    const dash = text.startsWith('- ')
    const body = dash ? text.slice(2).trim() : text
    const kv = keyValue(body)
    open = (kv ? kv[1] : body) !== '' && !(kv && /^[[{]/.test(kv[1])) ? line : null
    openCol = dash ? indent + 2 : indent
  }
  return out
}

export function parseYaml(src: string): Yaml {
  const lines = logical(src)
  let i = 0

  function block(indent: number): Yaml {
    const first = lines[i]
    if (!first || first.indent < indent) return null
    return first.text.startsWith('- ') || first.text === '-' ? seq(first.indent) : map(first.indent)
  }

  function map(indent: number, into: { [k: string]: Yaml } = {}): { [k: string]: Yaml } {
    while (i < lines.length && lines[i].indent === indent && !lines[i].text.startsWith('- ')) {
      const kv = keyValue(lines[i].text)
      if (!kv) throw new Error(`yaml: ${lines[i].text}`)
      i++
      const [k, v] = kv
      if (v !== '') into[k] = scalar(v)
      else {
        const next = lines[i]
        // a block sequence may sit at the key's own indent (PyYAML's default)
        if (next && (next.indent > indent || (next.indent === indent && next.text.startsWith('- '))))
          into[k] = next.text.startsWith('- ') ? seq(next.indent) : map(next.indent)
        else into[k] = null
      }
    }
    return into
  }

  function seq(indent: number): Yaml[] {
    const out: Yaml[] = []
    while (i < lines.length && lines[i].indent === indent && (lines[i].text.startsWith('- ') || lines[i].text === '-')) {
      const rest = lines[i].text.slice(1).trim()
      const inner = indent + 2
      if (rest === '') {
        i++
        out.push(block(inner))
        continue
      }
      const kv = keyValue(rest)
      if (kv) {
        // "- key: v" starts a mapping whose other keys sit at indent + 2
        lines[i] = { indent: inner, text: rest }
        out.push(map(inner))
      } else {
        i++
        out.push(scalar(rest))
      }
    }
    return out
  }

  const v = block(0)
  if (i < lines.length) throw new Error(`yaml: unread line ${lines[i].text}`)
  return v
}

// ---- the spec, as far as the Spec section needs it ---------------------------------------

export type Target = Partial<Record<'segment' | 'city' | 'channel' | 'category' | 'supplier' | 'product', string[]>>
export type Effect = {
  metric: string
  size: number
  size_stated?: boolean
  lag_days?: number
  ramp_days?: number
  duration_days?: number | null
}
export type SpecEvent = {
  id: string
  type: string
  start: string
  target: Target
  effects: Effect[]
  caused_by?: string | null
  narrative_cs?: string
}
export type Spec = {
  meta: { start: string; days: number; seed?: number; difficulty?: string }
  company: {
    name: string
    legal_form?: string
    industry?: string
    description?: string
    channels: { channel: string; weight: number }[]
    cities: { name: string; weight: number; has_store?: boolean }[]
  }
  customers: { n: number; growth_per_year?: number; segments: { id: string; share: number; subscription?: boolean }[] }
  categories: { id: string; supplier?: string }[]
  suppliers: { id: string; name: string }[]
  events: SpecEvent[]
}

type Obj = { [k: string]: Yaml }
const obj = (v: Yaml | undefined): Obj => (v && typeof v === 'object' && !Array.isArray(v) ? v : {})
const arr = (v: Yaml | undefined): Yaml[] => (Array.isArray(v) ? v : [])
const str = (v: Yaml | undefined) => (v === null || v === undefined ? '' : String(v))
const nr = (v: Yaml | undefined) => (typeof v === 'number' ? v : Number(v ?? NaN))

/** channels are `{channel, weight}` after validation; hand-written specs use `{eshop: 0.55}`. */
function channel(v: Yaml): { channel: string; weight: number } {
  const o = obj(v)
  if ('channel' in o) return { channel: str(o.channel), weight: nr(o.weight) }
  const [k, w] = Object.entries(o)[0] ?? ['?', null]
  return { channel: k, weight: nr(w) }
}

export function readSpec(yaml: string): Spec | null {
  try {
    const root = obj(parseYaml(yaml))
    const meta = obj(root.meta)
    const company = obj(root.company)
    const ent = obj(root.entities)
    const cust = obj(ent.customers)
    return {
      meta: { start: str(meta.start), days: nr(meta.days), seed: nr(meta.seed), difficulty: str(meta.difficulty) },
      company: {
        name: str(company.name),
        legal_form: str(company.legal_form),
        industry: str(company.industry),
        description: str(company.description),
        channels: arr(company.channels).map(channel),
        cities: arr(company.cities).map((c) => {
          const o = obj(c)
          return { name: str(o.name), weight: nr(o.weight), has_store: o.has_store === true }
        }),
      },
      customers: {
        n: nr(cust.n),
        growth_per_year: nr(cust.growth_per_year),
        segments: arr(cust.segments).map((s) => {
          const o = obj(s)
          return { id: str(o.id), share: nr(o.share), subscription: o.subscription === true }
        }),
      },
      categories: arr(obj(ent.products).categories).map((c) => ({ id: str(obj(c).id), supplier: str(obj(c).supplier) })),
      suppliers: arr(ent.suppliers).map((s) => ({ id: str(obj(s).id), name: str(obj(s).name) })),
      events: arr(root.events).map((e) => {
        const o = obj(e)
        return {
          id: str(o.id),
          type: str(o.type),
          start: str(o.start),
          target: Object.fromEntries(Object.entries(obj(o.target)).map(([k, v]) => [k, arr(v).map(str)])) as Target,
          effects: arr(o.effects).map((x) => {
            const f = obj(x)
            return {
              metric: str(f.metric),
              size: nr(f.size),
              size_stated: f.size_stated === true,
              lag_days: nr(f.lag_days ?? 0),
              ramp_days: nr(f.ramp_days ?? 0),
              duration_days: f.duration_days === null || f.duration_days === undefined ? null : nr(f.duration_days),
            }
          }),
          caused_by: o.caused_by === undefined ? null : (o.caused_by as string | null),
          narrative_cs: str(o.narrative_cs),
        }
      }),
    }
  } catch {
    return null
  }
}

// ---- Czech labels ----------------------------------------------------------------------

export const CHANNEL_CS: Record<string, string> = { eshop: 'e-shop', store: 'physical stores', app: 'app', marketplace: 'marketplace' }

/** s2d/spec.py EventType */
export const EVENT_TYPE_CS: Record<string, string> = {
  price_change: 'price change',
  churn_shock: 'customer churn',
  competitor_entry: 'new competitor',
  campaign: 'campaign',
  supplier_delay: 'supplier delay',
  stockout: 'stock-out',
  courier_change: 'courier change',
  service_outage: 'service outage',
  quality_issue: 'quality issue',
  staff_shortage: 'staff shortage',
  viral_spike: 'viral spike',
}

/** s2d/spec.py Metric, the ones format.METRIC_CS (the detective's) does not name */
export const SPEC_METRIC_CS: Record<string, string> = {
  basket_size: 'basket size',
  return_rate: 'returns',
  payment_failure_rate: 'failed payments',
}

export const TARGET_CS: Record<keyof Target, string> = {
  segment: 'segment',
  city: 'city',
  channel: 'channel',
  category: 'category',
  supplier: 'supplier',
  product: 'product',
}

/** "segment student · city Brno", or "everyone" for an empty target. */
export function targetCs(t: Target, spec?: Spec): string {
  const parts = Object.entries(t)
    .filter(([, v]) => v && v.length)
    .map(([k, v]) => {
      const names = v!.map((x) =>
        k === 'channel' ? (CHANNEL_CS[x] ?? x) : k === 'supplier' ? (spec?.suppliers.find((s) => s.id === x)?.name ?? x) : x,
      )
      return `${TARGET_CS[k as keyof Target] ?? k} ${names.join(', ')}`
    })
  return parts.length ? parts.join(' · ') : 'everyone'
}

/** "42 days" / "6 weeks" / "no lag" */
export function lagCs(d: number | undefined): string {
  if (!d) return 'none'
  if (d % 7 === 0 && d >= 14) return `${d / 7} weeks`
  return d === 1 ? '1 day' : `${d} days`
}

const DAY_MS = 86_400_000
export const addDays = (iso: string, n: number) => new Date(Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) + n * DAY_MS).toISOString().slice(0, 10)

/** When the event's effects end (start + lag + duration), or null when one of them lasts. */
export function eventEnd(e: SpecEvent): string | null {
  let end = 0
  for (const f of e.effects) {
    if (f.duration_days === null || f.duration_days === undefined) return null
    end = Math.max(end, (f.lag_days ?? 0) + f.duration_days)
  }
  return e.effects.length ? addDays(e.start, end) : null
}

/** The result's spec, parsed once per YAML; null when it cannot be read. */
export function useSpec(yaml: string | undefined): Spec | null {
  return useMemo(() => (yaml ? readSpec(yaml) : null), [yaml])
}
