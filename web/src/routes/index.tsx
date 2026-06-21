import { motion } from 'framer-motion'
import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import EvoFluxAppIcon from '@/assets/brand/evoflux-app-icon.png'

import { AppBackendDialog } from '@/components/AppBackendDialog'
import { Activity, AlertCircle, Code2, Gauge, MessageSquare, Settings, Wifi } from 'lucide-react'
import { useHealthQuery } from '@/queries/useHealthQuery'
import { useTeamStatusQuery } from '@/queries/useTeamStatusQuery'
import { useTeamSessionsQuery } from '@/queries/useSessionsQuery'
import { usePlatform } from '@/hooks/use-platform'
import { useIsMobile } from '@/hooks/use-mobile'
import { useTauriDrag } from '@/hooks/use-tauri-drag'
import { useReducedMotion } from '@/hooks/useReducedMotion'

export function HomePage() {
  const navigate = useNavigate()
  const health = useHealthQuery()
  const team = useTeamStatusQuery()
  const sessions = useTeamSessionsQuery()
  const isMobile = useIsMobile()
  const { isMacOverlay, isTauri, os } = usePlatform()
  const isTauriMobile = isMobile && isTauri && (os === 'ios' || os === 'android')
  const dragHandlers = useTauriDrag()
  const prefersReducedMotion = useReducedMotion()
  const [backendDialogOpen, setBackendDialogOpen] = useState(false)

  const backendOk = health.isSuccess
  const hasTeam = team.isSuccess && team.data !== null
  const loading = health.isLoading || team.isLoading
  const error = health.isError

  const recentSessions = sessions.data?.pages
    .flatMap((p) => p.data)
    .slice(0, 5) ?? []

  return (
    <main id="main" className="mobile-safe-shell mobile-viewport flex h-dvh flex-col overflow-y-auto bg-(--bg-page)">
      {isMacOverlay && (
        <div
          {...dragHandlers}
          aria-hidden="true"
          className="fixed left-(--spacing-mac-traffic-inset) right-0 top-0 z-20 h-10 select-none"
        />
      )}
      <motion.div
        initial={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 24 }}
        animate={prefersReducedMotion ? { opacity: 1 } : { opacity: 1, y: 0 }}
        transition={{ duration: prefersReducedMotion ? 0.01 : 0.45, ease: 'easeOut' }}
        className="mx-auto flex w-full max-w-lg flex-1 flex-col px-6 pt-[max(3rem,env(safe-area-inset-top))] pb-[max(2rem,env(safe-area-inset-bottom))]"
      >
        {/* Logo + Title */}
        <div className="flex flex-col items-center gap-4 pb-8">
          <div className="relative">
            <div className="absolute inset-0 rounded-2xl bg-(--bg-key) blur-xl" />
            <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl bg-(--bg-key) ring-1 ring-(--color-border)">
              <img src={EvoFluxAppIcon} width={56} height={56} alt="EvoFlux" className="rounded-xl" />
            </div>
          </div>
          <div className="text-center">
            <h1 className="text-3xl font-bold tracking-tight text-(--color-text)">EvoFlux</h1>
            <p className="mt-1 text-sm text-(--color-text-muted)">Local AI agent platform</p>
          </div>
        </div>

        {/* Quick Actions */}
        <div className="grid grid-cols-2 gap-3 pb-6">
          <QuickAction
            icon={Gauge}
            label="Forge"
            sublabel={
              loading && !error
                ? 'Checking…'
                : hasTeam
                  ? `${[team.data!.lead, ...team.data!.members].length} agents`
                  : 'No team'
            }
            disabled={!backendOk || !hasTeam}
            loading={loading && !error}
            onClick={() => navigate({ to: '/forge' })}
          />
          <QuickAction
            icon={Code2}
            label="Coding"
            sublabel="Project workspace"
            disabled={!backendOk}
            loading={loading && !error}
            onClick={() => navigate({ to: '/coding' })}
          />
          <QuickAction
            icon={Activity}
            label="Telemetry"
            sublabel="Spans & latency"
            disabled={!backendOk}
            loading={loading && !error}
            onClick={() => navigate({ to: '/telemetry' })}
          />
          <QuickAction
            icon={Settings}
            label="Settings"
            sublabel="Agents, MCP, sandbox"
            disabled={!backendOk}
            loading={loading && !error}
            onClick={() => navigate({ to: '/settings' })}
          />
        </div>

        {/* Recent Sessions */}
        {recentSessions.length > 0 && (
          <div className="flex-1 overflow-y-auto">
            <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-(--color-text-muted)">Recent</h2>
            <div className="flex flex-col gap-1">
              {recentSessions.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => {
                    const route = s.mode === 'coding' ? '/coding/$sessionId' : '/forge/$sessionId'
                    navigate({ to: route, params: { sessionId: s.id } })
                  }}
                  className="group flex items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-(--bg-key)"
                >
                  <MessageSquare size={16} className="shrink-0 text-(--color-text-muted) group-hover:text-(--color-accent)" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-(--color-text)">{s.title || 'Untitled session'}</p>
                    <p className="truncate text-xs text-(--color-text-muted)">
                      {s.mode === 'coding' ? 'Coding' : 'Forge'}
                      {s.model ? ` · ${s.model.split(':').pop()}` : ''}
                    </p>
                  </div>
                  {s.running && (
                    <span className="h-2 w-2 shrink-0 rounded-full bg-(--color-success) animate-pulse" />
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Backend status */}
        <div className="mt-auto flex items-center justify-center gap-2 pt-4 text-xs">
          {loading && !error ? (
            <button
              type="button"
              onClick={() => setBackendDialogOpen(true)}
              className="flex items-center gap-2 rounded-md px-2 py-1 text-(--color-text-muted) transition-colors hover:bg-(--bg-key)"
            >
              <Wifi size={12} className="animate-pulse" />
              <span>Connecting…</span>
            </button>
          ) : error ? (
            <button
              type="button"
              onClick={() => setBackendDialogOpen(true)}
              className="flex items-center gap-2 rounded-md px-2 py-1 text-(--color-error) transition-colors hover:bg-(--color-error)/10"
            >
              <AlertCircle size={12} />
              <span>Backend unreachable</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setBackendDialogOpen(true)}
              className="flex items-center gap-2 rounded-md px-2 py-1 transition-colors hover:bg-(--bg-key)"
            >
              <Wifi size={12} className="text-(--color-success)" />
              <span className="text-(--color-text-muted)">Connected</span>
              <span className="text-(--color-text-subtle)">·</span>
              <span className="text-(--color-text-subtle)">Change server</span>
            </button>
          )}
        </div>
      </motion.div>
      <AppBackendDialog open={backendDialogOpen} onOpenChange={setBackendDialogOpen} />
    </main>
  )
}

function QuickAction({
  icon: Icon,
  label,
  sublabel,
  disabled,
  loading,
  onClick,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>
  label: string
  sublabel: string
  disabled: boolean
  loading: boolean
  onClick: () => void
}) {
  return (
    <motion.button
      whileHover={disabled ? {} : { scale: 1.02 }}
      whileTap={disabled ? {} : { scale: 0.98 }}
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      className={`flex flex-col items-start gap-2 rounded-xl border p-4 text-left transition-all ${
        disabled
          ? 'cursor-not-allowed border-(--border-soft) bg-(--bg-key) opacity-40'
          : 'border-(--border-soft) bg-(--bg-card) hover:border-(--color-border-strong) hover:shadow-sm'
      }`}
    >
      <Icon
        size={20}
        className={
          disabled
            ? 'text-(--color-text-muted)'
            : loading
              ? 'animate-pulse text-(--color-accent)'
              : 'text-(--color-accent)'
        }
      />
      <div>
        <p className="text-sm font-medium text-(--color-text)">{label}</p>
        <p className="text-xs text-(--color-text-muted)">{sublabel}</p>
      </div>
    </motion.button>
  )
}
