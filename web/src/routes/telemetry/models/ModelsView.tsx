import type { ObservabilitySummary } from '@/api/client'
import { formatCompact, formatInt, formatMs, formatPercent, formatUsd } from '@/utils/telemetryFormat'
import { ChartCard, RankedBars } from '../charts'
import { EmptyTable, SectionHeader, Stat, Table } from '../primitives'

export function ModelsView({ data }: { data: ObservabilitySummary }) {
  const ordinaryInputTokens = Math.max(
    data.totals.input_tokens - data.totals.cached_tokens - data.totals.cache_write_tokens,
    0,
  )
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

      <section className="min-w-0">
        <SectionHeader>Burn report</SectionHeader>
        <p className="mb-3 text-xs text-(--color-text-muted)">
          Tokens billed and where the money went, per model. The blended
          rate folds in cache efficiency, so it compares two models fairly
          where a headline price cannot.
        </p>
        {models.length === 0 ? (
          <EmptyTable label="No LLM calls recorded in this window." />
        ) : (
          <Table
            ariaLabel="Tokens and cost by provider and model"
            headers={[
              'Provider:model',
              'Input',
              'Output',
              'Cache rd',
              'Cache wr',
              '$ input',
              '$ output',
              '$ cache rd',
              '$ cache wr',
              'Total',
              '$ / 1M',
            ]}
            rows={models.map((model) => [
              model.provider_model,
              formatCompact(model.input_tokens),
              formatCompact(model.output_tokens),
              formatCompact(model.cached_tokens),
              formatCompact(model.cache_write_tokens),
              formatUsd(model.input_usd),
              formatUsd(model.output_usd),
              formatUsd(model.cache_read_usd),
              formatUsd(model.cache_write_usd),
              formatUsd(model.estimated_cost_usd),
              formatUsd(model.usd_per_mtok),
            ])}
            align={[
              'left',
              'right',
              'right',
              'right',
              'right',
              'right',
              'right',
              'right',
              'right',
              'right',
              'right',
            ]}
          />
        )}
      </section>

      <section className="min-w-0">
        <SectionHeader>Model performance</SectionHeader>
        {models.length === 0 ? (
          <EmptyTable label="No LLM calls recorded in this window." />
        ) : (
          <Table
            ariaLabel="Performance by provider and model"
            headers={['Provider:model', 'Calls', 'Errors', 'p50', 'p95', 'Cache hit', 'Reasoning']}
            rows={models.map((model) => [
              model.provider_model,
              formatInt(model.calls),
              formatPercent(model.error_rate),
              formatMs(model.p50_ms),
              formatMs(model.p95_ms),
              formatPercent(model.cache_percent),
              formatCompact(model.reasoning_tokens),
            ])}
            align={['left', 'right', 'right', 'right', 'right', 'right', 'right']}
          />
        )}
      </section>

      <section>
        <SectionHeader>Prompt cache</SectionHeader>
        <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Read tokens" value={formatCompact(data.totals.cached_tokens)} />
          <Stat label="Write tokens" value={formatCompact(data.totals.cache_write_tokens)} />
          <Stat label="Ordinary input" value={formatCompact(ordinaryInputTokens)} />
          <Stat label="Hit rate" value={formatPercent(data.totals.cache_percent)} />
        </div>
        {data.cache_by_step.length === 0 ? (
          <EmptyTable label="No cache usage recorded in this window." />
        ) : (
          <Table
            ariaLabel="Cache usage by operation"
            headers={['Operation', 'Provider:model', 'Calls', 'Read', 'Write', 'Ordinary', 'Hit rate', 'Cost']}
            rows={data.cache_by_step.map((step) => [
              step.step,
              step.provider_model,
              formatInt(step.calls),
              formatCompact(step.cached_tokens),
              formatCompact(step.cache_write_tokens),
              formatCompact(step.ordinary_input_tokens),
              formatPercent(step.cache_percent),
              formatUsd(step.estimated_cost_usd),
            ])}
            align={['left', 'left', 'right', 'right', 'right', 'right', 'right', 'right']}
          />
        )}
      </section>
    </div>
  )
}
