// The Story chat input: one textarea (Enter sends, Shift+Enter is a new line), chips for the
// example and the no-AI test, and a paperclip that attaches a .yaml spec.
import { useRef, useState } from 'react'
import { splitPrompt, type Submit } from './prompt'
import type { Draft } from './useSend'
import { BRIEF_EXAMPLE, FAST_TEST_SPEC } from '../examples'
import { Spinner } from '../components/ui'


const chip = 'rounded-full border border-line px-3 py-1 text-xs text-slate-300 hover:border-slate-500 hover:text-white disabled:opacity-50'

/**
 * `onSubmit` resolves once the run exists: then the input clears, as in a chat. `initial` is what
 * History's "Upravit" puts in (the page keys this component by navigation, so a new draft resets it).
 */
export function Composer({
  onSubmit,
  busy,
  error,
  initial,
}: {
  onSubmit: (s: Submit) => Promise<unknown>
  busy: boolean
  error?: string | null
  initial?: Draft
}) {
  const [text, setText] = useState(initial && 'text' in initial ? initial.text : '')
  const [spec, setSpec] = useState<{ name: string; yaml: string } | null>(initial && 'spec' in initial ? initial.spec : null)
  const [fileErr, setFileErr] = useState<string | null>(null)
  const file = useRef<HTMLInputElement>(null)
  const area = useRef<HTMLTextAreaElement>(null)

  const canSend = !busy && (Boolean(spec) || text.trim().length > 0)
  const send = () => {
    if (!canSend) return
    const s: Submit = spec ? { body: { spec_yaml: spec.yaml }, specName: spec.name } : { body: splitPrompt(text) }
    onSubmit(s).then(
      () => {
        setText('')
        setSpec(null)
      },
      () => {}, // the error shows under the input; keep the text
    )
  }

  return (
    <div data-chrome="bottom" className="sticky bottom-0 z-10 -mx-3 bg-bg/95 px-3 pb-3 pt-2 backdrop-blur sm:mx-0 sm:px-0">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          className={chip}
          onClick={() => {
            setText(`${BRIEF_EXAMPLE.company}\n\n${BRIEF_EXAMPLE.story}`)
            setSpec(null)
            area.current?.focus()
          }}
        >
          Ukázka
        </button>
        <button
          type="button"
          className={chip}
          disabled={busy}
          title="Pošle hotovou specifikaci examples/a.yaml, krok AI se přeskočí"
          onClick={() => void onSubmit({ body: { spec_yaml: FAST_TEST_SPEC }, specName: 'examples/a.yaml' }).catch(() => {})}
        >
          Rychlý test bez AI
        </button>
        {spec && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/[0.06] py-1 pl-3 pr-1.5 text-xs">
            <span className="font-mono">{spec.name}</span>
            <button type="button" aria-label="Odebrat soubor" className="rounded-full px-1 text-muted hover:text-white" onClick={() => setSpec(null)}>
              ×
            </button>
          </span>
        )}
      </div>
      <form
        className="flex items-end gap-2 rounded-2xl border border-line bg-panel p-1.5 sm:p-2 focus-within:border-slate-500"
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
      >
        <button
          type="button"
          onClick={() => file.current?.click()}
          className="grid size-9 shrink-0 place-items-center rounded-xl text-muted hover:bg-white/[0.06] hover:text-white"
          title="Přiložit specifikaci (.yaml)"
          aria-label="Přiložit specifikaci (.yaml)"
        >
          <svg viewBox="0 0 24 24" className="size-[18px]" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 11.5 12.6 19.9a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8" />
          </svg>
        </button>
        <input
          ref={file}
          type="file"
          accept=".yaml,.yml,application/yaml,text/yaml"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            e.target.value = ''
            if (!f) return
            setFileErr(null)
            if (!/\.ya?ml$/i.test(f.name)) return setFileErr('Přiložte soubor .yaml se specifikací.')
            void f.text().then((yaml) => setSpec({ name: f.name, yaml }))
          }}
        />
        <textarea
          ref={area}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              send()
            }
          }}
          autoFocus={Boolean(initial)}
          rows={Math.min(8, Math.max(1, text.split('\n').length))}
          placeholder={spec ? 'Pošle se přiložená specifikace (text se nepoužije).' : 'První odstavec: firma. Pak příběh.'}
          aria-label="Firma a příběh"
          className="max-h-60 min-h-9 flex-1 resize-none bg-transparent px-1 py-2 text-[16px] leading-relaxed placeholder:text-slate-500 focus:outline-none sm:text-sm"
        />
        <button
          type="submit"
          disabled={!canSend}
          className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent text-slate-950 hover:brightness-110 disabled:bg-white/10 disabled:text-slate-500"
          aria-label="Odeslat"
          title="Odeslat (Enter)"
        >
          {busy ? (
            <Spinner />
          ) : (
            <svg viewBox="0 0 24 24" className="size-[18px]" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          )}
        </button>
      </form>
      {(error || fileErr) && <p className="mt-1.5 text-xs text-rose-300">{fileErr ?? error}</p>}
      <p className="mt-1.5 hidden text-[11px] text-slate-500 sm:block">Enter odešle, Shift+Enter nový řádek. Běh trvá 1–2 minuty.</p>
    </div>
  )
}
