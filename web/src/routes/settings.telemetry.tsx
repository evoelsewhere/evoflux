/**
 * Telemetry panel for the settings modal — compact summary + recent traces
 * without the full-page Telemetry chrome/sidebar.
 */
import { useMemo, useState } from 'react'
import { ArrowLeft, BarChart3 } from 'lucide-react'

import { useIsMobile } from '@/hooks/use-mobile'
import { SettingsGroup, SettingsPage } from '@/components/settings/SettingsLayout'
import { SegmentedControl } from '@/components/ui/segmented-control'
import {
  useInfiniteTracesQuery,
  useObservabilitySummaryQuery,
  useTraceDetailQuery,
} from '@/queries'
import { formatShortId } from '@/utils/telemetryFormat'
import { ErrorState, LoadingState } from '@/routes/telemetry/chrome'
import { SummaryView } from '@/routes/telemetry/summary/SummaryView'
import { TracesSection } from '@/routes/telemetry/traces/TracesSection'
import { SpanDetailPanel } from '@/routes/telemetry/waterfall/SpanDetailPanel'
import { Waterfall } from '@/routes/telemetry/waterfall/Waterfall'

type WindowDays = 1 | 7 | 30 | 90

const RANGES: { value: WindowDays; label: string }[] = [
  { value: 1, label: '24 h' },
  { value: 7, label: '7 d' },
  { value: 30, label: '30 d' },
  { value: 90, label: '90 d' },
]

const TRACE_PAGE_SIZE = 25

export function TelemetrySettingsPage() {
  const [days, setDays] = useState<WindowDays>(7)
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null)

  return (
    <SettingsPage
      icon={BarChart3}
      title="Telemetry"
      lede={
        selectedTraceId
          ? undefined
          : 'Span aggregates and recent traces for debugging agent runs on this machine.'
      }
      actions={
        !selectedTraceId ? (
          <SegmentedControl
            options={RANGES}
            value={days}
            onChange={setDays}
            layoutId="telemetry-range"
            ariaLabel="Time window"
          />
        ) : undefined
      }
    >
      {selectedTraceId ? (
        <TraceDetail
          traceId={selectedTraceId}
          onBack={() => setSelectedTraceId(null)}
        />
      ) : (
        <SummaryBody days={days} onSelectTrace={setSelectedTraceId} />
      )}
    </SettingsPage>
  )
}

function SummaryBody({
  days,
  onSelectTrace,
}: {
  days: WindowDays
  onSelectTrace: (traceId: string) => void
}) {
  const summary = useObservabilitySummaryQuery(days)
  const traces = useInfiniteTracesQuery(days, TRACE_PAGE_SIZE)
  const traceRows = useMemo(
    () => traces.data?.pages.flatMap((page) => page.traces) ?? [],
    [traces.data],
  )
  const traceTotal = traces.data?.pages[0]?.total ?? traceRows.length

  return (
    <>
      {summary.isLoading ? (
        <LoadingState label="Loading span aggregates…" />
      ) : summary.isError ? (
        <ErrorState
          message={String(summary.error)}
          onRetry={() => summary.refetch()}
        />
      ) : summary.data ? (
        <div className="flex flex-col gap-6">
          <SummaryView data={summary.data} />
          <TracesSection
            query={traces}
            traces={traceRows}
            limit={TRACE_PAGE_SIZE}
            total={traceTotal}
            hasNext={traces.hasNextPage}
            onLoadMore={() => {
              if (!traces.hasNextPage || traces.isFetchingNextPage) return
              void traces.fetchNextPage()
            }}
            onSelectTrace={onSelectTrace}
          />
        </div>
      ) : null}
    </>
  )
}

function TraceDetail({
  traceId,
  onBack,
}: {
  traceId: string
  onBack: () => void
}) {
  const isMobile = useIsMobile()
  const { data, isLoading, isError, error, refetch } = useTraceDetailQuery(traceId)
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null)
  const selectedSpan = data?.spans.find((span) => span.span_id === selectedSpanId) ?? null

  return (
    <SettingsGroup bare className="-mx-4 overflow-hidden sm:-mx-6">
      <div className="flex shrink-0 items-center gap-2 border-b border-(--color-border) px-4 py-2 sm:px-6">
        <button
          type="button"
          onClick={onBack}
          className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          aria-label="Back to telemetry summary"
        >
          <ArrowLeft size={14} />
        </button>
        <p className="truncate text-xs text-(--color-text-muted)">
          Trace {formatShortId(traceId)}
        </p>
      </div>
      <div className="relative flex min-h-64 overflow-hidden">
        <div className="min-w-0 flex-1 overflow-y-auto p-4 sm:px-6">
          {isLoading ? (
            <LoadingState label="Loading trace…" />
          ) : isError ? (
            <ErrorState message={String(error)} onRetry={() => refetch()} />
          ) : data ? (
            <Waterfall
              spans={data.spans}
              selectedSpanId={selectedSpanId}
              onSelectSpan={setSelectedSpanId}
            />
          ) : null}
        </div>
        {selectedSpan && (
          <div className={isMobile
            ? 'absolute inset-0 z-(--z-panel) bg-(--bg-page)'
            : 'w-72 shrink-0 border-l border-(--color-border)'}
          >
            <SpanDetailPanel span={selectedSpan} onClose={() => setSelectedSpanId(null)} fullWidth={isMobile} />
          </div>
        )}
      </div>
    </SettingsGroup>
  )
}
