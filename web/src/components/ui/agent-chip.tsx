/**
 * AgentChip — pill that identifies an agent with its role-specific emblem.
 *
 * Visual structure (per `.diagrams/EvoFlux-ui.pen`, components
 * EvoFluxChip / ExecutorChip / ConsultantChip / ExplorerChip):
 *
 *   [emblem role]
 *
 * - compact role emblem with an optional overlaid status dot
 * - mono label
 * - rounded-md badge, padding 6×12, gap 8
 * - active variant: 1.2px border in role's marker color + bold (600) label in `--color-text`
 * - inactive variant: no border, 500-weight label in `--color-text-2`
 *
 * The chip is identity-only. For interactive variants pass an `onClick`
 * (the wrapper renders as a `<button>`); read-only variants render a `<span>`.
 */

import { cva, type VariantProps } from 'class-variance-authority'
import { AgentLogo } from '@/components/AgentLogo'
import { cn } from '@/lib/utils'
import type { AgentRole } from '@/lib/agent-roles'

const chipVariants = cva(
  'inline-flex items-center gap-2 rounded-md px-3 py-1.5 font-mono text-xs leading-none transition-[background-color,border-color,color,opacity,transform] duration-(--motion-fast) focus-ring-control press-control hover:bg-(--bg-key)/50',
  {
    variants: {
      role: {
        EvoFlux: '',
        executor: '',
        consultant: '',
        explorer: '',
        debate: '',
        coder: '',
        architect: '',
        custom: '',
      },
      active: {
        true: 'border font-semibold text-(--color-text)',
        false: 'border-transparent font-medium text-(--color-text-2)',
      },
    },
    compoundVariants: [
      // Lead is almost always active — mint border on mint dot reads
      // as visual noise. Foreground weight carries the active state.
      { role: 'EvoFlux', active: true, className: 'border-transparent' },
      { role: 'executor', active: true, className: 'border-(--color-marker-orange)' },
      { role: 'consultant', active: true, className: 'border-(--color-marker-blue)' },
      { role: 'explorer', active: true, className: 'border-(--color-text-muted)' },
      { role: 'debate', active: true, className: 'border-(--color-marker-pink)' },
      { role: 'coder', active: true, className: 'border-(--color-violet)' },
      { role: 'architect', active: true, className: 'border-(--color-marker-blue)' },
      { role: 'custom', active: true, className: 'border-(--color-border-strong)' },
    ],
    defaultVariants: {
      role: 'EvoFlux',
      active: false,
    },
  },
)

export interface AgentChipProps
  extends Omit<React.ComponentPropsWithoutRef<'button'>, 'role'>,
    VariantProps<typeof chipVariants> {
  role: AgentRole
  /** Optional override for the visible label (defaults to the role name). */
  label?: string
  /** Optional override of the dot color when an agent's status diverges from idle. */
  dotClassName?: string
}

export function AgentChip({
  role,
  active = false,
  label,
  dotClassName,
  className,
  onClick,
  ...rest
}: AgentChipProps) {
  const visibleLabel = label ?? role
  const content = (
    <>
      <AgentLogo
        name={visibleLabel}
        role={role === 'EvoFlux' ? 'lead' : 'member'}
        size="xs"
        statusClassName={dotClassName}
      />
      <span className="min-w-0 truncate">{visibleLabel}</span>
    </>
  )

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-pressed={Boolean(active)}
        className={cn(chipVariants({ role, active }), className)}
        {...rest}
      >
        {content}
      </button>
    )
  }

  return (
    <span className={cn(chipVariants({ role, active }), className)}>{content}</span>
  )
}
