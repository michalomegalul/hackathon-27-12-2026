// Found ↔ planted: which of the detective's events is which event of the story. A port of
// s2d/score.py (slots, pair_score, the optimal assignment, consequence_of) so the arrows Rev
// story draws are the pairs behind the P/R/F1 the API reports. The API sends only the score,
// not the pairs, so the page computes them again from /detect and /answer-key.
import type { Decoy, DetectEvent, PlantedEvent } from '../api'

const MATCH = 0.5
const TAU: Record<string, number> = { shift: 7, spike: 2, stockout: 2 }
const W_TIME = 0.4
const W_SEG = 0.4
const W_MAG = 0.2
const CONSEQUENCE_DAYS = 60
const ADVERSE_UP: Record<string, boolean> = {
  purchase_rate: false,
  acquisition_rate: false,
  rating_mean: false,
  churn_hazard: true,
  delivery_days: true,
  ticket_rate: true,
}

const DAY = 86_400_000
const day = (iso: string) => Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) / DAY

/** 'city=Brno;category=a,b' → {city=Brno, category=a, category=b} */
export function segPairs(seg: string | null | undefined): Set<string> {
  const out = new Set<string>()
  for (const part of (seg ?? '').split(';').filter(Boolean)) {
    const [k, v = ''] = part.split('=', 2)
    for (const x of v.split(',')) out.add(`${k}=${x}`)
  }
  return out
}

export type Slots = { gate: boolean; timing: number; deltaDays: number; segment: number; magnitude: number }

export function slots(p: DetectEvent, t: PlantedEvent): Slots {
  const tTrue = day(t.start_date) + (t.lag_days ?? 0)
  const delta = Math.round(day(p.start_date) - tTrue)
  const tau = TAU[p.kind] ?? 7
  const a = segPairs(p.segment)
  const b = segPairs(t.segment)
  const inter = [...a].filter((x) => b.has(x)).length
  const union = new Set([...a, ...b]).size
  const jac = union === 0 ? 1 : inter / union
  const pm = Math.abs(p.magnitude_pct ?? 0)
  const tm = Math.abs(t.magnitude_pct ?? 0)
  const mag = pm > 0 && tm > 0 ? Math.max(0, 1 - Math.abs(Math.log(pm / tm)) / Math.log(2)) : 0
  return {
    gate: p.metric === t.metric && p.direction === t.direction,
    timing: Math.max(0, 1 - Math.abs(delta) / tau),
    deltaDays: delta,
    segment: jac,
    magnitude: mag,
  }
}

/** score.py pair_score with TIME_GATE: metric, direction and timing > 0 must all hold. */
export const pairScore = (s: Slots) => (s.gate && s.timing > 0 ? W_TIME * s.timing + W_SEG * s.segment + W_MAG * s.magnitude : 0)

/**
 * The assignment that maximises the summed score, as scipy's linear_sum_assignment does:
 * a DP over which planted events are taken (up to 16 planted events, plenty for a story).
 * Returns col[i] = the planted index of found event i, or -1.
 */
function assign(s: number[][], nT: number): number[] {
  const nP = s.length
  if (nT > 16) {
    // a story never has this many events; greedy is good enough there
    const col = Array<number>(nP).fill(-1)
    const used = new Set<number>()
    const all = s.flatMap((row, i) => row.map((v, j) => ({ v, i, j }))).sort((x, y) => y.v - x.v)
    for (const { i, j } of all)
      if (col[i] < 0 && !used.has(j)) {
        col[i] = j
        used.add(j)
      }
    return col
  }
  const states = 1 << nT
  // best[i][mask]: best sum using found events i.. with planted `mask` already taken
  const best: Float64Array[] = Array.from({ length: nP + 1 }, () => new Float64Array(states))
  const pick: Int8Array[] = Array.from({ length: nP }, () => new Int8Array(states).fill(-1))
  for (let i = nP - 1; i >= 0; i--)
    for (let mask = 0; mask < states; mask++) {
      let b = best[i + 1][mask] // i takes nothing
      let pj = -1
      for (let j = 0; j < nT; j++)
        if (!(mask & (1 << j))) {
          const v = s[i][j] + best[i + 1][mask | (1 << j)]
          if (v > b + 1e-12) {
            b = v
            pj = j
          }
        }
      best[i][mask] = b
      pick[i][mask] = pj
    }
  const col = Array<number>(nP).fill(-1)
  let mask = 0
  for (let i = 0; i < nP; i++) {
    const j = pick[i][mask]
    col[i] = j
    if (j >= 0) mask |= 1 << j
  }
  return col
}

const bad = (metric: string, direction: string) => (direction === 'up') === (ADVERSE_UP[metric] ?? false)
const dims = (pairs: Set<string>) => new Set([...pairs].map((p) => p.split('=')[0]))

/** score.py consequence_of: an unmatched find that follows from matched planted event `t`. */
export function consequenceOf(e: DetectEvent, t: PlantedEvent): boolean {
  const start = day(t.start_date)
  const d = day(e.start_date)
  if (d < start || d > start + (t.lag_days ?? 0) + CONSEQUENCE_DAYS) return false
  const a = segPairs(e.segment)
  const b = segPairs(t.segment)
  const shared = [...a].some((x) => b.has(x))
  if ((a.size === 0 || b.size === 0 || shared) && bad(e.metric, e.direction) === bad(t.metric, t.direction)) return true
  const da = dims(a)
  return [...dims(b)].some((x) => da.has(x)) && !shared && e.metric === t.metric && e.direction !== t.direction
}

export type Pair = { found: DetectEvent; planted: PlantedEvent; score: number; slots: Slots }
export type Matching = {
  pairs: Pair[]
  /** planted events nobody found */
  missed: PlantedEvent[]
  /** finds that are no planted event; `decoy` names the decoy within 3 days, if any */
  falseFinds: { found: DetectEvent; decoy: string | null }[]
  /** finds that follow from a matched planted event (neither a hit nor a false alarm) */
  consequences: { found: DetectEvent; of: string }[]
  precision: number
  recall: number
  f1: number
}

export function matchEvents(found: DetectEvent[], plantedAll: PlantedEvent[], decoys: Decoy[] = []): Matching {
  const planted = plantedAll.filter((t) => t.simulated)
  const s = found.map((p) => planted.map((t) => pairScore(slots(p, t))))
  const col = found.length && planted.length ? assign(s, planted.length) : found.map(() => -1)
  const pairs: Pair[] = []
  found.forEach((p, i) => {
    const j = col[i]
    if (j >= 0 && s[i][j] >= MATCH) pairs.push({ found: p, planted: planted[j], score: s[i][j], slots: slots(p, planted[j]) })
  })
  const hitP = new Set(pairs.map((x) => x.found.id))
  const hitT = new Set(pairs.map((x) => x.planted.event_id))
  const falseFinds: Matching['falseFinds'] = []
  const consequences: Matching['consequences'] = []
  for (const e of found) {
    if (hitP.has(e.id)) continue
    const of = pairs.find((x) => consequenceOf(e, x.planted))?.planted.event_id
    if (of) {
      consequences.push({ found: e, of })
      continue
    }
    const near = decoys.find((dc) => Math.abs(day(dc.date) - day(e.start_date)) <= 3)
    falseFinds.push({ found: e, decoy: near ? near.type : null })
  }
  const tp = pairs.length
  const precision = found.length ? tp / found.length : 0
  const recall = planted.length ? tp / planted.length : 0
  const f1 = precision + recall ? (2 * precision * recall) / (precision + recall) : 0
  return { pairs, missed: planted.filter((t) => !hitT.has(t.event_id)), falseFinds, consequences, precision, recall, f1 }
}
