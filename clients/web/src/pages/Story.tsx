// Story "/" and "/run/:id". On "/" the prompt is typed into the Prompt section itself; sending
// runs everything automatically (useRun) and the URL becomes /run/:id, so a reload or a shared
// link reopens the run. "+ New story" starts a new one;
// the "Story" tab leads back to the last run (run/lastRun.ts).
import { Link, useLocation, useParams } from 'react-router'
import { Composer } from '../run/Composer'
import { RunView } from '../run/RunView'
import { Sections } from '../run/sections'
import { useRun } from '../run/useRun'
import { recallSent, useResend, useSend, type Draft } from '../run/useSend'
import { forgetLast, useRememberLast } from '../run/lastRun'

export function Story() {
  const { id } = useParams()
  const send = useSend()
  const run = useRun(id, useResend(id, send))
  // History "Edit" navigates here with the prompt (or spec) as a draft
  const location = useLocation()
  const draft = (location.state as { draft?: Draft } | null)?.draft
  useRememberLast('story', id)

  return (
    <RunView
      run={run}
      top={
        id ? (
          <div className="flex px-1">
            <Link to="/" onClick={() => forgetLast('story')} className="text-sm text-muted hover:text-white">
              + New story
            </Link>
          </div>
        ) : (
          <div className="px-1 pb-1">
            <h1 className="text-xl font-semibold tracking-tight">Story to data</h1>
            <p className="mt-1 max-w-2xl text-sm text-muted">
              Describe the company and what happened to it. An LLM turns the text into a spec, the simulator generates the database and a twin without the
              story, a statistical test verifies every event, and a blind detective tries to find it again. The whole pipeline runs by itself.
            </p>
          </div>
        )
      }
    >
      <Sections
        run={run}
        specName={recallSent(id)?.specName}
        composer={
          !id && (
            <Composer
              key={location.key}
              initial={draft}
              onSubmit={(s) => send.mutateAsync(s)}
              busy={send.isPending}
              error={send.error?.message}
            />
          )
        }
      />
    </RunView>
  )
}
