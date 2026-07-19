/** /settings/diagnostics — active health checks across all EvoFlux subsystems. */
import { AlertTriangle, ArrowLeft, CheckCircle2, Loader2, RefreshCw, Stethoscope, XCircle } from 'lucide-react'

import { useDiagnosticsQuery } from '@/queries'
import { useIsMobile } from '@/hooks/use-mobile'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { DiagnosticsCheck, DiagnosticsStatus } from '@/api/types'

function StatusIcon({ status, className }: { status: DiagnosticsStatus; className?: string }) {
  if (status === 'ok')
    return <CheckCircle2 size={16} className={cn('text-green-500', className)} aria-hidden="true" />
  if (status === 'warn')
    return <AlertTriangle size={16} className={cn('text-yellow-500', className)} aria-hidden="true" />
  return <XCircle size={16} className={cn('text-red-500', className)} aria-hidden="true" />
}

function SummaryBadge({ summary }: { summary: DiagnosticsStatus }) {
  const variants: Record<DiagnosticsStatus, { label: string; className: string }> = {
    ok: { label: 'All systems OK', className: 'bg-green-500/10 text-green-600 dark:text-green-400 ring-green-500/20' },
    warn: { label: 'Warnings detected', className: 'bg-yellow-500/10 text-yellow-600 dark:text-yellow-400 ring-yellow-500/20' },
    fail: { label: 'Errors detected', className: 'bg-red-500/10 text-red-600 dark:text-red-400 ring-red-500/20' },
  }
  const v = variants[summary]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset',
        v.className,
      )}
    >
      <StatusIcon status={summary} className="!size-3" />
      {v.label}
    </span>
  )
}

function CheckRow({ check }: { check: DiagnosticsCheck }) {
  return (
    <div
      className={cn(
        'flex items-start gap-3 rounded-lg border p-3.5 transition-colors',
        check.status === 'ok' && 'border-(--color-border) bg-(--bg-card)',
        check.status === 'warn' && 'border-yellow-500/20 bg-yellow-500/5',
        check.status === 'fail' && 'border-red-500/20 bg-red-500/5',
      )}
    >
      <StatusIcon status={check.status} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="text-sm font-medium text-(--color-text)">{check.label}</p>
        <p className="text-sm text-(--color-text-muted)">{check.detail}</p>
        {check.hint && (
          <p className="text-xs text-(--color-text-muted) italic">{check.hint}</p>
        )}
      </div>
    </div>
  )
}

export function DiagnosticsPage() {
  const isMobile = useIsMobile()
  const settingsNavigate = useSettingsNavigate()
  const { data, isLoading, isRefetching, error, refetch } = useDiagnosticsQuery()

  return (
    <>
      <header className="sticky top-0 z-(--z-panel) flex h-14 shrink-0 items-center gap-3 border-b border-(--color-border) bg-(--bg-page) px-4">
        {isMobile && (
          <button
            type="button"
            onClick={() => settingsNavigate('/settings')}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Back to settings"
          >
            <ArrowLeft size={14} />
          </button>
        )}
        <Stethoscope size={15} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
        <h1 className="flex-1 truncate text-sm font-semibold text-(--color-text)">Diagnostics</h1>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => refetch()}
          disabled={isLoading || isRefetching}
          className="gap-1.5 text-xs"
        >
          <RefreshCw
            size={13}
            className={cn('shrink-0', (isLoading || isRefetching) && 'animate-spin')}
            aria-hidden="true"
          />
          Refresh
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-5 p-6">
          <p className="text-sm leading-relaxed text-(--color-text-muted)">
            Active health checks across every EvoFlux subsystem. Use this to
            diagnose configuration issues, missing API keys, or resource
            constraints.
          </p>

          {isLoading && (
            <div className="flex items-center gap-2 py-8 text-sm text-(--color-text-muted)">
              <Loader2 size={16} className="animate-spin" aria-hidden="true" />
              Running checks…
            </div>
          )}

          {error && !isLoading && (
            <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-600 dark:text-red-400">
              Could not reach the backend: {error instanceof Error ? error.message : String(error)}
            </div>
          )}

          {data && (
            <>
              <div className="flex items-center gap-3">
                <SummaryBadge summary={data.summary} />
                {isRefetching && (
                  <Loader2 size={13} className="animate-spin text-(--color-text-muted)" aria-hidden="true" />
                )}
              </div>

              <div className="space-y-2">
                {data.checks.map((check) => (
                  <CheckRow key={check.id} check={check} />
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}
