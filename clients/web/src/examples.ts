// Example inputs from the repo's examples/ folder, bundled as text with Vite's ?raw.
import briefYaml from '../../../examples/stories/brief.yaml?raw'
import specA from '../../../examples/a.yaml?raw'
import zrnkoYaml from '../../../examples/stories/zrnko.yaml?raw'
import nahapravdaYaml from '../../../examples/stories/nahapravda.yaml?raw'

/** The hand-written spec for the fast test (no AI): POST {spec_yaml}. */
export const FAST_TEST_SPEC = specA

/**
 * Reads a top-level `key: >` (folded) or `key: |` (literal) block, or a plain one-line
 * `key: value`, from a small YAML file. Enough for examples/stories/*.yaml; not a YAML parser.
 */
function topLevelText(yaml: string, key: string): string {
  const lines = yaml.split('\n')
  const i = lines.findIndex((l) => l.startsWith(`${key}:`))
  if (i < 0) return ''
  const head = lines[i].slice(key.length + 1).trim()
  if (!/^[>|][-+]?$/.test(head)) return head.replace(/^["']|["']$/g, '')
  const body: string[] = []
  for (const l of lines.slice(i + 1)) {
    if (l.trim() !== '' && !/^\s/.test(l)) break // next top-level key
    body.push(l.trim())
  }
  while (body.length && body[body.length - 1] === '') body.pop()
  if (head.startsWith('|')) return body.join('\n')
  // folded: lines join with spaces, an empty line is a paragraph break
  return body.reduce((acc, l) => (l === '' ? `${acc}\n` : acc === '' || acc.endsWith('\n') ? acc + l : `${acc} ${l}`), '')
}

export const BRIEF_EXAMPLE = {
  company: topLevelText(briefYaml, 'company'),
  story: topLevelText(briefYaml, 'story'),
}

/** examples/stories/nahapravda.yaml: demo scenario 3, the model's limits. */
export const NAHAPRAVDA_EXAMPLE = {
  company: topLevelText(nahapravdaYaml, 'company'),
  story: topLevelText(nahapravdaYaml, 'story'),
}

/** examples/stories/zrnko.yaml: demo scenario 2, the prompt behind examples/a.yaml. */
export const ZRNKO_EXAMPLE = {
  company: topLevelText(zrnkoYaml, 'company'),
  story: topLevelText(zrnkoYaml, 'story'),
}
