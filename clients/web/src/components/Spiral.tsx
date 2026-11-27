// The 🌀 in the header: one slow turn every 14 s (anime.js); still under prefers-reduced-motion.
import { useEffect, useRef } from 'react'
import { animate, createScope, type Scope } from 'animejs'

export function Spiral() {
  const root = useRef<HTMLSpanElement>(null)
  const scope = useRef<Scope | null>(null)
  useEffect(() => {
    scope.current = createScope({ root, mediaQueries: { reduce: '(prefers-reduced-motion: reduce)' } }).add((self) => {
      if (self?.matches.reduce) return
      animate('.spin', { rotate: 360, duration: 14_000, ease: 'linear', loop: true })
    })
    return () => scope.current?.revert()
  }, [])
  return (
    <span ref={root} aria-hidden className="inline-grid size-7 place-items-center">
      <span className="spin inline-block text-lg leading-none">🌀</span>
    </span>
  )
}
