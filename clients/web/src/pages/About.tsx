// About "/about": the technical part. Prompt 3 of docs/prompts/06-web-v2.md fills it in.
import { Card } from '../components/ui'

const STEPS: [string, string][] = [
  ['Prompt', 'firma a příběh česky, jedna zpráva'],
  ['Spec', 'Gemma 4 26b z příběhu napíše specifikaci (StorySpec)'],
  ['Data', 'numpy simulace a dvojče se stejným seedem bez příběhu, DuckDB'],
  ['Detektiv', 'hledá události v datech bez znalosti příběhu'],
  ['Skóre', 'rozdíl v rozdílech proti kontrole, placebo test, dvojče jako falešné poplachy'],
  ['Shrnutí', 'věty z promptu napojené na grafy a sloupce, kde se změnily'],
]

export function About() {
  return (
    <div className="mx-auto grid max-w-3xl gap-4">
      <h1 className="text-xl font-semibold tracking-tight">About</h1>
      <Card>
        <h2 className="mb-3 font-semibold">Pipeline</h2>
        <ol className="grid gap-2 text-sm">
          {STEPS.map(([k, v], i) => (
            <li key={k} className="flex gap-3">
              <span className="w-4 shrink-0 text-right font-mono text-xs leading-5 text-slate-500">{i + 1}</span>
              <span className="w-20 shrink-0 font-medium">{k}</span>
              <span className="text-muted">{v}</span>
            </li>
          ))}
        </ol>
      </Card>
      <Card>
        <h2 className="mb-2 font-semibold">API</h2>
        <p className="text-sm text-muted">
          Všechno, co stránka dělá, umí i HTTP API:{' '}
          <a href="/docs" className="text-slate-200 underline decoration-line underline-offset-2 hover:decoration-slate-400">
            /docs
          </a>{' '}
          (Swagger),{' '}
          <a
            href="https://github.com/michalomegalul/hackathon-27-12-2026"
            className="text-slate-200 underline decoration-line underline-offset-2 hover:decoration-slate-400"
          >
            repozitář
          </a>
          .
        </p>
      </Card>
    </div>
  )
}
