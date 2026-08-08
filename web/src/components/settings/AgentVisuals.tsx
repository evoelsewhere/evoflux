import {
  Bot,
  CheckCircle2,
  Crown,
  RefreshCw,
} from 'lucide-react'

import { AgentLogo } from '@/components/AgentLogo'
import { ProviderBrandIcon } from '@/components/providers/ProviderBrandIcon'
import {
  AGENT_TEAM_VISUALS,
  type AgentTeam,
} from '@/lib/agent-visuals'
import { providerOf, shortModelName } from '@/lib/model-settings'
import { cn } from '@/lib/utils'

export function AgentGlyph({
  name,
  role,
  size = 'md',
  className,
}: {
  name: string
  role: 'lead' | 'member'
  size?: 'sm' | 'md' | 'lg'
  className?: string
}) {
  return <AgentLogo name={name} role={role} size={size} className={className} />
}

export function AgentTeamBadge({ team }: { team: AgentTeam }) {
  const visual = AGENT_TEAM_VISUALS[team]
  const Icon = visual.icon
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center gap-1.5 rounded-full border px-2 text-[10px] font-semibold tracking-[0.04em] uppercase',
        visual.soft,
        visual.border,
        visual.accent,
      )}
    >
      <Icon size={10} aria-hidden="true" />
      {visual.label}
    </span>
  )
}

export function AgentRoleBadge({ role }: { role: 'lead' | 'member' }) {
  return (
    <span
      className={cn(
        'inline-flex h-6 items-center gap-1 rounded-full border px-2 text-[10px] font-medium capitalize',
        role === 'lead'
          ? 'border-(--color-warning)/25 bg-(--color-warning-subtle) text-(--color-warning)'
          : 'border-(--color-border) bg-(--bg-key)/55 text-(--color-text-muted)',
      )}
    >
      {role === 'lead' ? <Crown size={10} aria-hidden="true" /> : <Bot size={10} aria-hidden="true" />}
      {role}
    </span>
  )
}

export function AgentModelBadge({ model }: { model: string | null | undefined }) {
  if (!model) {
    return (
      <span className="inline-flex h-7 items-center gap-1.5 rounded-lg border border-(--color-warning)/25 bg-(--color-warning-subtle) px-2 text-[11px] text-(--color-warning)">
        <RefreshCw size={11} aria-hidden="true" />
        Model not set
      </span>
    )
  }

  return (
    <span
      className="inline-flex h-7 min-w-0 items-center gap-1.5 rounded-lg border border-(--color-border) bg-(--bg-input) px-1.5 pr-2 text-[11px] text-(--color-text-2)"
      title={model}
    >
      <ProviderBrandIcon providerId={model} size="xs" className="scale-75" />
      <span className="max-w-44 truncate font-medium">{shortModelName(model)}</span>
      <span className="hidden font-mono text-[9px] tracking-wide text-(--color-text-subtle) uppercase sm:inline">
        {providerOf(model)}
      </span>
    </span>
  )
}

export function AgentReadyBadge({ valid }: { valid: boolean }) {
  return valid ? (
    <span className="inline-flex items-center gap-1 text-[11px] text-(--color-success)">
      <CheckCircle2 size={12} aria-hidden="true" />
      Ready
    </span>
  ) : null
}
