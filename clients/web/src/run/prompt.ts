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

// Words that turn up in any real company story, Czech or English. Keyboard mashing has none.
const COMMON = new Set(
  'a i v ve na se je jsou od do z ze že s o u k pro po při za to ta ten byl byla bylo firma firmy společnost zákazníci zákazníků tržby prodej the and of in on is are was were from to for with by company customers sales since after'.split(' '),
)

/** A cheap guard before a prompt is sent: null when it reads like text, else what to tell the user. */
export function promptProblem(text: string): string | null {
  const words = (text.toLowerCase().match(/\p{L}+/gu) ?? []).filter((w) => w.length > 0)
  if (words.length < 5) return 'Invalid prompt: describe the company and what happened to it in a few sentences.'
  const real = words.filter((w) => w.length >= 3)
  const withVowel = real.filter((w) => /[aeiouyáéěíóúůý]/.test(w)).length
  const common = words.filter((w) => COMMON.has(w)).length
  if (real.length === 0 || withVowel / real.length < 0.6 || common < 1 || new Set(words).size < 4)
    return 'Invalid prompt: this does not read like a company story. Say what the company does and what changed, and when.'
  return null
}
