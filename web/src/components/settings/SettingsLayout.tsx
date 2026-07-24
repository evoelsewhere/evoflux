/**
 * Settings design language.
 *
 * One page frame, grouped hairline lists instead of stacked cards, and a
 * single row shape (label + description on the left, control on the right).
 * Shape scale is fixed: containers `rounded-lg`, controls `rounded-md`,
 * status chips `rounded-full`.
 *
 * Every settings page composes these instead of hand-rolling headers and
 * card markup, so spacing, typography and motion stay identical across the
 * whole surface.
 */
import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import { ArrowLeft, type LucideIcon } from 'lucide-react'

import { useIsMobile } from '@/hooks/use-mobile'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

/**
 * The one settings header. Pages that need a full-bleed body (telemetry,
 * editors) render this directly instead of `SettingsPage`.
 */
export function SettingsPageHeader({
  icon: Icon,
  title,
  actions,
}: {
  icon: LucideIcon
  title: string
  actions?: ReactNode
}) {
  const isMobile = useIsMobile()
  const settingsNavigate = useSettingsNavigate()

  return (
    <header className="sticky top-0 z-(--z-panel) flex h-14 shrink-0 items-center gap-2.5 border-b border-(--color-border) bg-(--bg-page)/95 px-4 backdrop-blur-sm">
      {isMobile && (
        <button
          type="button"
          onClick={() => settingsNavigate('/settings')}
          className="-ml-1 flex size-11 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          aria-label="Back to settings"
        >
          <ArrowLeft size={16} />
        </button>
      )}
      <Icon size={15} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
      <h1 className="min-w-0 flex-1 truncate text-sm font-semibold text-(--color-text)">{title}</h1>
      {actions}
    </header>
  )
}

export function SettingsPage({
  icon,
  title,
  actions,
  lede,
  children,
}: {
  icon: LucideIcon
  title: string
  actions?: ReactNode
  /** One sentence explaining what the page controls. */
  lede?: ReactNode
  children: ReactNode
}) {
  const preset = useMotionPreset()

  return (
    <>
      <SettingsPageHeader icon={icon} title={title} actions={actions} />

      <div className="min-h-0 flex-1 overflow-y-auto">
        <motion.div
          initial={{ opacity: 0, y: 6 * preset.distance }}
          animate={{ opacity: 1, y: 0 }}
          transition={preset.transition}
          className="mx-auto max-w-2xl space-y-7 px-4 py-6 sm:px-6"
        >
          {lede && (
            <p className="max-w-[62ch] text-sm leading-relaxed text-(--color-text-muted)">{lede}</p>
          )}
          {children}
        </motion.div>
      </div>
    </>
  )
}

export function SettingsGroup({
  title,
  description,
  actions,
  /** Drop the surrounding surface when children bring their own containers. */
  bare = false,
  className,
  children,
}: {
  title?: string
  description?: ReactNode
  actions?: ReactNode
  bare?: boolean
  className?: string
  children: ReactNode
}) {
  return (
    <section className="space-y-2.5">
      {(title || actions) && (
        <div className="flex items-end justify-between gap-3 px-0.5">
          <div className="min-w-0">
            {title && <h2 className="text-[13px] font-semibold text-(--color-text)">{title}</h2>}
            {description && (
              <p className="mt-1 max-w-[58ch] text-xs leading-relaxed text-(--color-text-muted)">
                {description}
              </p>
            )}
          </div>
          {actions && <div className="shrink-0">{actions}</div>}
        </div>
      )}
      <div
        className={cn(
          !bare &&
            'divide-y divide-(--color-border-subtle) overflow-hidden rounded-lg border border-(--color-border) bg-(--bg-card)',
          className,
        )}
      >
        {children}
      </div>
    </section>
  )
}

export function SettingsRow({
  label,
  description,
  control,
  htmlFor,
  /** Stack the control under the text. Use for wide inputs and editors. */
  stacked = false,
  className,
  children,
}: {
  label?: ReactNode
  description?: ReactNode
  control?: ReactNode
  htmlFor?: string
  stacked?: boolean
  className?: string
  children?: ReactNode
}) {
  const text = (label || description) && (
    <div className="min-w-0 flex-1">
      {label && (
        <label
          htmlFor={htmlFor}
          className={cn('block text-sm text-(--color-text)', htmlFor && 'cursor-pointer')}
        >
          {label}
        </label>
      )}
      {description && (
        <p className="mt-1 max-w-[54ch] text-xs leading-relaxed text-(--color-text-muted)">
          {description}
        </p>
      )}
    </div>
  )

  if (stacked) {
    return (
      <div className={cn('space-y-2.5 px-4 py-3.5', className)}>
        {text}
        {control ?? children}
      </div>
    )
  }

  return (
    <div className={cn('flex items-start gap-4 px-4 py-3.5', className)}>
      {text}
      {(control || children) && (
        <div className="flex shrink-0 items-center gap-2 pt-0.5">{control ?? children}</div>
      )}
    </div>
  )
}

const CALLOUT_TONES = {
  info: 'border-(--color-border) bg-(--bg-key)/60 text-(--color-text-muted)',
  success: 'border-(--color-success)/25 bg-(--color-success)/8 text-(--color-text)',
  warning: 'border-(--color-warning)/25 bg-(--color-warning)/8 text-(--color-text)',
  error: 'border-(--color-error)/25 bg-(--color-error)/8 text-(--color-text)',
} as const

export function SettingsCallout({
  tone = 'info',
  icon: Icon,
  children,
  className,
}: {
  tone?: keyof typeof CALLOUT_TONES
  icon?: LucideIcon
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex items-start gap-2.5 rounded-lg border px-3.5 py-3 text-xs leading-relaxed',
        CALLOUT_TONES[tone],
        className,
      )}
      role={tone === 'error' ? 'alert' : undefined}
    >
      {Icon && <Icon size={14} className="mt-px shrink-0" aria-hidden="true" />}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}
