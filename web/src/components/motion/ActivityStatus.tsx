import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

interface ActivityStatusProps {
  label?: string
  className?: string
  'aria-label'?: string
}

/** Quiet Codex-style status text with a reduced-motion-safe light sweep. */
export function ActivityStatus({
  label = 'Thinking',
  className,
  'aria-label': ariaLabel = label,
}: ActivityStatusProps) {
  const preset = useMotionPreset()
  return (
    <span
      className={cn(
        'inline-block select-none text-sm font-medium text-(--color-text-muted)',
        preset.intensity !== 'reduced' && 'activity-text-shimmer',
        className,
      )}
      role="status"
      aria-label={ariaLabel}
    >
      {label}
    </span>
  )
}
