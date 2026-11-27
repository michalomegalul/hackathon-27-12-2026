// Story "/" and "/run/:id". On "/" the prompt is typed into the Prompt section itself; sending
// runs everything automatically (useRun) and the URL becomes /run/:id, so a reload or a shared
// link reopens the run. A new run starts from "Story" in the header.
import { useLocation, useParams } from 'react-router'
import { Composer } from '../run/Composer'
import { RunView } from '../run/RunView'
import { Sections } from '../run/sections'
import { useRun } from '../run/useRun'
import { recallSent, useResend, useSend, type Draft } from '../run/useSend'

export function Story() {
  const { id } = useParams()
  const send = useSend()
  const run = useRun(id, useResend(id, send))
  // History "Upravit" navigates here with the prompt (or spec) as a draft
  const location = useLocation()
  const draft = (location.state as { draft?: Draft } | null)?.draft

  return (
    <RunView
      run={run}
      top={
        !id && (
          <div className="px-1 pb-1">
            <h1 className="text-xl font-semibold tracking-tight">Z příběhu data</h1>
            <p className="mt-1 max-w-2xl text-sm text-muted">
              Napište, co je to za firmu a co se jí stalo. AI z toho udělá specifikaci, simulátor vyrobí data i dvojče bez příběhu,
              statistika ověří každou událost a detektiv ji zkusí najít naslepo. Všechno proběhne samo.
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
