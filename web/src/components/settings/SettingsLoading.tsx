import { useEffect, useState, type ReactNode } from 'react'
import { AlertCircle, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

export type SettingsSkeletonVariant =
  | 'list'
  | 'detail'
  | 'cards'
  | 'diagnostics'
  | 'telemetry'

function ListSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex h-11 items-center gap-3 rounded-xl border border-(--color-border-subtle) bg-(--bg-card)/80 px-4">
        <Skeleton className="size-4 shrink-0 rounded-full" />
        <Skeleton className="h-3.5 w-36" />
        <Skeleton className="ml-auto h-3 w-14" />
      </div>
      <div className="overflow-hidden rounded-xl border border-(--color-border-subtle) bg-(--bg-card)/80">
        {Array.from({ length: 6 }, (_, index) => (
          <div
            key={index}
            className="flex min-h-16 items-center gap-3 border-b border-(--color-border-subtle) px-4 last:border-b-0"
          >
            <Skeleton className="size-9 shrink-0 rounded-lg" />
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className={cn('h-3.5', index % 2 === 0 ? 'w-36' : 'w-44')} />
              <Skeleton className={cn('h-3', index % 3 === 0 ? 'w-56' : 'w-44')} />
            </div>
            <Skeleton className="h-6 w-14 shrink-0 rounded-full" />
          </div>
        ))}
      </div>
    </div>
  )
}

function DetailSkeleton() {
  return (
    <div className="space-y-7">
      {Array.from({ length: 3 }, (_, groupIndex) => (
        <section key={groupIndex} className="space-y-3">
          <div className="space-y-2 px-0.5">
            <Skeleton className="h-3.5 w-28" />
            <Skeleton className="h-3 w-64 max-w-[78%]" />
          </div>
          <div className="overflow-hidden rounded-xl border border-(--color-border-subtle) bg-(--bg-card)/80">
            {Array.from({ length: 2 }, (_, rowIndex) => (
              <div
                key={rowIndex}
                className="flex min-h-20 items-center gap-6 border-b border-(--color-border-subtle) px-4 py-4 last:border-b-0"
              >
                <div className="min-w-0 flex-1 space-y-2">
                  <Skeleton className="h-3.5 w-32" />
                  <Skeleton className="h-3 w-52 max-w-full" />
                </div>
                <Skeleton className="h-10 w-40 max-w-[42%]" />
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

function CardsSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex h-11 items-center gap-3 rounded-xl border border-(--color-border-subtle) bg-(--bg-card)/80 px-4">
        <Skeleton className="size-4 shrink-0 rounded-full" />
        <Skeleton className="h-3.5 w-40" />
        <Skeleton className="ml-auto h-3 w-20" />
      </div>
      <div className="space-y-3">
        <Skeleton className="h-3.5 w-24" />
        {Array.from({ length: 3 }, (_, index) => (
          <div
            key={index}
            className="flex min-h-20 items-center gap-4 rounded-xl border border-(--color-border-subtle) bg-(--bg-card)/80 px-4 py-3.5"
          >
            <Skeleton className="size-11 shrink-0 rounded-xl" />
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-64 max-w-[85%]" />
            </div>
            <Skeleton className="h-7 w-20 shrink-0 rounded-full" />
            <Skeleton className="size-8 shrink-0 rounded-lg" />
          </div>
        ))}
      </div>
    </div>
  )
}

function DiagnosticsSkeleton() {
  return (
    <div className="overflow-hidden rounded-xl border border-(--color-border-subtle) bg-(--bg-card)/80">
      {Array.from({ length: 5 }, (_, index) => (
        <div
          key={index}
          className="flex min-h-16 items-center gap-3 border-b border-(--color-border-subtle) px-4 last:border-b-0"
        >
          <Skeleton className="size-8 shrink-0 rounded-lg" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-36" />
            <Skeleton className="h-3 w-56 max-w-[75%]" />
          </div>
        </div>
      ))}
    </div>
  )
}

function TelemetrySkeleton() {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div
            key={index}
            className="space-y-3 rounded-xl border border-(--color-border-subtle) bg-(--bg-card)/80 p-4"
          >
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-7 w-24" />
          </div>
        ))}
      </div>
      <Skeleton className="h-48 w-full rounded-xl" />
      <div className="space-y-2 rounded-xl border border-(--color-border-subtle) bg-(--bg-card)/80 p-4">
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-8 w-full" />
        ))}
      </div>
    </div>
  )
}

const SKELETONS: Record<SettingsSkeletonVariant, () => ReactNode> = {
  list: ListSkeleton,
  detail: DetailSkeleton,
  cards: CardsSkeleton,
  diagnostics: DiagnosticsSkeleton,
  telemetry: TelemetrySkeleton,
}

export function SettingsLoadingState({
  variant,
  label,
  delayMs = 120,
}: {
  variant: SettingsSkeletonVariant
  label: string
  delayMs?: number
}) {
  const [visible, setVisible] = useState(delayMs <= 0)

  useEffect(() => {
    if (delayMs <= 0) return undefined
    const timeout = window.setTimeout(() => setVisible(true), delayMs)
    return () => window.clearTimeout(timeout)
  }, [delayMs])

  if (!visible) return null

  const Geometry = SKELETONS[variant]
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={label}
      className="settings-loading-enter"
      data-settings-loading={variant}
    >
      <span className="sr-only">{label}</span>
      <div aria-hidden="true">
        <Geometry />
      </div>
    </div>
  )
}

export function SettingsAsyncBoundary({
  loading,
  hasData,
  error,
  variant,
  loadingLabel,
  errorTitle,
  onRetry,
  children,
}: {
  loading: boolean
  hasData: boolean
  error?: unknown
  variant: SettingsSkeletonVariant
  loadingLabel: string
  errorTitle: string
  onRetry?: () => void
  children: ReactNode
}) {
  if (!hasData && loading) {
    return <SettingsLoadingState variant={variant} label={loadingLabel} />
  }

  if (!hasData && error) {
    const message = error instanceof Error ? error.message : String(error)
    return (
      <div
        role="alert"
        className="flex items-start gap-3 rounded-xl border border-(--color-error)/30 bg-(--color-error)/8 px-4 py-4 text-sm text-(--color-text)"
      >
        <AlertCircle
          size={17}
          className="mt-0.5 shrink-0 text-(--color-error)"
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{errorTitle}</p>
          <p className="mt-1 text-xs leading-relaxed text-(--color-text-muted)">{message}</p>
          {onRetry && (
            <Button size="sm" variant="outline" className="mt-3" onClick={onRetry}>
              <RefreshCw size={13} aria-hidden="true" />
              Try again
            </Button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div aria-busy={loading ? 'true' : 'false'} className="contents">
      {loading && (
        <span role="status" aria-live="polite" className="sr-only">
          {loadingLabel}
        </span>
      )}
      {children}
    </div>
  )
}
