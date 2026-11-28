// Rev story's input: the data, as the download ZIP of a run (or its customers.csv and orders.csv).
// The file never leaves the browser. Only a fingerprint goes to POST /v1/jobs/match: the row
// counts of customers and orders and up to 64 customers (id, e-mail) spread over the table
// (s2d/api/match.py). The ZIP is read here without a library: the central directory gives each
// entry's offset, and DecompressionStream('deflate-raw') inflates just the two CSVs, streamed, so
// a ZIP of hundreds of MB is never held in memory.

import type { MatchIn } from '../api'

const SAMPLE = 64

type Entry = { name: string; method: number; size: number; offset: number }

const u16 = (v: DataView, at: number) => v.getUint16(at, true)
const u32 = (v: DataView, at: number) => v.getUint32(at, true)
const bytes = async (f: Blob, from: number, to: number) => new DataView(await f.slice(from, to).arrayBuffer())

/** The ZIP's entries from its central directory (the end-of-central-directory record is in the last 64 kB). */
async function entries(f: File): Promise<Entry[]> {
  const tailFrom = Math.max(0, f.size - 65_557)
  const tail = await bytes(f, tailFrom, f.size)
  let eocd = -1
  for (let i = tail.byteLength - 22; i >= 0; i--)
    if (u32(tail, i) === 0x06054b50) {
      eocd = i
      break
    }
  if (eocd < 0) throw new Error(`${f.name} is not a ZIP file.`)
  const cdSize = u32(tail, eocd + 12)
  const cdOffset = u32(tail, eocd + 16)
  if (cdOffset === 0xffffffff) throw new Error(`${f.name} is a ZIP64 archive; upload customers.csv and orders.csv instead.`)
  const cd = await bytes(f, cdOffset, cdOffset + cdSize)
  const out: Entry[] = []
  const dec = new TextDecoder()
  for (let at = 0; at + 46 <= cd.byteLength && u32(cd, at) === 0x02014b50; ) {
    const nameLen = u16(cd, at + 28)
    const extraLen = u16(cd, at + 30)
    const commentLen = u16(cd, at + 32)
    const name = dec.decode(new Uint8Array(cd.buffer, cd.byteOffset + at + 46, nameLen))
    out.push({ name, method: u16(cd, at + 10), size: u32(cd, at + 20), offset: u32(cd, at + 42) })
    at += 46 + nameLen + extraLen + commentLen
  }
  return out
}

/** One entry's bytes as a stream (stored or deflated). */
async function open(f: File, e: Entry): Promise<ReadableStream<Uint8Array>> {
  const local = await bytes(f, e.offset, e.offset + 30)
  if (u32(local, 0) !== 0x04034b50) throw new Error(`${e.name}: damaged ZIP entry.`)
  const start = e.offset + 30 + u16(local, 26) + u16(local, 28)
  const raw = f.slice(start, start + e.size).stream()
  if (e.method === 0) return raw
  if (e.method === 8) return raw.pipeThrough(new DecompressionStream('deflate-raw'))
  throw new Error(`${e.name}: unsupported compression (method ${e.method}).`)
}

/** customers.csv or orders.csv at the ZIP's root (or in one folder), never the messy/ copy. */
function pick(all: Entry[], table: string): Entry | undefined {
  const ok = all.filter((e) => (e.name === `${table}.csv` || e.name.endsWith(`/${table}.csv`)) && !/(^|\/)messy\//.test(e.name))
  return ok.sort((a, b) => a.name.length - b.name.length)[0]
}

/** Data rows of a CSV stream (a newline inside quotes is not a row end). */
async function countRows(s: ReadableStream<Uint8Array>, onRows?: (n: number) => void): Promise<number> {
  let lines = 0
  let quoted = false
  let last = 10
  const reader = s.getReader()
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    for (let i = 0; i < value.length; i++) {
      const b = value[i]
      if (b === 34) quoted = !quoted
      else if (b === 10 && !quoted) lines++
    }
    if (value.length) last = value[value.length - 1]
    onRows?.(lines)
  }
  if (last !== 10) lines++ // no newline after the last row
  return Math.max(0, lines - 1) // the header
}

/** One CSV line into fields (DuckDB's COPY: comma, double quotes only where needed). */
function fields(line: string): string[] {
  const out: string[] = []
  let cur = ''
  let q = false
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]
    if (q) {
      if (ch === '"' && line[i + 1] === '"') {
        cur += '"'
        i++
      } else if (ch === '"') q = false
      else cur += ch
    } else if (ch === '"') q = true
    else if (ch === ',') {
      out.push(cur)
      cur = ''
    } else cur += ch
  }
  out.push(cur)
  return out
}

/** All (customer_id, email) of customers.csv (one row per customer: small, read whole). */
async function customers(s: ReadableStream<Uint8Array>): Promise<{ customer_id: number; email: string }[]> {
  const text = await new Response(s).text()
  const lines = text.split(/\r?\n/).filter(Boolean)
  const head = fields(lines[0] ?? '')
  const id = head.indexOf('customer_id')
  const email = head.indexOf('email')
  if (id < 0 || email < 0) throw new Error('customers.csv has no customer_id and email columns.')
  return lines.slice(1).map((l) => {
    const f = fields(l)
    return { customer_id: Number(f[id]), email: f[email] }
  })
}

export type Progress = (msg: string) => void

/** The fingerprint of a dropped ZIP, or of customers.csv + orders.csv dropped together. */
export async function fingerprint(files: File[], say: Progress = () => {}): Promise<MatchIn> {
  let cust: ReadableStream<Uint8Array> | undefined
  let ord: ReadableStream<Uint8Array> | undefined
  const zip = files.find((f) => /\.zip$/i.test(f.name))
  if (zip) {
    say(`Reading ${zip.name}…`)
    const all = await entries(zip)
    const c = pick(all, 'customers')
    const o = pick(all, 'orders')
    if (!c || !o) throw new Error(`${zip.name} has no customers.csv and orders.csv: is it the data ZIP of a run?`)
    cust = await open(zip, c)
    ord = await open(zip, o)
  } else {
    const c = files.find((f) => /(^|\/)customers\.csv$/i.test(f.name))
    const o = files.find((f) => /(^|\/)orders\.csv$/i.test(f.name))
    if (!c || !o) throw new Error('Drop the data ZIP of a run, or its customers.csv and orders.csv together.')
    cust = c.stream()
    ord = o.stream()
  }
  say('Reading customers…')
  const all = await customers(cust)
  if (!all.length) throw new Error('customers.csv has no rows.')
  const step = Math.max(1, Math.floor(all.length / SAMPLE))
  const sample = all.filter((_, i) => i % step === 0).slice(0, SAMPLE)
  const fmt = new Intl.NumberFormat('en-GB')
  let shown = 0
  const orders = await countRows(ord, (n) => {
    const now = performance.now()
    if (now - shown < 250) return // a chunk is ~64 kB: say it a few times a second, not per chunk
    shown = now
    say(`Counting orders… ${fmt.format(n)}`)
  })
  return { customers: all.length, orders, sample }
}
