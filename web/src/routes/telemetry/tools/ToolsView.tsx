import type { ObservabilitySummary } from '@/api/client'
import { formatInt, formatMs, formatPercent } from '@/utils/telemetryFormat'
import { ChartCard, RankedBars } from '../charts'
import { EmptyTable, SectionHeader, Stat, Table } from '../primitives'

export function ToolsView({ data }: { data: ObservabilitySummary }) {
  const tools = data.by_tool
  const toolErrors = tools.reduce((sum, tool) => sum + tool.errors, 0)
  const errorRate = data.totals.tool_calls > 0 ? (toolErrors / data.totals.tool_calls) * 100 : 0

  return (
    <div className="flex flex-col gap-5">
      <section>
        <SectionHeader>Tool health</SectionHeader>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Tool calls" value={formatInt(data.totals.tool_calls)} />
          <Stat label="Tools used" value={formatInt(tools.length)} />
          <Stat label="Tool errors" value={formatInt(toolErrors)} hint={`${formatPercent(errorRate)} of calls`} tone={toolErrors > 0 ? 'danger' : undefined} />
          <Stat label="Tool p95" value={formatMs(data.latency_ms.tool_p95)} hint={`p50 ${formatMs(data.latency_ms.tool_p50)}`} />
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="Most used tools" description="Completed executions by tool name" legend={[]}>
          <RankedBars rows={tools.slice(0, 10).map((tool) => ({
            label: tool.tool,
            value: tool.calls,
            secondary: `${formatPercent(tool.error_rate)} errors`,
          }))} />
        </ChartCard>
        <ChartCard title="Slowest tools" description="95th percentile execution duration" legend={[]}>
          <RankedBars
            rows={[...tools].sort((a, b) => b.p95_ms - a.p95_ms).slice(0, 10).map((tool) => ({
              label: tool.tool,
              value: tool.p95_ms,
              secondary: `${formatInt(tool.calls)} calls`,
              tone: tool.error_rate > 0 ? 'danger' as const : undefined,
            }))}
            valueFormatter={formatMs}
          />
        </ChartCard>
      </div>

      <section>
        <SectionHeader>Tool reliability</SectionHeader>
        {tools.length === 0 ? (
          <EmptyTable label="No tool calls recorded in this window." />
        ) : (
          <Table
            ariaLabel="Tool reliability and latency"
            headers={['Tool', 'Calls', 'Errors', 'Error rate', 'Average', 'p50', 'p95']}
            rows={tools.map((tool) => [
              tool.tool,
              formatInt(tool.calls),
              formatInt(tool.errors),
              formatPercent(tool.error_rate),
              formatMs(tool.avg_ms),
              formatMs(tool.p50_ms),
              formatMs(tool.p95_ms),
            ])}
            align={['left', 'right', 'right', 'right', 'right', 'right', 'right']}
          />
        )}
      </section>
    </div>
  )
}
