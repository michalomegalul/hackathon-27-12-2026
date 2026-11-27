// Demo "/demo": the three scenarios of the pitch. 1 small (the official brief), 2 big (six
// linked events, and what the model is not good at), 3 the model's limits (a story half
// outside what the engine can represent). Each card opens its pre-generated run, or puts the
// same input into Story to run it again.
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { BRIEF_EXAMPLE, FAST_TEST_SPEC, NAHAPRAVDA_EXAMPLE } from '../examples'
import type { Draft } from '../run/useSend'

// Pre-generated runs on hack.dobsinsky.dev (fill in after generating; '' hides the button).
const RUN_IDS = { brief: '', coffee: '', nahapravda: '' }

type Fit = 'yes' | 'partly' | 'no'
const FIT_MARK: Record<Fit, string> = { yes: '✅', partly: '⚠️', no: '❌' }

type Scenario = {
  n: string
  size: string
  title: string
  lead: string
  points: ReactNode[]
  fit?: [story: string, engine: string, fit: Fit][]
  run: string
  draft: Draft
}

const SCENARIOS: Scenario[] = [
  {
    n: '1',
    size: 'small',
    title: 'SportMax: the official brief',
    lead: 'One event for everyone: from April 2026 sales drop by 5 % and stay down. The hackathon’s own example, run as written.',
    points: [
      'The size is stated by the story, so it is never inflated: −5 % stays −5 %.',
      'An event for everyone has no group to compare with, so the test compares with the same weeks a year earlier.',
      'A −5 % change is close to the noise: it needs about 160 000 customers to confirm reliably.',
    ],
    run: RUN_IDS.brief,
    draft: { text: `${BRIEF_EXAMPLE.company}\n\n${BRIEF_EXAMPLE.story}` },
  },
  {
    n: '2',
    size: 'big',
    title: 'Pražírna Zrnko: six linked events',
    lead: 'A coffee roaster with an e-shop and four cafés: a price rise, students leaving six weeks later, a supplier delay, complaints, subscribers leaving in Brno, a competitor in Brno.',
    points: [
      'Each event is tested on its own and on a twin without the story; the twin must show nothing.',
      <>
        <b>Where the model is weak.</b> On one random seed an event can land under the noise: this story came out 3/6 until calibration measured on
        three seeds and took the weakest.
      </>,
      'A size the story states (−20 % in Brno) cannot be made stronger, so the run adds customers instead (40 000 → 80 000) and says so.',
      'Churn is only visible through orders, so calibrated churn sizes end far above the story’s +60 % / +80 %.',
      'At most 3 years of data and a fixed list of event types and metrics.',
    ],
    run: RUN_IDS.coffee,
    draft: { spec: { name: 'examples/a.yaml', yaml: FAST_TEST_SPEC } },
  },
  {
    n: '3',
    size: 'limits',
    title: 'Nahá pravda: a story half outside the model',
    lead: 'A subscription video site since 2002: AI content and chatbots cut traffic by 20 %, a section for users’ own generated videos brings part of them back, and the database grows by 100 GB a day.',
    points: ['What the compiler keeps, what it approximates and what it has to drop:'],
    fit: [
      ['subscription site, subscribers', 'industry subscription', 'yes'],
      ['traffic −20 % (stated)', 'a −20 % drop in new and active customers, never inflated', 'yes'],
      ['own-video section, users return', 'a campaign / lower churn', 'yes'],
      ['since 2002, stable until 2021', 'at most 3 years of data: only the starting level', 'partly'],
      ['monthly traffic', 'no visits table: orders and subscriptions stand in', 'partly'],
      ['+100 GB a day in the database', 'no infrastructure metrics: dropped and listed as unsupported', 'no'],
    ],
    run: RUN_IDS.nahapravda,
    draft: { text: `${NAHAPRAVDA_EXAMPLE.company}\n\n${NAHAPRAVDA_EXAMPLE.story}` },
  },
]

const btn = 'border border-line px-3 py-1.5 text-sm text-slate-300 hover:border-slate-500 hover:text-white'

export function Demo() {
  return (
    <div className="max-w-4xl">
      <h1 className="text-xl font-semibold tracking-tight">Demo: three stories</h1>
      <p className="mt-1 text-sm text-muted">From the smallest story to one the model cannot fully represent. Each opens a finished run, or runs again.</p>
      <div className="mt-6 space-y-8">
        {SCENARIOS.map((s) => (
          <section key={s.n} className="border-t border-line pt-5">
            <div className="flex flex-wrap items-baseline gap-3">
              <span className="font-mono text-2xl text-accent">{s.n}</span>
              <h2 className="text-lg font-semibold">{s.title}</h2>
              <span className="border border-line px-2 py-0.5 text-xs uppercase tracking-wide text-muted">{s.size}</span>
            </div>
            <p className="mt-2 text-sm text-slate-300">{s.lead}</p>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted">
              {s.points.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
            {s.fit && (
              <table className="mt-3 w-full text-left text-sm">
                <thead className="text-xs uppercase tracking-wide text-muted">
                  <tr>
                    <th className="py-1 pr-3 font-normal">In the story</th>
                    <th className="py-1 pr-3 font-normal">In the engine</th>
                    <th className="py-1 font-normal" aria-label="fit" />
                  </tr>
                </thead>
                <tbody>
                  {s.fit.map(([story, engine, fit]) => (
                    <tr key={story} className="border-t border-line/60">
                      <td className="py-1.5 pr-3 text-slate-300">{story}</td>
                      <td className="py-1.5 pr-3 text-muted">{engine}</td>
                      <td className="py-1.5" title={fit}>
                        {FIT_MARK[fit]}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="mt-4 flex flex-wrap gap-2">
              {s.run && (
                <Link to={`/run/${s.run}`} className={`${btn} border-accent text-white`}>
                  Open the run
                </Link>
              )}
              <Link to="/" state={{ draft: s.draft }} className={btn}>
                Run it yourself
              </Link>
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
