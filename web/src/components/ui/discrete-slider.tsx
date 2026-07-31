/**
 * DiscreteSlider — a stepped slider for enumerated settings.
 *
 * A native range input carries keyboard and screen-reader behaviour; the
 * visible rail, fill and thumb are painted on top and animate with the user's
 * motion preset. Only `transform` and `opacity` animate, so dragging stays on
 * the compositor.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'

import { softHapticFeedback } from '@/lib/haptics'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

const THUMB_WIDTH = 22

interface DiscreteSliderProps {
  label: string
  /** Short text for the current value, shown next to the label and in the bubble. */
  valueLabel: string
  index: number
  marks: ReadonlyArray<string>
  onChange: (index: number) => void
  /** Accent for fill and thumb. Any CSS color, defaults to the app accent. */
  color?: string
  /** Optional caption under the tick labels. */
  hint?: string
  className?: string
  compact?: boolean
}

export function DiscreteSlider({
  label,
  valueLabel,
  index,
  marks,
  onChange,
  color = 'var(--color-accent)',
  hint,
  className,
  compact = false,
}: DiscreteSliderProps) {
  const preset = useMotionPreset()
  const railRef = useRef<HTMLDivElement>(null)
  const [railWidth, setRailWidth] = useState(0)
  const [interacting, setInteracting] = useState(false)
  const [focused, setFocused] = useState(false)
  const [hovered, setHovered] = useState(false)

  const maxIndex = Math.max(0, marks.length - 1)
  const progress = maxIndex === 0 ? 0 : index / maxIndex

  useLayoutEffect(() => {
    const rail = railRef.current
    if (!rail) return
    const observer = new ResizeObserver(([entry]) => {
      setRailWidth(entry.contentRect.width)
    })
    observer.observe(rail)
    setRailWidth(rail.getBoundingClientRect().width)
    return () => observer.disconnect()
  }, [])

  const thumbWidth = compact ? 18 : THUMB_WIDTH
  const travel = Math.max(0, railWidth - thumbWidth)
  const thumbX = travel * progress

  const handleInput = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const next = Number(event.target.value)
      if (!Number.isFinite(next) || next === index) return
      softHapticFeedback()
      onChange(next)
    },
    [index, onChange],
  )

  // Pointer capture ends outside the element often enough that a window
  // listener is the reliable way to clear the dragging state.
  useEffect(() => {
    if (!interacting) return
    const stop = () => setInteracting(false)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
    return () => {
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
    }
  }, [interacting])

  const bubbleVisible = interacting || focused

  return (
    <div className={cn('select-none', className)}>
      <div className="flex items-baseline justify-between gap-3">
        <span className={cn('font-medium text-(--color-text)', compact ? 'text-xs' : 'text-sm')}>
          {label}
        </span>
        <span className={cn(
          'font-mono tabular-nums text-(--color-text-muted)',
          compact ? 'text-[10px]' : 'text-xs',
        )}>
          {valueLabel}
        </span>
      </div>

      <div className={cn('relative', compact ? 'mt-2 h-8' : 'mt-3 h-11')}>
        {/* Value bubble tracks the thumb while the control is active. */}
        <motion.div
          aria-hidden="true"
          className="pointer-events-none absolute -top-1 left-0 z-10 origin-bottom"
          animate={{ x: thumbX - 14, opacity: bubbleVisible ? 1 : 0, y: bubbleVisible ? 0 : 4 }}
          transition={preset.spring}
        >
          <span
            className="block rounded-md border border-(--color-border-strong) bg-(--color-surface) px-2 py-0.5 font-mono text-[11px] whitespace-nowrap text-(--color-text) shadow-sm"
            style={{ minWidth: 50, textAlign: 'center' }}
          >
            {valueLabel}
          </span>
        </motion.div>

        <div
          ref={railRef}
          className={cn(
            'absolute inset-x-0 top-1/2 -translate-y-1/2 overflow-hidden rounded-full bg-(--bg-key) ring-1 ring-inset ring-(--color-border)',
            compact ? 'h-2' : 'h-2.5',
          )}
        >
          <motion.div
            className="absolute inset-y-0 left-0 w-full rounded-full"
            style={{
              originX: 0,
              background: `linear-gradient(90deg, color-mix(in srgb, ${color} 35%, transparent), ${color})`,
            }}
            initial={false}
            animate={{ scaleX: Math.max(progress, 0.001) }}
            transition={preset.spring}
          />
        </div>

        {/* Ticks sit above the fill so the active step reads clearly. */}
        <div className="pointer-events-none absolute inset-x-0 top-1/2 flex -translate-y-1/2 items-center justify-between px-[9px]">
          {marks.map((mark, markIndex) => (
            <span
              key={mark}
              className="size-1 rounded-full transition-opacity"
              style={{
                backgroundColor: markIndex <= index ? 'var(--color-text-on-accent)' : 'var(--color-text-subtle)',
                opacity: markIndex === index ? 0 : markIndex < index ? 0.5 : 0.35,
              }}
            />
          ))}
        </div>

        <motion.div
          aria-hidden="true"
          className={cn(
            'pointer-events-none absolute top-1/2 left-0 flex items-center justify-center rounded-full border border-(--color-border-strong) bg-(--color-surface) shadow-[0_1px_3px_rgb(0_0_0/0.25)]',
            compact ? 'h-5' : 'h-6',
          )}
          style={{
            width: thumbWidth,
            y: '-50%',
            // Keyboard focus has to be visible on the painted thumb, since the
            // real input is transparent and cannot show its own ring.
            boxShadow: focused
              ? `0 1px 3px rgb(0 0 0 / 0.25), 0 0 0 3px color-mix(in srgb, ${color} 35%, transparent)`
              : undefined,
          }}
          initial={false}
          animate={{ x: thumbX, scale: interacting ? 1.12 : hovered ? 1.06 : 1 }}
          transition={preset.spring}
        >
          <span className="size-2 rounded-full" style={{ backgroundColor: color }} />
        </motion.div>

        <input
          type="range"
          min={0}
          max={maxIndex}
          step={1}
          value={index}
          aria-label={label}
          aria-valuetext={valueLabel}
          onChange={handleInput}
          onPointerDown={() => setInteracting(true)}
          onPointerEnter={() => setHovered(true)}
          onPointerLeave={() => setHovered(false)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          className="absolute inset-0 z-20 w-full cursor-pointer appearance-none bg-transparent opacity-0 outline-none"
        />
      </div>

      <div className={cn('flex justify-between gap-1', compact ? 'mt-0.5' : 'mt-1')}>
        {marks.map((mark, markIndex) => (
          <button
            key={mark}
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            onClick={() => onChange(markIndex)}
            className={cn(
              'min-w-0 flex-1 truncate rounded px-0.5 text-center font-mono transition-colors',
              compact ? 'text-[9px]' : 'text-[10px]',
              markIndex === index
                ? 'font-semibold text-(--color-text)'
                : 'text-(--color-text-subtle) hover:text-(--color-text-muted)',
            )}
          >
            {mark}
          </button>
        ))}
      </div>

      {hint && <p className="mt-2 text-xs leading-relaxed text-(--color-text-muted)">{hint}</p>}
    </div>
  )
}
