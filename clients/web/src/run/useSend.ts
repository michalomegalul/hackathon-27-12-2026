// Sending a prompt: POST /v1/jobs, remember what was sent (so "Zkusit znovu" can resend it and a
// spec job can show its file name after a reload), then go to /run/:id.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { createJob, type JobInput, type NewJob } from '../api'
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
      void qc.invalidateQueries({ queryKey: ['jobs'] })
      void navigate(`${base}/${created.job_id}`)
    },
  })
}
