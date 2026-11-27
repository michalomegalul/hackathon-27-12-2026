import type { NewJob } from '../api'

/**
 * The API wants company and story apart: the first paragraph is the company, the rest the story.
 * Paragraphs are split on a blank line; without one, on the first line break. A single paragraph
 * is sent as both.
 */
export function splitPrompt(text: string): { company: string; story: string } {
  const t = text.trim()
  let parts = t.split(/\n\s*\n/)
  if (parts.length < 2) parts = t.split('\n')
  const company = parts[0].trim()
  const story = parts.slice(1).join('\n\n').trim()
  return { company, story: story || company }
}

export type Submit = { body: NewJob; specName?: string }
