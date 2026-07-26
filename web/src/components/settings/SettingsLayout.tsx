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
import { useId, type ReactNode } from 'react'
import { motion } from 'framer-motion'
import { ArrowLeft, type LucideIcon } from 'lucide-react'

import { useIsMobile } from '@/hooks/use-mobile'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

export type SettingsContentSize = 'narrow' | 'wide' | 'full'

const CONTENT_WIDTHS: Record<SettingsContentSize, string> = {
  narrow: 'max-w-3xl',
  wide: 'max-w-5xl',
  full: 'max-w-none',
}

export function SettingsPageHeader({
  icon: Icon,
  title,
  titleId,
  lede,
  actions,
}: {
  icon: LucideIcon
  title: string
  titleId?: string
  lede?: ReactNode
  actions?: ReactNode
}) {
  const isMobile = useIsMobile()
  const settingsNavigate = useSettingsNavigate()

  return (
    <header className="relative flex items-start gap-3 border-b border-(--color-border-subtle) pb-5 sm:gap-4 sm:pb-6">
      {isMobile && (
        <button
          type="button"
          onClick={() => settingsNavigate('/settings')}
          className="-ml-1 flex size-11 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) transition-[background-color,color,transform] duration-200 hover:bg-(--bg-key) hover:text-(--color-text) active:scale-[0.96] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)"
          aria-label="Back to settings"
        >
          <ArrowLeft size={18} />
        </button>
      )}
      <div className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-(--color-border) bg-(--bg-card) text-(--color-accent) shadow-[0_8px_24px_color-mix(in_srgb,var(--color-accent)_10%,transparent)] sm:size-11">
        <Icon size={19} aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1 pt-0.5">
        <h1
          id={titleId}
          className="text-balance text-xl font-semibold tracking-[-0.02em] text-(--color-text) sm:text-2xl"
        >
          {title}
        </h1>
        {lede && (
          <p className="mt-1.5 max-w-[62ch] text-sm leading-relaxed text-(--color-text-muted)">
            {lede}
          </p>
        )}
      </div>
      {actions && (
        <div className="settings-page-actions fixed inset-x-0 bottom-0 z-(--z-panel) flex min-h-16 items-center justify-end gap-2 border-t border-(--color-border) bg-(--bg-page)/95 px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 shadow-[0_-12px_32px_rgba(0,0,0,0.08)] backdrop-blur-md sm:static sm:z-auto sm:min-h-0 sm:shrink-0 sm:border-0 sm:bg-transparent sm:p-0 sm:shadow-none sm:backdrop-blur-none">
          {actions}
        </div>
      )}
    </header>
  )
}

export function SettingsPage({
  icon,
  title,
  actions,
  lede,
  size = 'narrow',
  children,
}: {
  icon: LucideIcon
  title: string
  actions?: ReactNode
  /** One sentence explaining what the page controls. */
  lede?: ReactNode
  size?: SettingsContentSize
  children: ReactNode
}) {
  const preset = useMotionPreset()
  const titleId = useId()

  return (
    <section
      role="region"
      aria-labelledby={titleId}
      data-settings-size={size}
      className="flex min-h-0 flex-1 flex-col"
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
        <motion.div
          initial={{ opacity: 0, y: 6 * preset.distance }}
          animate={{ opacity: 1, y: 0 }}
          transition={preset.transition}
          className={cn(
            'mx-auto w-full space-y-7 px-4 py-5 sm:px-7 sm:py-7',
            actions && 'pb-24 sm:pb-7',
            CONTENT_WIDTHS[size],
          )}
        >
          <SettingsPageHeader
            icon={icon}
            title={title}
            titleId={titleId}
            lede={lede}
            actions={actions}
          />
          {children}
        </motion.div>
      </div>
    </section>
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
            'divide-y divide-(--color-border-subtle) overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card) shadow-[0_10px_30px_rgba(0,0,0,0.025)]',
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
      <div className={cn('space-y-2.5 px-4 py-4', className)}>
        {text}
        {control ?? children}
      </div>
    )
  }

  return (
    <div className={cn('flex min-h-14 items-start gap-4 px-4 py-4', className)}>
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
