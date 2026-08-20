import { Building2 } from 'lucide-react'

import type { ManagedResourceProvider } from '@/api/types'
import {
  CONDUCTOR_RESOURCE_STATE,
  CONDUCTOR_RESOURCE_STATE_LABEL,
} from '@/lib/conductor-constants'
import { cn } from '@/lib/utils'

const ATTENTION_STATES = new Set<ManagedResourceProvider['observed_state']>([
  CONDUCTOR_RESOURCE_STATE.ERROR,
  CONDUCTOR_RESOURCE_STATE.INCOMPATIBLE,
  CONDUCTOR_RESOURCE_STATE.OWNERSHIP_CONFLICT,
  CONDUCTOR_RESOURCE_STATE.PROJECT_SCOPE_MISMATCH,
  CONDUCTOR_RESOURCE_STATE.UPDATE_PENDING,
])

export function ManagedResourceProviderBadge({
  provider,
  className,
  showState = false,
}: {
  provider: ManagedResourceProvider
  className?: string
  showState?: boolean
}) {
  const stateLabel = CONDUCTOR_RESOURCE_STATE_LABEL[provider.observed_state]
  const version = provider.applied_version ? ` · installed v${provider.applied_version}` : ''
  const desiredVersion =
    provider.version && provider.version !== provider.applied_version
      ? ` → desired v${provider.version}`
      : ''
  const channel = provider.release_channel ? ` · ${provider.release_channel}` : ''
  const modes = provider.modes?.length ? ` · ${provider.modes.join(' + ')}` : ''
  const title = `${provider.project_name}${version}${desiredVersion}${channel}${modes} · ${stateLabel}`
  const attention = ATTENTION_STATES.has(provider.observed_state)

  return (
    <span
      title={title}
      className={cn(
        'inline-flex min-w-0 max-w-52 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ring-1',
        attention
          ? 'bg-amber-500/10 text-amber-600 ring-amber-500/25 dark:text-amber-400'
          : 'bg-(--color-accent-soft) text-(--color-accent) ring-(--color-accent)/20',
        className,
      )}
    >
      <Building2 size={10} className="shrink-0" aria-hidden="true" />
      <span className="truncate">provider: {provider.project_name}</span>
      {provider.applied_version && (
        <span className="shrink-0 border-l border-current/20 pl-1.5 font-mono">
          v{provider.applied_version}
        </span>
      )}
      {showState ? (
        <span className="shrink-0 border-l border-current/20 pl-1.5">{stateLabel}</span>
      ) : attention ? (
        <span className="size-1.5 shrink-0 rounded-full bg-current" aria-label={stateLabel} />
      ) : null}
    </span>
  )
}
