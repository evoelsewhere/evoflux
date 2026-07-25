/**
 * SegmentedControl — small exclusive choice with a single indicator that
 * slides between options, so switching reads as one movement instead of two
 * separate highlights. The indicator follows the user's motion preset.
 */
import { motion } from 'framer-motion'

import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

export interface SegmentedOption<T extends string | number> {
  value: T
  label: string
  disabled?: boolean
}

export function SegmentedControl<T extends string | number>({
  options,
  value,
  onChange,
  /** Unique across the page: two controls may not share one indicator. */
  layoutId,
  ariaLabel,
  className,
}: {
  options: ReadonlyArray<SegmentedOption<T>>
  value: T
  onChange: (value: T) => void
  layoutId: string
  ariaLabel: string
  className?: string
}) {
  const preset = useMotionPreset()

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        'flex w-fit gap-0.5 rounded-md border border-(--color-border) bg-(--bg-key)/60 p-0.5',
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            disabled={option.disabled}
            onClick={() => {
              if (option.disabled) return
              onChange(option.value)
            }}
            className={cn(
              'relative rounded-[7px] px-2.5 py-1 text-xs transition-colors',
              active ? 'text-(--color-text)' : 'text-(--color-text-muted) hover:text-(--color-text)',
              option.disabled && 'cursor-not-allowed opacity-40',
            )}
          >
            {active && (
              <motion.span
                layoutId={layoutId}
                transition={preset.spring}
                className="absolute inset-0 rounded-[7px] bg-(--bg-card) shadow-sm"
                aria-hidden="true"
              />
            )}
            <span className="relative whitespace-nowrap">{option.label}</span>
          </button>
        )
      })}
    </div>
  )
}
