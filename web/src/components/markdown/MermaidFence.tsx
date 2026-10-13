/**
 * ```mermaid fence wrapper (Intelligent UI feature D).
 *
 * Loads the mermaid runtime once per theme through a dynamic import —
 * mermaid itself never lands in the initial bundle — and renders with
 * `securityLevel: 'strict'` so diagram text cannot execute scripts.
 * Render failures degrade to the caller's CodeBlock fallback with a
 * one-line notice once the stream has settled.
 */

import { useEffect, useState, type ReactNode } from 'react'

import { FenceSkeleton } from './ChartFence'

type MermaidApi = typeof import('mermaid')['default']

let initializedTheme: string | null = null
let renderCounter = 0

async function getMermaid(theme: 'default' | 'dark'): Promise<MermaidApi> {
  const mermaid = (await import('mermaid')).default
  if (initializedTheme !== theme) {
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme })
    initializedTheme = theme
  }
  return mermaid
}

function currentTheme(): 'default' | 'dark' {
  if (typeof window === 'undefined' || !window.matchMedia) return 'default'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default'
}

export interface MermaidFenceProps {
  rawText: string
  streaming: boolean
  fallback: ReactNode
}

export default function MermaidFence({ rawText, streaming, fallback }: MermaidFenceProps) {
  const [svg, setSvg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const theme = currentTheme()
    const id = `evoflux-mermaid-${++renderCounter}`
    getMermaid(theme)
      .then((mermaid) => mermaid.render(id, rawText))
      .then((result) => {
        if (cancelled) return
        setSvg(result.svg)
        setError(null)
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setSvg(null)
        setError(cause instanceof Error ? cause.message : String(cause))
      })
    return () => {
      cancelled = true
    }
  }, [rawText])

  if (svg) {
    return (
      <div className="not-prose my-3 overflow-x-auto rounded-xl border border-(--color-border-subtle) bg-(--bg-card) p-3">
        <div
          className="evoflux-mermaid"
          // mermaid.render output is sanitized by securityLevel: 'strict'.
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    )
  }

  if (error) {
    if (streaming) return <FenceSkeleton />
    return (
      <>
        {fallback}
        <p className="mt-1 text-xs text-(--color-text-muted)">Mermaid diagram failed to render</p>
      </>
    )
  }

  return <FenceSkeleton />
}
