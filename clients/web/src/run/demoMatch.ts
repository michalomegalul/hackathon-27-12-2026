// Which finished demo a typed prompt is. Kept free of imports so it can be tested on its own.

/** Lower case, no diacritics, one space between words: compares prompts however they were typed. */
export const fold = (s: string) => s.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '').replace(/\s+/g, ' ').trim()

/**
 * The demo whose whole story is in `text`, else null. The whole story, not its opening: a story that
 * starts "Data od ledna 2025 do konce října 2026." is how many prompts start, and matching only those
 * words sent every one of them to the coffee-shop replay instead of running it.
 */
export function demoOfPrompt<K extends string>(text: string, stories: Record<K, string>): K | null {
  const t = fold(text)
  for (const key of Object.keys(stories) as K[]) {
    const story = fold(stories[key])
    if (story && t.includes(story)) return key
  }
  return null
}
