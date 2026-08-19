import { cn } from '@/lib/utils'

export function EnterpriseAttentionDot({
  label = 'Enterprise attention available',
  className,
  testId,
}: {
  label?: string
  className?: string
  testId?: string
}) {
  return (
    <span className={cn('inline-flex shrink-0 items-center', className)}>
      <span
        aria-hidden="true"
        data-testid={testId}
        className="size-2 rounded-full bg-(--color-warning)"
      />
      <span className="sr-only">{label}</span>
    </span>
  )
}
