import { motion } from 'framer-motion'
import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import EvoFluxAppIcon from '@/assets/brand/evoflux-app-icon.png'

import { AppBackendDialog } from '@/components/AppBackendDialog'
import {
  Activity, AlertCircle, Bot, CheckCircle2, ChevronRight, Code2, Cog, Gauge,
  Globe, MessageSquare, Plug, Settings, Terminal, Wifi, XCircle, Clock,
} from 'lucide-react'
import { useHealthQuery } from '@/queries/useHealthQuery'
import { useTeamStatusQuery } from '@/queries/useTeamStatusQuery'
import { useTeamSessionsQuery } from '@/queries/useSessionsQuery'
import { useMcpServersQuery } from '@/queries/useMcpQuery'
import { useScheduledTasksQuery } from '@/queries/useSchedulerQuery'
import { useObservabilitySummaryQuery } from '@/queries/useObservabilitySummaryQuery'
import { usePlatform } from '@/hooks/use-platform'
import { useIsMobile } from '@/hooks/use-mobile'
import { useTauriDrag } from '@/hooks/use-tauri-drag'
import { useReducedMotion } from '@/hooks/useReducedMotion'

export function HomePage() {
  const navigate = useNavigate()
  const health = useHealthQuery()
  const team = useTeamStatusQuery()
  const sessions = useTeamSessionsQuery()
  const mcp = useMcpServersQuery()
  const tasks = useScheduledTasksQuery()
  const obs = useObservabilitySummaryQuery(7)
  const isMobile = useIsMobile()
  const { isMacOverlay, isTauri, os } = usePlatform()
  const dragHandlers = useTauriDrag()
  const prefersReducedMotion = useReducedMotion()
  const [backendDialogOpen, setBackendDialogOpen] = useState(false)

  const backendOk = health.isSuccess
  const hasTeam = team.isSuccess && team.data !== null
  const loading = health.isLoading || team.isLoading
  const error = health.isError

  const recentSessions = sessions.data?.pages
    .flatMap((p) => p.data)
    .slice(0, 8) ?? []

  const mcpServers = mcp.data?.servers ?? []
  const scheduledTasks = tasks.data?.tasks ?? []
  const activeTasks = scheduledTasks.filter((t) => t.enabled)
  const summary = obs.data

  return (
    <main id="main" className="mobile-safe-shell mobile-viewport flex h-dvh flex-col overflow-y-auto bg-(--bg-page)">
      {isMacOverlay && (
        <div {...dragHandlers} aria-hidden="true" className="fixed left-(--spacing-mac-traffic-inset) right-0 top-0 z-20 h-10 select-none" />
      )}
      <motion.div
        initial={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 16 }}
        animate={prefersReducedMotion ? { opacity: 1 } : { opacity: 1, y: 0 }}
        transition={{ duration: prefersReducedMotion ? 0.01 : 0.35, ease: 'easeOut' }}
        className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-8 pt-[max(2.5rem,env(safe-area-inset-top))] pb-[max(2rem,env(safe-area-inset-bottom))]"
      >
        {/* Header */}
        <div className="flex items-center gap-4">
          <div className="relative flex h-12 w-12 shrink-0 items-center justify-center">
            <img src={EvoFluxAppIcon} width={40} height={40} alt="EvoFlux" className="rounded-lg" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-bold tracking-tight text-(--color-text)">EvoFlux</h1>
            <p className="text-xs text-(--color-text-muted)">Local AI agent platform</p>
          </div>
          <BackendBadge
            loading={loading && !error}
            error={!!error}
            onClick={() => setBackendDialogOpen(true)}
          />
        </div>

        {/* Quick Actions */}
        <div className="grid grid-cols-4 gap-3">
          <QuickAction
            icon={Gauge}
            label="Forge"
            disabled={!backendOk || !hasTeam}
            loading={loading && !error}
            onClick={() => navigate({ to: '/forge' })}
          />
          <QuickAction
            icon={Code2}
            label="Coding"
            disabled={!backendOk}
            loading={loading && !error}
            onClick={() => navigate({ to: '/coding' })}
          />
          <QuickAction
            icon={Activity}
            label="Telemetry"
            disabled={!backendOk}
            loading={loading && !error}
            onClick={() => navigate({ to: '/telemetry' })}
          />
          <QuickAction
            icon={Settings}
            label="Settings"
            disabled={!backendOk}
            loading={loading && !error}
            onClick={() => navigate({ to: '/settings' })}
          />
        </div>

        {/* Two-column layout */}
        <div className="grid min-h-0 flex-1 grid-cols-2 gap-6 overflow-hidden">
          {/* Left: Sessions */}
          <section className="flex min-h-0 flex-col">
            <SectionHeader icon={MessageSquare} title="Recent Sessions" count={recentSessions.length} />
            <div className="flex-1 overflow-y-auto -mx-2 px-2">
              {recentSessions.length === 0 ? (
                <EmptyState text="No sessions yet" />
              ) : (
                <div className="flex flex-col gap-0.5">
                  {recentSessions.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => {
                        const route = s.mode === 'coding' ? '/coding/$sessionId' : '/forge/$sessionId'
                        navigate({ to: route, params: { sessionId: s.id } })
                      }}
                      className="group flex items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-(--bg-key)"
                    >
                      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-(--bg-key)">
                        {s.mode === 'coding'
                          ? <Code2 size={14} className="text-(--color-text-muted)" />
                          : <MessageSquare size={14} className="text-(--color-text-muted)" />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm text-(--color-text)">{s.title || 'Untitled'}</p>
                        <p className="truncate text-[11px] text-(--color-text-muted)">
                          {s.mode === 'coding' ? 'Coding' : 'Forge'}
                          {s.model ? ` · ${s.model.split(':').pop()}` : ''}
                          {s.updated_at ? ` · ${formatRelativeTime(s.updated_at)}` : ''}
                        </p>
                      </div>
                      {s.running && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-(--color-success) animate-pulse" />}
                      <ChevronRight size={14} className="shrink-0 text-(--color-text-subtle) opacity-0 transition-opacity group-hover:opacity-100" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </section>

          {/* Right: Status panels */}
          <section className="flex min-h-0 flex-col gap-4 overflow-y-auto">
            {/* Team */}
            {hasTeam && (
              <div>
                <SectionHeader icon={Bot} title="Team" />
                <div className="flex flex-col gap-1">
                  <AgentRow agent={team.data!.lead} isLead />
                  {team.data!.members.map((m) => (
                    <AgentRow key={m.name} agent={m} />
                  ))}
                </div>
              </div>
            )}

            {/* MCP Servers */}
            <div>
              <SectionHeader icon={Plug} title="MCP Servers" count={mcpServers.length} />
              {mcpServers.length === 0 ? (
                <EmptyState text="No MCP servers configured" />
              ) : (
                <div className="flex flex-col gap-1">
                  {mcpServers.map((s) => (
                    <div key={s.name} className="flex items-center gap-2.5 rounded-lg px-3 py-2">
                      <StateDot state={s.state} />
                      <span className="min-w-0 flex-1 truncate text-sm text-(--color-text)">{s.name}</span>
                      <span className="shrink-0 font-mono text-[10px] text-(--color-text-muted)">{s.tool_names.length} tools</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Scheduled Tasks */}
            <div>
              <SectionHeader icon={Clock} title="Scheduled Tasks" count={activeTasks.length} />
              {scheduledTasks.length === 0 ? (
                <EmptyState text="No scheduled tasks" />
              ) : (
                <div className="flex flex-col gap-1">
                  {scheduledTasks.slice(0, 5).map((t) => (
                    <div key={t.name} className="flex items-center gap-2.5 rounded-lg px-3 py-2">
                      <StateDot state={t.enabled ? 'ready' : 'stopped'} />
                      <span className="min-w-0 flex-1 truncate text-sm text-(--color-text)">{t.name}</span>
                      <span className="shrink-0 font-mono text-[10px] text-(--color-text-muted)">{t.schedule_type}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Observability Summary */}
            {summary && (
              <div>
                <SectionHeader icon={Activity} title="7-Day Activity" />
                <div className="grid grid-cols-3 gap-2">
                  <StatCard label="Turns" value={summary.totals.turns} />
                  <StatCard label="Tokens" value={formatCompactNumber(summary.totals.input_tokens + summary.totals.output_tokens)} />
                  <StatCard label="LLM p50" value={`${Math.round(summary.latency_ms.llm_p50)}ms`} />
                </div>
              </div>
            )}
          </section>
        </div>
      </motion.div>
      <AppBackendDialog open={backendDialogOpen} onOpenChange={setBackendDialogOpen} />
    </main>
  )
}

/* ── Sub-components ────────────────────────────────────────── */

function BackendBadge({ loading, error, onClick }: { loading: boolean; error: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] transition-colors ${
        error
          ? 'bg-(--color-error-subtle) text-(--color-error)'
          : loading
            ? 'bg-(--bg-key) text-(--color-text-muted)'
            : 'bg-(--bg-key) text-(--color-text-muted) hover:bg-(--color-border)'
      }`}
    >
      {error ? <XCircle size={12} /> : loading ? <Wifi size={12} className="animate-pulse" /> : <CheckCircle2 size={12} className="text-(--color-success)" />}
      <span>{error ? 'Offline' : loading ? 'Connecting' : 'Connected'}</span>
    </button>
  )
}

function QuickAction({
  icon: Icon, label, disabled, loading, onClick,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>
  label: string
  disabled: boolean
  loading: boolean
  onClick: () => void
}) {
  return (
    <motion.button
      whileHover={disabled ? {} : { scale: 1.03 }}
      whileTap={disabled ? {} : { scale: 0.97 }}
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      className={`flex flex-col items-center gap-1.5 rounded-xl border px-3 py-3 text-center transition-all ${
        disabled
          ? 'cursor-not-allowed border-(--border-soft) bg-(--bg-key) opacity-40'
          : 'border-(--border-soft) bg-(--bg-card) hover:border-(--color-border-strong) hover:shadow-sm'
      }`}
    >
      <Icon size={18} className={disabled ? 'text-(--color-text-muted)' : loading ? 'animate-pulse text-(--color-accent)' : 'text-(--color-accent)'} />
      <span className="text-xs font-medium text-(--color-text)">{label}</span>
    </motion.button>
  )
}

function SectionHeader({ icon: Icon, title, count }: { icon: React.ComponentType<{ size?: number; className?: string }>; title: string; count?: number }) {
  return (
    <div className="mb-2 flex items-center gap-2">
      <Icon size={14} className="text-(--color-text-muted)" />
      <h2 className="text-xs font-medium uppercase tracking-wider text-(--color-text-muted)">{title}</h2>
      {count !== undefined && count > 0 && (
        <span className="rounded-full bg-(--bg-key) px-1.5 py-0.5 font-mono text-[10px] text-(--color-text-muted)">{count}</span>
      )}
    </div>
  )
}

function AgentRow({ agent, isLead = false }: { agent: { name: string; model: string; state: string }; isLead?: boolean }) {
  return (
    <div className="flex items-center gap-2.5 rounded-lg px-3 py-2">
      <div className={`flex h-6 w-6 items-center justify-center rounded-md text-[10px] font-bold ${isLead ? 'bg-(--accent-green-soft) text-(--accent-green-text)' : 'bg-(--bg-key) text-(--color-text-muted)'}`}>
        {agent.name.charAt(0).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-(--color-text)">{agent.name}{isLead ? ' (lead)' : ''}</p>
        <p className="truncate text-[11px] text-(--color-text-muted)">{agent.model}</p>
      </div>
      <StateDot state={agent.state} />
    </div>
  )
}

function StateDot({ state }: { state: string }) {
  const color = state === 'ready' || state === 'running'
    ? 'bg-(--color-success)'
    : state === 'error' || state === 'failed'
      ? 'bg-(--color-error)'
      : state === 'starting' || state === 'auth_required'
        ? 'bg-(--color-warning)'
        : 'bg-(--color-text-subtle)'
  return <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${color}`} />
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-(--border-soft) bg-(--bg-card) px-3 py-2">
      <p className="font-mono text-base font-semibold text-(--color-text)">{value}</p>
      <p className="text-[10px] text-(--color-text-muted)">{label}</p>
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return <p className="py-4 text-center text-xs text-(--color-text-subtle)">{text}</p>
}

/* ── Helpers ───────────────────────────────────────────────── */

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function formatCompactNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}
