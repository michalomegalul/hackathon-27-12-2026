import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router'
import { ApiError, createJob, jobsOptions, type Difficulty, type Dirt, type NewJob } from '../api'
import { BRIEF_EXAMPLE, FAST_TEST_SPEC } from '../examples'
import { Alert, Card, JobStatusBadge, Spinner } from '../components/ui'

const input =
  'w-full rounded-lg border border-line bg-bg px-3 py-2 text-[16px] sm:text-sm placeholder:text-slate-500 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent'

function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <label className="grid gap-1.5">
      <span className="text-sm font-medium text-slate-200">{label}</span>
      {children}
      {error ? <span className="text-xs text-rose-300">{error}</span> : hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  )
}

type Form = { company: string; story: string; difficulty: '' | Difficulty; n_customers: string; dirt: '' | Dirt; seed: string }
const EMPTY: Form = { company: '', story: '', difficulty: '', n_customers: '', dirt: '', seed: '' }

/** Options only when filled in, so the spec's own values stay the default. */
function options(f: Form) {
  return {
    ...(f.difficulty ? { difficulty: f.difficulty } : {}),
    ...(f.dirt ? { dirt: f.dirt } : {}),
    ...(f.n_customers.trim() ? { n_customers: Number(f.n_customers) } : {}),
    ...(f.seed.trim() ? { seed: Number(f.seed) } : {}),
  }
}

/** 422 detail → errors per field name (loc ["body", "n_customers"]). */
function fieldErrors(err: unknown): Partial<Record<keyof Form, string>> {
  if (!(err instanceof ApiError) || typeof err.detail === 'string') return {}
  const out: Partial<Record<keyof Form, string>> = {}
  for (const d of err.detail) {
    const f = d.loc[1]
    if (typeof f === 'string' && f in EMPTY) out[f as keyof Form] = d.msg
  }
  return out
}

function RecentDone() {
  const { data } = useQuery(jobsOptions())
  const done = data?.jobs.filter((j) => j.status === 'done').slice(0, 4) ?? []
  if (!done.length) return null
  return (
    <Card>
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="font-semibold">Hotové úlohy</h2>
        <Link to="/jobs" className="text-sm text-accent hover:underline">
          všechny →
        </Link>
      </div>
      <p className="mb-3 text-xs text-muted">Stejný příběh nemusíte generovat znovu: GPU je jedno a fronta společná.</p>
      <ul className="grid gap-2">
        {done.map((j) => (
          <li key={j.job_id}>
            <Link
              to={`/jobs/${j.job_id}`}
              className="flex items-center gap-3 rounded-lg border border-line px-3 py-2 hover:border-accent/60"
            >
              <span className="min-w-0 flex-1 truncate text-sm">{j.title || j.job_id}</span>
              {j.summary && (
                <span className="text-xs text-muted">
                  příběh {j.summary.story} · dvojče {j.summary.twin}
                </span>
              )}
              <JobStatusBadge s={j.status} />
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export function Home() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [f, setF] = useState<Form>(EMPTY)
  const set = <K extends keyof Form>(k: K) => (e: { target: { value: string } }) => setF((p) => ({ ...p, [k]: e.target.value as Form[K] }))

  const create = useMutation({
    mutationFn: (body: NewJob) => createJob(body),
    onSuccess: ({ job_id }) => {
      void qc.invalidateQueries({ queryKey: ['jobs'] })
      void navigate(`/jobs/${job_id}`)
    },
  })
  const errs = fieldErrors(create.error)
  const generalError = create.error && Object.keys(errs).length === 0 ? create.error.message : null

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <Card>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Z příběhu data</h1>
        <p className="mt-1 text-sm text-muted">
          Popište firmu a co se jí stalo. AI z toho udělá specifikaci, simulátor vyrobí dva roky dat a statistika ověří,
          že v datech je přesně váš příběh.
        </p>

        <form
          className="mt-5 grid gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            create.mutate({ company: f.company, story: f.story, ...options(f) })
          }}
        >
          <Field label="Firma" error={errs.company}>
            <textarea
              required
              rows={4}
              value={f.company}
              onChange={set('company')}
              className={input}
              placeholder="Pražírna Zrnko s.r.o.: výběrová káva, e-shop s předplatným a čtyři kavárny v Praze, Brně, Ostravě a Plzni. Zákazníci jsou studenti, předplatitelé a firmy…"
            />
          </Field>
          <Field label="Příběh" error={errs.story}>
            <textarea
              required
              rows={5}
              value={f.story}
              onChange={set('story')}
              className={input}
              placeholder="Data od ledna 2025 na dva roky. V březnu 2026 jsme zdražili o 15 % a studenti začali odcházet. V Brně se od června zpožďovaly zásilky…"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Field label="Obtížnost" error={errs.difficulty}>
              <select value={f.difficulty} onChange={set('difficulty')} className={input}>
                <option value="">dle specifikace</option>
                <option value="easy">snadná</option>
                <option value="medium">střední</option>
                <option value="hard">těžká</option>
              </select>
            </Field>
            <Field label="Zákazníků" error={errs.n_customers}>
              <input
                type="number"
                inputMode="numeric"
                min={500}
                max={100000}
                step={500}
                value={f.n_customers}
                onChange={set('n_customers')}
                className={input}
                placeholder="20 000"
              />
            </Field>
            <Field label="Nepořádek" error={errs.dirt}>
              <select value={f.dirt} onChange={set('dirt')} className={input}>
                <option value="">dle specifikace</option>
                <option value="none">žádný</option>
                <option value="low">malý</option>
                <option value="medium">střední</option>
                <option value="high">velký</option>
              </select>
            </Field>
            <Field label="Seed" error={errs.seed}>
              <input type="number" inputMode="numeric" value={f.seed} onChange={set('seed')} className={input} placeholder="42" />
            </Field>
          </div>

          {generalError && <Alert>{generalError}</Alert>}

          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            <button
              type="submit"
              disabled={create.isPending}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 font-medium text-slate-950 hover:brightness-110 disabled:opacity-60"
            >
              {create.isPending && <Spinner />}
              Vygenerovat data
            </button>
            <button
              type="button"
              onClick={() => setF((p) => ({ ...p, ...BRIEF_EXAMPLE }))}
              className="rounded-lg border border-line px-4 py-2.5 text-sm hover:border-slate-400"
            >
              Načíst příklad
            </button>
            <button
              type="button"
              disabled={create.isPending}
              onClick={() => create.mutate({ spec_yaml: FAST_TEST_SPEC, ...options(f) })}
              className="rounded-lg border border-line px-4 py-2.5 text-sm hover:border-slate-400 disabled:opacity-60"
              title="Pošle hotovou specifikaci examples/a.yaml, krok AI se přeskočí"
            >
              Rychlý test (bez AI)
            </button>
          </div>
          <p className="text-xs text-muted">Běh trvá 1–2 minuty. Prázdná pole berou hodnotu ze specifikace.</p>
        </form>
      </Card>

      <aside className="grid content-start gap-5">
        <RecentDone />
        <Card>
          <h2 className="mb-2 font-semibold">Co dostanete</h2>
          <ul className="grid gap-1.5 text-sm text-muted">
            <li>• tabulky zákazníků, objednávek, recenzí… (CSV + DuckDB)</li>
            <li>• ověření každé události z příběhu, s SQL dotazem</li>
            <li>• „dvojče“ bez příběhu jako kontrolu, že nález není náhoda</li>
            <li>• český souhrn toho, co v datech je</li>
          </ul>
        </Card>
      </aside>
    </div>
  )
}
