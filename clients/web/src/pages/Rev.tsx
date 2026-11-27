// Rev story "/rev": data → story. Prompt 3 of docs/prompts/06-web-v2.md adds the database picker
// and the detective-vs-original summary; for now the run view with every step waiting.
import { Link } from 'react-router'
import { RunView } from '../run/RunView'
import { Sections } from '../run/sections'
import { useRun } from '../run/useRun'

export function Rev() {
  const run = useRun(undefined)
  const idle = { ...run, status: { ...run.status, detail: 'Vyberte databázi nebo přiložte specifikaci.' } }
  return (
    <RunView
      run={idle}
      top={
        <div className="rounded-xl border border-line bg-panel p-4 sm:p-5">
          <h1 className="text-lg font-semibold">Rev story: z dat příběh</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Vyberete hotovou databázi a detektiv v ní naslepo hledá příběh. Shrnutí ho pak porovná s původním zadáním. Výběr databáze
            přibude v další verzi; zatím otevřete běh z{' '}
            <Link to="/history" className="text-slate-200 underline decoration-line underline-offset-2 hover:decoration-slate-400">
              History
            </Link>
            , detektiv v něm proběhne sám.
          </p>
        </div>
      }
    >
      <Sections run={idle} />
    </RunView>
  )
}
