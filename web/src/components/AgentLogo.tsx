import {
  AGENT_IDENTITY_VISUALS,
  agentVisualKind,
} from '@/lib/agent-visuals'
import { cn } from '@/lib/utils'

export type AgentLogoSize = 'xs' | 'sm' | 'md' | 'lg'

const FRAME_SIZE: Record<AgentLogoSize, string> = {
  xs: 'size-[18px] rounded-[6px]',
  sm: 'size-8 rounded-lg',
  md: 'size-10 rounded-xl',
  lg: 'size-14 rounded-2xl',
}

const ICON_SIZE: Record<AgentLogoSize, number> = {
  xs: 10,
  sm: 14,
  md: 17,
  lg: 22,
}

const STATUS_SIZE: Record<AgentLogoSize, string> = {
  xs: 'size-1.5 -bottom-0.5 -right-0.5 ring-1',
  sm: 'size-2 bottom-0 right-0 ring-2',
  md: 'size-2.5 bottom-0 right-0 ring-2',
  lg: 'size-3 bottom-0.5 right-0.5 ring-2',
}

export function AgentLogo({
  name,
  role,
  size = 'sm',
  className,
  statusClassName,
}: {
  name: string
  role?: 'lead' | 'member'
  size?: AgentLogoSize
  className?: string
  statusClassName?: string
}) {
  const kind = agentVisualKind(name, role)
  const visual = AGENT_IDENTITY_VISUALS[kind]
  const Icon = visual.icon

  return (
    <span
      className={cn(
        'relative inline-flex shrink-0 items-center justify-center overflow-visible border shadow-[inset_0_1px_0_rgba(255,255,255,0.09),0_1px_2px_rgba(0,0,0,0.08)]',
        FRAME_SIZE[size],
        visual.soft,
        visual.border,
        visual.accent,
        className,
      )}
      title={visual.label}
      aria-hidden="true"
      data-agent-kind={kind}
    >
      <span className="pointer-events-none absolute inset-x-[22%] top-0 h-px bg-current opacity-25" />
      <Icon size={ICON_SIZE[size]} strokeWidth={1.85} />
      {statusClassName && (
        <span
          className={cn(
            'absolute rounded-full ring-(--bg-card)',
            STATUS_SIZE[size],
            statusClassName,
          )}
        />
      )}
    </span>
  )
}
