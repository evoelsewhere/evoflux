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

import { cleanupMermaidTempNodes } from './mermaidTempNodes'
import { FenceSkeleton } from './ChartFence'

type MermaidApi = typeof import('mermaid')['default']

let initializedTheme: string | null = null
let renderCounter = 0

type AmdDefineGlobal = { define?: unknown }

/**
 * Monaco's editor loads through its AMD loader, which installs a global
 * `define` (a `var`-declared global: non-configurable but writable).
 * Mermaid's pre-bundled UMD dependencies detect that `define`, register
 * anonymously, and the loader throws "Can only have one anonymous define
 * call per script file" — failing the whole render. Clear the global for the
 * duration of mermaid's import+render and restore it afterwards; monaco only
 * needs it while its own plugin scripts execute.
 */
async function withAmdDefineHidden<T>(run: () => Promise<T>): Promise<T> {
  const scope = globalThis as AmdDefineGlobal
  const savedDefine = scope.define
  if (typeof savedDefine !== 'function') return run()
  try {
    scope.define = undefined
  } catch {
    return run()
  }
  if (scope.define !== undefined) return run() // read-only in this environment
  try {
    return await run()
  } finally {
    scope.define = savedDefine
  }
}

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
    withAmdDefineHidden(() =>
      getMermaid(theme).then((mermaid) => mermaid.render(id, rawText)),
    )
      .then((result) => {
        if (!cancelled) {
          setSvg(result.svg)
          setError(null)
        }
      })
      .catch((cause: unknown) => {
        // Keep the failure reason visible in the console — the UI only shows
        // a one-line notice, so this is the only place to debug render errors.
        console.error('[mermaid] render failed:', cause)
        if (!cancelled) {
          setSvg(null)
          setError(cause instanceof Error ? cause.message : String(cause))
        }
      })
      .finally(() => {
        // Successful renders self-clean, but failed renders leave mermaid's
        // temp container (#d{id}) in document.body — sweep it so a retry
        // (theme change, content edit) starts from a clean slate.
        cleanupMermaidTempNodes(id)
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
