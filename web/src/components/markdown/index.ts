/**
 * Public surface of the markdown feature components (Intelligent UI).
 *
 * Shared markdown types and lazy renderer exports. Importing this barrel
 * never pulls Recharts or Mermaid into the initial bundle.
 */

export { parseChartSpec } from './chart-spec'
export type { ChartSeries, ChartSpec } from './chart-spec'
export type { ChartBlockProps, ChartTheme } from './ChartBlock'
export { default as ChartFence, type ChartFenceProps } from './ChartFence'
export { default as MarkdownTable, type MarkdownTableProps } from './MarkdownTable'
export { default as MermaidFence, type MermaidFenceProps } from './MermaidFence'
