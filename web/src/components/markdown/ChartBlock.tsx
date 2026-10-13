/**
 * Recharts renderer for the ```chart fence (Intelligent UI feature D).
 *
 * This module is only ever reached through `React.lazy`, so `recharts`
 * becomes one isolated code-split chunk and never lands in the initial
 * bundle. Stream 2's `UiChart` re-points at the same block (§8.3).
 */

import { useEffect, useState, type ReactElement, type ReactNode } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Area,
  AreaChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { ChartSpec } from './chart-spec'

export interface ChartBlockProps {
  spec: ChartSpec
}

/** Categorical series palette that reads acceptably on both themes. */
const PALETTE = ['#2563eb', '#7c3aed', '#0d9488', '#d97706', '#db2777', '#0891b2']

const FALLBACK_THEME = {
  text: '#1D1D1D',
  subtle: '#6A6A6A',
  grid: '#E5E5E5',
  surface: '#FFFFFF',
}

export interface ChartTheme {
  text: string
  subtle: string
  grid: string
  surface: string
}

function readToken(styles: CSSStyleDeclaration, name: string, fallback: string) {
  const value = styles.getPropertyValue(name).trim()
  return value || fallback
}

function computeChartTheme(): ChartTheme {
  // SVG presentation attributes cannot take var() — the tokens are resolved
  // once against the live computed style and passed down as plain colors.
  const styles = getComputedStyle(document.documentElement)
  return {
    text: readToken(styles, '--color-text', FALLBACK_THEME.text),
    subtle: readToken(styles, '--color-text-subtle', FALLBACK_THEME.subtle),
    grid: readToken(styles, '--color-border-subtle', FALLBACK_THEME.grid),
    surface: readToken(styles, '--bg-card', FALLBACK_THEME.surface),
  }
}

/**
 * Resolve the app's `--color-*` tokens for Recharts SVG attributes and
 * refresh them when the theme flips (class/style change on `<html>`).
 */
function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>(computeChartTheme)

  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(computeChartTheme()))
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class', 'style'],
    })
    return () => observer.disconnect()
  }, [])

  return theme
}

function seriesColor(theme: ChartTheme, index: number, explicit?: string) {
  return explicit ?? PALETTE[index % PALETTE.length] ?? theme.text
}

export default function ChartBlock({ spec }: ChartBlockProps) {
  const theme = useChartTheme()
  const { type, xKey, series, data, unit } = spec

  const tickProps = {
    fill: theme.subtle,
    fontSize: 11,
  } as const

  const grid = <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} vertical={false} />
  const legend = series.length > 1 ? <Legend wrapperStyle={{ fontSize: 11 }} /> : null
  const tooltip = (
    <Tooltip
      formatter={(value) =>
        typeof value === 'number' || typeof value === 'string'
          ? `${value}${unit ?? ''}`
          : value
      }
      contentStyle={{
        background: theme.surface,
        border: `1px solid ${theme.grid}`,
        borderRadius: 8,
        fontSize: 12,
        color: theme.text,
      }}
    />
  )

  let chart: ReactNode
  if (type === 'line') {
    chart = (
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
        {grid}
        <XAxis dataKey={xKey} tick={tickProps} stroke={theme.grid} tickLine={false} axisLine={false} />
        <YAxis tick={tickProps} stroke={theme.grid} tickLine={false} axisLine={false} width={40} />
        {tooltip}
        {legend}
        {series.map((s, index) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label ?? s.key}
            stroke={seriesColor(theme, index, s.color)}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    )
  } else if (type === 'area') {
    chart = (
      <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
        {grid}
        <XAxis dataKey={xKey} tick={tickProps} stroke={theme.grid} tickLine={false} axisLine={false} />
        <YAxis tick={tickProps} stroke={theme.grid} tickLine={false} axisLine={false} width={40} />
        {tooltip}
        {legend}
        {series.map((s, index) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label ?? s.key}
            stroke={seriesColor(theme, index, s.color)}
            fill={seriesColor(theme, index, s.color)}
            fillOpacity={0.15}
            isAnimationActive={false}
          />
        ))}
      </AreaChart>
    )
  } else if (type === 'bar') {
    chart = (
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
        {grid}
        <XAxis dataKey={xKey} tick={tickProps} stroke={theme.grid} tickLine={false} axisLine={false} />
        <YAxis tick={tickProps} stroke={theme.grid} tickLine={false} axisLine={false} width={40} />
        {tooltip}
        {legend}
        {series.map((s, index) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label ?? s.key}
            fill={seriesColor(theme, index, s.color)}
            stackId={spec.stacked ? 'stack' : undefined}
            radius={spec.stacked ? undefined : [4, 4, 0, 0]}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    )
  } else {
    // pie — validated to exactly one series in parseChartSpec.
    const sliceKey = series[0]?.key ?? ''
    chart = (
      <PieChart>
        {tooltip}
        {legend}
        <Pie
          data={data}
          dataKey={sliceKey}
          nameKey={xKey}
          isAnimationActive={false}
          outerRadius="75%"
        >
          {data.map((_, index) => (
            <Cell key={index} fill={seriesColor(theme, index, series[0]?.color)} />
          ))}
        </Pie>
      </PieChart>
    )
  }

  return (
    <div className="not-prose my-3 overflow-hidden rounded-xl border border-(--color-border-subtle) bg-(--bg-card) p-3">
      {spec.title ? (
        <p className="mb-1 text-xs font-medium text-(--color-text)">{spec.title}</p>
      ) : null}
      {spec.yLabel ? (
        <p className="text-[10px] text-(--color-text-subtle)">{spec.yLabel}</p>
      ) : null}
      <div className="h-[260px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          {chart as ReactElement}
        </ResponsiveContainer>
      </div>
    </div>
  )
}
