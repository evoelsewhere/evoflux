/**
 * useReducedMotion — honors OS `prefers-reduced-motion` and the Appearance
 * "UI animations → Reduced" setting (`data-motion="reduced"`).
 *
 * The CSS layer in `index.css` also short-circuits transitions when either
 * gate is active; use this hook for JS-driven motion (framer-motion,
 * custom rAF loops).
 */
import { useSyncExternalStore } from 'react'
import { useReducedMotion as useFramerReducedMotion } from 'framer-motion'

function subscribeMotionAttr(onStoreChange: () => void): () => void {
  const observer = new MutationObserver(onStoreChange)
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-motion'],
  })
  window.addEventListener('evoflux:appearance-change', onStoreChange)
  return () => {
    observer.disconnect()
    window.removeEventListener('evoflux:appearance-change', onStoreChange)
  }
}

function readMotionReduced(): boolean {
  return document.documentElement.dataset.motion === 'reduced'
}

export function useReducedMotion(): boolean | null {
  const osReduced = useFramerReducedMotion()
  const userReduced = useSyncExternalStore(subscribeMotionAttr, readMotionReduced, () => false)
  if (osReduced) return true
  if (userReduced) return true
  return osReduced
}
