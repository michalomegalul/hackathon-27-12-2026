// Sending a prompt: POST /v1/jobs, remember what was sent (so "Zkusit znovu" can resend it and a
// spec job can show its file name after a reload), then go to /run/:id.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { createJob, getInput, getResult, inputOptions, type JobInput, type NewJob } from '../api'
import { rememberMine } from './jobs'
import type { Submit } from './prompt'

const key = (id: string) => `s2d_sent_${id}`

export function recallSent(id: string | undefined): Submit | null {
  if (!id) return null
  try {
    const s = sessionStorage.getItem(key(id))
    return s ? (JSON.parse(s) as Submit) : null
  } catch {
    return null
  }
}

/** The body to resend for a run: what this browser sent, else the story from GET /input. */
export function resendBody(id: string | undefined, input: JobInput | undefined): NewJob | null {
  const sent = recallSent(id)
  if (sent) return sent.body
  if (!input || input.spec_given || !input.company || !input.story) return null
  const opt = <K extends 'difficulty' | 'seed' | 'n_customers' | 'dirt'>(k: K) => (input[k] === null ? {} : { [k]: input[k] })
  return { company: input.company, story: input.story, ...opt('difficulty'), ...opt('seed'), ...opt('n_customers'), ...opt('dirt') }
}

export function useSend(base = '/run') {
  const navigate = useNavigate()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (s: Submit) => ({ created: await createJob(s.body), s }),
    onSuccess: ({ created, s }) => {
      try {
        sessionStorage.setItem(key(created.job_id), JSON.stringify(s))
      } catch {
        /* private mode: retry falls back to GET /input */
      }
      rememberMine(created.job_id)
      void qc.invalidateQueries({ queryKey: ['jobs'] })
      void navigate(`${base}/${created.job_id}`)
    },
  })
}

/** "Zkusit znovu" for a failed job: send the same prompt again as a new run (undefined if unknown). */
export function useResend(id: string | undefined, send: ReturnType<typeof useSend>) {
  const input = useQuery({ ...inputOptions(id ?? ''), enabled: Boolean(id) })
  const body = resendBody(id, input.data)
  return body ? () => send.mutate({ body, specName: recallSent(id)?.specName }) : undefined
}

/** A fresh seed for "Znovu": same prompt, different data. */
const newSeed = () => Math.floor(Math.random() * 1_000_000_000)

/**
 * "Znovu": the same input as a new run with a new seed. The prompt from this browser or GET /input;
 * a spec job's spec from /result (it is not repeated in /input).
 */
export async function rerunBody(id: string): Promise<Submit> {
  const sent = recallSent(id)
  const input = sent ? null : await getInput(id)
  const body = resendBody(id, input ?? undefined)
  if (body) return { body: { ...body, seed: newSeed() }, specName: sent?.specName }
  if (input?.spec_given) {
    const r = await getResult(id)
    const opt = input.n_customers === null ? {} : { n_customers: input.n_customers }
    return { body: { spec_yaml: r.spec_yaml, ...opt, seed: newSeed() }, specName: `${id}.yaml` }
  }
  throw new Error('Zadání tohoto běhu není k dispozici.')
}

/** What "Upravit" puts into the Story input: the prompt as text, or a spec as the attached file. */
export type Draft = { text: string } | { spec: { name: string; yaml: string } }

export async function draftOf(id: string): Promise<Draft> {
  const sent = recallSent(id)
  if (sent && 'spec_yaml' in sent.body) return { spec: { name: sent.specName ?? `${id}.yaml`, yaml: sent.body.spec_yaml } }
  if (sent && 'company' in sent.body) return { text: joinPrompt(sent.body.company, sent.body.story) }
  const input = await getInput(id)
  if (input.spec_given) return { spec: { name: `${id}.yaml`, yaml: (await getResult(id)).spec_yaml } }
  return { text: joinPrompt(input.company ?? '', input.story ?? '') }
}

/** The inverse of splitPrompt: company, a blank line, the story (once if they are the same). */
const joinPrompt = (company: string, story: string) => (story && story !== company ? `${company}\n\n${story}` : company)
