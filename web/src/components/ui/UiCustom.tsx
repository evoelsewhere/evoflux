import { useEffect, useMemo, useState } from 'react'
import { WidgetRenderer } from '@/components/WidgetRenderer'
import type { UiCustomBlock } from './ui-block-types'

/**
 * `custom` block (spec §3): agent-authored HTML rendered through the existing
 * `WidgetRenderer` sandbox — inherits the CSP `wrapHtml`, storage shim,
 * `sendPrompt` and resize bridges. WidgetRenderer itself is untouched; this
 * component only prepends a design-token `<style>` so widget CSS vocabulary
 * (guidelines.py) resolves from the live app theme instead of self-declaring
 * and desyncing from `html.dark`.
 */

/**
 * Frozen mapping (spec §3.3): widget vocabulary var ← app token in
 * `web/src/index.css` ← literal fallback copied from the widget guidelines
 * (`app/agent/tools/builtin/visualize/guidelines.py:49-75`). Light literals
 * first, dark second.
 */
const TOKEN_MAP: ReadonlyArray<
  readonly [widgetVar: string, appVar: string, light: string, dark: string]
> = [
  ['--color-text-primary', '--color-text', '#1a1a1a', '#f5f5f5'],
  ['--color-text-secondary', '--color-text-2', '#666666', '#a0a0a0'],
  ['--color-background', '--bg-card', '#ffffff', '#1a1a1a'],
  ['--color-background-secondary', '--bg-page', '#f5f5f5', '#2a2a2a'],
  ['--color-border', '--color-border', '#e0e0e0', '#3a3a3a'],
  ['--color-accent', '--color-accent', '#534ab7', '#7f77dd'],
  ['--color-success', '--color-success', '#1d9e75', '#5dcaa5'],
  ['--color-warning', '--color-warning', '#d85a30', '#f0997b'],
  ['--color-error', '--color-error', '#d85a30', '#f0997b'],
]

/** App-only tokens injected verbatim (second group, spec §3.3). */
const APP_ONLY_TOKENS = [
  '--color-text-muted',
  '--color-text-subtle',
  '--bg-card',
  '--bg-input',
  '--bg-hover',
] as const

function collectWidgetTokens(): string {
  const root = document.documentElement
  const computed = getComputedStyle(root)
  const isDark = root.classList.contains('dark')
  const decls: string[] = []
  for (const [widgetVar, appVar, light, dark] of TOKEN_MAP) {
    const value = computed.getPropertyValue(appVar).trim()
    decls.push(`${widgetVar}: ${value || (isDark ? dark : light)};`)
  }
  for (const appVar of APP_ONLY_TOKENS) {
    const value = computed.getPropertyValue(appVar).trim()
    if (value) decls.push(`${appVar}: ${value};`)
  }
  decls.push(`color-scheme: ${isDark ? 'dark' : 'light'};`)
  return `<style id="evoflux-widget-tokens">:root{ ${decls.join(' ')} }</style>`
}

export function UiCustom({ block }: { block: UiCustomBlock }) {
  const [tokens, setTokens] = useState(collectWidgetTokens)

  // Re-apply on theme flip (ChartBlock.tsx:76 pattern): morphdom diffs the
  // updated <style> into the mounted frame in place.
  useEffect(() => {
    const observer = new MutationObserver(() => setTokens(collectWidgetTokens()))
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    })
    return () => observer.disconnect()
  }, [])

  const html = useMemo(() => tokens + block.html, [tokens, block.html])
  const height = block.height ?? 320

  return (
    <div style={{ height }}>
      <WidgetRenderer html={html} height={height} isStreaming={false} />
    </div>
  )
}
