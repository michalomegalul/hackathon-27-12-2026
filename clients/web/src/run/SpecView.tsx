// Spec: what the AI understood, as readable Czech parameters (company, segments, cities,
// channels) and the events as a table. The YAML itself only behind "pro vývojáře".
import { useState, type ReactNode } from 'react'
import type { JobResult } from '../api'
import { CopyButton } from '../components/Code'
import { METRIC_CS, dateCs, intCs, signed } from '../format'
import { CHANNEL_CS, EVENT_TYPE_CS, SPEC_METRIC_CS, eventEnd, lagCs, targetCs, type Effect, type Spec, type SpecEvent } from '../spec'

const pct = (x: number) => `${Math.round(x * 100)} %`

function Shares({ title, items }: { title: string; items: { label: string; share: number; note?: string }[] }) {
  if (!items.length) return null
  return (
    <div className="rounded-lg border border-line bg-bg/40 p-3">
      <h3 className="mb-2 text-xs text-muted">{title}</h3>
      <ul className="grid gap-1.5">
        {items.map((it) => (
          <li key={it.label} className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-2 text-sm">
            <span className="truncate">
              {it.label}
              {it.note && <span className="ml-1.5 text-xs text-muted">{it.note}</span>}
            </span>
            <span className="tabular-nums text-slate-300">{pct(it.share)}</span>
            <span className="col-span-2 h-1 overflow-hidden rounded-full bg-white/[0.06]">
              <span className="block h-full rounded-full bg-slate-400/60" style={{ width: `${Math.min(100, it.share * 100)}%` }} />
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Company({ s }: { s: Spec }) {
  const c = s.company
  const n = s.customers
  return (
    <div className="grid gap-3">
      <div className="grid gap-1">
        <p className="font-medium">
          {c.name} {c.legal_form && <span className="text-slate-400">{c.legal_form}</span>}
        </p>
        {c.description && <p className="text-sm text-slate-300">{c.description}</p>}
        <p className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted">
          {Number.isFinite(n.n) && <span>{intCs(n.n)} zákazníků</span>}
          {n.growth_per_year ? <span>růst {signed(n.growth_per_year * 100)} % ročně</span> : null}
          {s.meta.start && Number.isFinite(s.meta.days) && (
            <span>
              data od {dateCs(s.meta.start)}, {intCs(s.meta.days)} dní
            </span>
          )}
          {s.categories.length > 0 && <span>kategorie: {s.categories.map((x) => x.id).join(', ')}</span>}
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Shares
          title="Segmenty zákazníků"
          items={n.segments.map((x) => ({ label: x.id, share: x.share, note: x.subscription ? 'předplatné' : undefined }))}
        />
        <Shares
          title="Města"
          items={c.cities.map((x) => ({ label: x.name, share: x.weight, note: x.has_store ? 'prodejna' : undefined }))}
        />
        <Shares title="Kanály" items={c.channels.map((x) => ({ label: CHANNEL_CS[x.channel] ?? x.channel, share: x.weight }))} />
      </div>
    </div>
  )
}

const metricCs = (m: string) => METRIC_CS[m] ?? SPEC_METRIC_CS[m] ?? m

function Size({ f }: { f: Effect }) {
  // delivery_days is in days (s2d/sim/service.py courier_delay); every other size is relative
  const v = f.metric === 'delivery_days' ? `${signed(f.size)} ${Math.abs(f.size) === 1 ? 'den' : Math.abs(f.size) < 5 ? 'dny' : 'dní'}` : `${signed(f.size * 100)} %`
  return (
    <span className="whitespace-nowrap">
      {metricCs(f.metric)}{' '}
      {f.size_stated ? (
        <b className="font-medium tabular-nums text-slate-100">{v}</b>
      ) : (
        <span className="text-muted" title="příběh velikost neuvádí, simulace použila odhad">
          neuvedeno <span className="tabular-nums">(sim. {v})</span>
        </span>
      )}
    </span>
  )
}

function When({ e }: { e: SpecEvent }) {
  const end = eventEnd(e)
  return (
    <span className="whitespace-nowrap tabular-nums">
      {dateCs(e.start)} – {end ? dateCs(end) : <span className="text-muted">trvale</span>}
    </span>
  )
}

const lags = (e: SpecEvent) => [...new Set(e.effects.map((f) => lagCs(f.lag_days)))].join(', ') || 'hned'

function Events({ s }: { s: Spec }) {
  if (!s.events.length) return <p className="text-sm text-muted">Příběh neobsahuje žádné události.</p>
  return (
    <>
      <ul className="grid gap-2 md:hidden">
        {s.events.map((e) => (
          <li key={e.id} className="grid gap-1.5 rounded-lg border border-line bg-bg/40 p-3 text-sm">
            <div className="flex gap-2">
              <span className="font-mono text-xs text-muted">{e.id}</span>
              <span className="flex-1">{e.narrative_cs || EVENT_TYPE_CS[e.type] || e.type}</span>
            </div>
            <div className="grid gap-0.5 text-xs text-muted">
              <When e={e} />
              <span>{targetCs(e.target, s)}</span>
              {e.effects.map((f, i) => (
                <Size key={i} f={f} />
              ))}
              <span>zpoždění: {lags(e)}</span>
            </div>
          </li>
        ))}
      </ul>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="py-2 pr-3 font-medium">Co</th>
              <th className="py-2 pr-3 font-medium">Od – do</th>
              <th className="py-2 pr-3 font-medium">Koho</th>
              <th className="py-2 pr-3 font-medium">Velikost v příběhu</th>
              <th className="py-2 font-medium">Zpoždění</th>
            </tr>
          </thead>
          <tbody>
            {s.events.map((e) => (
              <tr key={e.id} className="border-b border-line/50 align-top last:border-0">
                <td className="py-2 pr-3">
                  <div className="flex gap-2">
                    <span className="font-mono text-xs leading-5 text-muted">{e.id}</span>
                    <span>
                      {e.narrative_cs || EVENT_TYPE_CS[e.type] || e.type}
                      <span className="mt-0.5 block text-xs text-muted">
                        {EVENT_TYPE_CS[e.type] ?? e.type}
                        {e.caused_by && <> · následek {e.caused_by}</>}
                      </span>
                    </span>
                  </div>
                </td>
                <td className="py-2 pr-3">
                  <When e={e} />
                </td>
                <td className="py-2 pr-3 text-slate-300">{targetCs(e.target, s)}</td>
                <td className="grid gap-0.5 py-2 pr-3">
                  {e.effects.map((f, i) => (
                    <Size key={i} f={f} />
                  ))}
                </td>
                <td className="py-2 whitespace-nowrap text-slate-300">{lags(e)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function DevYaml({ yaml }: { yaml: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="grid justify-items-start gap-2">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="text-xs text-slate-500 hover:text-slate-300">
        {open ? '▾' : '▸'} pro vývojáře
      </button>
      {open && (
        <div className="grid w-full gap-1.5">
          <div className="flex items-center gap-2 text-xs text-muted">
            <span className="font-mono">spec.yaml</span>
            <CopyButton text={yaml} />
          </div>
          <pre className="max-h-96 w-full overflow-auto rounded-lg border border-line bg-bg/70 px-3 py-2 font-mono text-[11.5px] leading-relaxed text-slate-300">
            {yaml}
          </pre>
        </div>
      )}
    </div>
  )
}

/** `spec` null (the YAML could not be read): `fallback` instead of the parameters. */
export function SpecView({ r, spec, fallback }: { r: JobResult; spec: Spec | null; fallback: ReactNode }) {
  return (
    <div className="grid gap-5">
      {spec ? (
        <>
          <Company s={spec} />
          <div className="grid gap-2">
            <h3 className="text-xs text-muted">Události příběhu</h3>
            <Events s={spec} />
          </div>
        </>
      ) : (
        fallback
      )}
      <DevYaml yaml={r.spec_yaml} />
    </div>
  )
}
