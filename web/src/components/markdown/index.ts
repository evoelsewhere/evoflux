/**
 * Public surface of the markdown feature components (Intelligent UI).
 *
 * Types here are the clean public names Stream 2's `UiChart` re-points to
 * (§8.3 of documents/plans/2026-10-13-intelligent-ui.md). The heavy
 * renderers stay behind `React.lazy` — importing this barrel never pulls
 * Recharts or Mermaid into the initial bundle.
 */

export { parseChartSpec } from './chart-spec'
export type { ChartSeries, ChartSpec } from './chart-spec'
export type { ChartBlockProps, ChartTheme } from './ChartBlock'
export { default as ChartFence, type ChartFenceProps } from './ChartFence'
export { default as MermaidFence, type MermaidFenceProps } from './MermaidFence'
