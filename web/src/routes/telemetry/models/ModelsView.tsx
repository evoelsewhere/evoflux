import type { ObservabilitySummary } from '@/api/client'
import { formatCompact, formatInt, formatMs, formatPercent, formatUsd } from '@/utils/telemetryFormat'
import { ChartCard, RankedBars } from '../charts'
import { EmptyTable, SectionHeader, Stat, Table } from '../primitives'

export function ModelsView({ data }: { data: ObservabilitySummary }) {
  const cacheMissTokens = Math.max(data.totals.input_tokens - data.totals.cached_tokens, 0)
  const models = data.by_model

  return (
    <div className="flex flex-col gap-5">
      <section>
        <SectionHeader>Model fleet</SectionHeader>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Models" value={formatInt(models.length)} />
          <Stat label="LLM calls" value={formatInt(data.totals.llm_calls)} />
          <Stat label="Cache hit" value={formatPercent(data.totals.cache_percent)} />
          <Stat label="Estimated cost" value={formatUsd(data.totals.estimated_cost_usd)} />
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="Cost by model" description="Estimated spend from provider-reported usage" legend={[]}>
          <RankedBars
            rows={models.slice(0, 8).map((model) => ({
              label: model.provider_model,
              value: model.estimated_cost_usd,
              secondary: `${formatInt(model.calls)} calls`,
            }))}
            valueFormatter={formatUsd}
          />
        </ChartCard>
        <ChartCard title="Latency by model" description="p95 response duration; error rate shown alongside" legend={[]}>
          <RankedBars
            rows={[...models].sort((a, b) => b.p95_ms - a.p95_ms).slice(0, 8).map((model) => ({
              label: model.provider_model,
              value: model.p95_ms,
              secondary: `${formatPercent(model.error_rate)} errors`,
              tone: model.error_rate > 0 ? 'danger' as const : undefined,
            }))}
            valueFormatter={formatMs}
          />
        </ChartCard>
      </div>

      <section>
        <SectionHeader>Model performance</SectionHeader>
        {models.length === 0 ? (
          <EmptyTable label="No LLM calls recorded in this window." />
        ) : (
          <Table
            ariaLabel="Performance by provider and model"
            headers={['Provider:model', 'Calls', 'Errors', 'p50', 'p95', 'Input', 'Output', 'Cache', 'Cost']}
            rows={models.map((model) => [
              model.provider_model,
              formatInt(model.calls),
              formatPercent(model.error_rate),
              formatMs(model.p50_ms),
              formatMs(model.p95_ms),
              formatCompact(model.input_tokens),
              formatCompact(model.output_tokens),
              formatPercent(model.cache_percent),
              formatUsd(model.estimated_cost_usd),
            ])}
            align={['left', 'right', 'right', 'right', 'right', 'right', 'right', 'right', 'right']}
          />
        )}
      </section>

      <section>
        <SectionHeader>Prompt cache</SectionHeader>
        <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Stat label="Hit tokens" value={formatCompact(data.totals.cached_tokens)} />
          <Stat label="Miss tokens" value={formatCompact(cacheMissTokens)} />
          <Stat label="Hit rate" value={formatPercent(data.totals.cache_percent)} />
        </div>
        {data.cache_by_step.length === 0 ? (
          <EmptyTable label="No cache usage recorded in this window." />
        ) : (
          <Table
            ariaLabel="Cache usage by operation"
            headers={['Operation', 'Provider:model', 'Calls', 'Hit', 'Miss', 'Hit rate', 'Cost']}
            rows={data.cache_by_step.map((step) => [
              step.step,
              step.provider_model,
              formatInt(step.calls),
              formatCompact(step.cached_tokens),
              formatCompact(step.miss_tokens),
              formatPercent(step.cache_percent),
              formatUsd(step.estimated_cost_usd),
            ])}
            align={['left', 'left', 'right', 'right', 'right', 'right', 'right']}
          />
        )}
      </section>
    </div>
  )
}
