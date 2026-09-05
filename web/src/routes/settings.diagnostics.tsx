/** /settings/diagnostics — active health checks across all EvoFlux subsystems. */
import { motion } from 'framer-motion'
import { AlertTriangle, CheckCircle2, RefreshCw, Activity, XCircle } from 'lucide-react'

import { useDiagnosticsQuery } from '@/queries'
import { SettingsCallout, SettingsGroup, SettingsPage } from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { Button } from '@/components/ui/button'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { DiagnosticsCheck, DiagnosticsStatus } from '@/api/types'

function StatusIcon({ status, className }: { status: DiagnosticsStatus; className?: string }) {
  if (status === 'ok')
    return <CheckCircle2 size={15} className={cn('text-(--color-success)', className)} aria-hidden="true" />
  if (status === 'warn')
    return <AlertTriangle size={15} className={cn('text-(--color-warning)', className)} aria-hidden="true" />
  return <XCircle size={15} className={cn('text-(--color-error)', className)} aria-hidden="true" />
}

const SUMMARY_COPY: Record<DiagnosticsStatus, { label: string; tone: 'success' | 'warning' | 'error' }> = {
  ok: { label: 'All systems responding', tone: 'success' },
  warn: { label: 'Some checks need attention', tone: 'warning' },
  fail: { label: 'One or more checks failed', tone: 'error' },
}

function CheckRow({ check, index }: { check: DiagnosticsCheck; index: number }) {
  const preset = useMotionPreset()
  return (
    <motion.div
      initial={{ y: 6 * preset.distance }}
      animate={{ y: 0 }}
      transition={{ ...preset.transition, delay: index * preset.stagger }}
      className={cn(
        'flex items-start gap-3 px-4 py-3.5',
        check.status === 'warn' && 'bg-(--color-warning)/6',
        check.status === 'fail' && 'bg-(--color-error)/6',
      )}
    >
      <StatusIcon status={check.status} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="text-sm text-(--color-text)">{check.label}</p>
        <p className="mt-0.5 text-xs leading-relaxed text-(--color-text-muted)">{check.detail}</p>
        {check.hint && (
          <p className="mt-1 text-xs leading-relaxed text-(--color-text-subtle)">{check.hint}</p>
        )}
      </div>
    </motion.div>
  )
}

export function DiagnosticsPage() {
  const { data, isLoading, isRefetching, error, refetch } = useDiagnosticsQuery()
  const summary = data ? SUMMARY_COPY[data.summary] : null

  return (
    <SettingsPage
      icon={Activity}
      title="Diagnostics"
      lede="Live health checks across every EvoFlux subsystem. Start here when a provider key, sandbox path or background job is misbehaving."
      size="wide"
      actions={
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
      }
    >
      <SettingsAsyncBoundary
        loading={isLoading || isRefetching}
        hasData={Boolean(data)}
        error={error}
        variant="diagnostics"
        loadingLabel="Running diagnostic checks"
        errorTitle="Could not reach the backend"
        onRetry={() => void refetch()}
      >
      {data && summary && (
        <>
          <SettingsCallout tone={summary.tone} icon={data.summary === 'ok' ? CheckCircle2 : AlertTriangle}>
            <span className="font-medium">{summary.label}</span>
            <span className="text-(--color-text-muted)">
              {' '}
              {data.checks.length} {data.checks.length === 1 ? 'check' : 'checks'} run
              {isRefetching ? ', refreshing' : ''}.
            </span>
          </SettingsCallout>

          <SettingsGroup title="Checks">
            {data.checks.map((check, index) => (
              <CheckRow key={check.id} check={check} index={index} />
            ))}
          </SettingsGroup>
        </>
      )}
      </SettingsAsyncBoundary>
    </SettingsPage>
  )
}
