import { Info } from 'lucide-react'
import type { ObservabilitySummary } from '@/api/client'
import {
  formatCompact,
  formatInt,
  formatMs,
  formatPercent,
  formatUsd,
} from '@/utils/telemetryFormat'
import { ChartCard, TimeChart, TokenVolumeChart } from '../charts'
import { SectionHeader, Stat } from '../primitives'

const COLORS = {
  turns: 'var(--color-marker-blue)',
  llm: 'var(--color-violet)',
  tools: 'var(--color-marker-mint)',
  errors: 'var(--color-error)',
  input: 'var(--color-marker-blue)',
  output: 'var(--color-marker-orange)',
}

export function SummaryView({ data }: { data: ObservabilitySummary }) {
  const sampled = data.sample_ratio < 1.0
  const { totals, latency_ms: latency } = data

  return (
    <div className="flex flex-col gap-5">
      {sampled && (
        <div className="flex items-start gap-2 rounded-lg border border-(--color-border) bg-(--bg-key)/40 p-3">
          <Info size={14} className="mt-0.5 shrink-0 text-(--color-accent)" />
          <p className="text-xs text-(--color-text-2)">
            Spans are sampled at <strong>{Math.round(data.sample_ratio * 100)}%</strong>.
            Counts and totals are observed values, not extrapolated estimates. Set{' '}
            <code className="rounded bg-(--bg-card) px-1 py-0.5 text-xs">OTEL_SPAN_SAMPLE_RATIO=1.0</code>{' '}
            for complete coverage.
          </p>
        </div>
      )}

      <section>
        <SectionHeader>Health</SectionHeader>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-6">
          <Stat label="Turns" value={formatInt(totals.turns)} hint={`${formatInt(totals.llm_calls)} LLM calls`} />
          <Stat label="Tool calls" value={formatInt(totals.tool_calls)} />
          <Stat label="Failed turns" value={formatInt(totals.failed_turns)} hint={`${formatPercent(totals.error_rate)} of turns`} tone={totals.failed_turns > 0 ? 'danger' : undefined} />
          <Stat label="Error spans" value={formatInt(totals.error_spans)} tone={totals.error_spans > 0 ? 'danger' : undefined} />
          <Stat label="Turn p95" value={formatMs(latency.turn_p95)} hint={`p50 ${formatMs(latency.turn_p50)}`} />
          <Stat label="LLM p95" value={formatMs(latency.llm_p95)} hint={`p50 ${formatMs(latency.llm_p50)}`} />
        </div>
      </section>

      <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard
          title="Request volume"
          description="Completed turns and downstream operations per bucket"
          legend={[
            { label: 'Turns', color: COLORS.turns },
            { label: 'LLM', color: COLORS.llm },
            { label: 'Tools', color: COLORS.tools },
          ]}
        >
          <TimeChart
            data={data.time_series}
            bucketSize={data.bucket_size}
            series={[
              { key: 'turns', label: 'Turns', color: COLORS.turns, kind: 'bar' },
              { key: 'llm_calls', label: 'LLM calls', color: COLORS.llm },
              { key: 'tool_calls', label: 'Tool calls', color: COLORS.tools },
            ]}
          />
        </ChartCard>

        <ChartCard
          title="Turn latency"
          description="95th percentile end-to-end turn duration"
          legend={[{ label: 'p95', color: COLORS.errors }]}
        >
          <TimeChart
            data={data.time_series}
            bucketSize={data.bucket_size}
            series={[{ key: 'turn_p95_ms', label: 'Turn p95', color: COLORS.errors }]}
            valueFormatter={formatMs}
          />
        </ChartCard>
      </div>

      <section>
        <SectionHeader>Usage & cost</SectionHeader>
        <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Input" value={formatCompact(totals.input_tokens)} />
          <Stat label="Output" value={formatCompact(totals.output_tokens)} />
          <Stat label="Cache hit" value={formatPercent(totals.cache_percent)} />
          <Stat label="Estimated cost" value={formatUsd(totals.estimated_cost_usd)} />
        </div>
        <ChartCard
          title="Token volume"
          description="Independent scales keep both input and output trends readable"
          legend={[
            { label: 'Input', color: COLORS.input },
            { label: 'Output', color: COLORS.output },
          ]}
        >
          <TokenVolumeChart data={data.time_series} bucketSize={data.bucket_size} />
        </ChartCard>
      </section>
    </div>
  )
}
