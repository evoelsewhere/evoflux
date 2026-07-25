import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

interface ThinkingDotsProps {
  className?: string
  'aria-label'?: string
}

/**
 * Thinking indicator — three dots pulsing with a preset-scaled stagger.
 * Signals "the agent is reasoning but has not yet produced output".
 */
export function ThinkingDots({
  className,
  'aria-label': ariaLabel = 'Thinking',
}: ThinkingDotsProps) {
  const preset = useMotionPreset()
  const delays = [0, 1, 2].map((i) => i * Math.max(preset.stagger, 0.12) * 1000)

  return (
    <span
      className={cn('inline-flex items-center gap-1', className)}
      role="status"
      aria-label={ariaLabel}
    >
      {delays.map((delay, i) => (
        <span
          key={i}
          className="thinking-dot block h-1 w-1 rounded-full bg-current"
          style={
            preset.intensity === 'reduced'
              ? { opacity: 0.55 }
              : { animationDelay: `${delay}ms` }
          }
        />
      ))}
    </span>
  )
}
