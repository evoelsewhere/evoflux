/**
 * ChatTopbar — the team chat header strip (extracted from TeamChatView).
 *
 * Owns the full <header> chrome: mobile hamburger + title, the desktop
 * ``ActiveAgentSwitcher`` dropdown, ``LoopStatusPill``,
 * ``WorkflowProgressPill``, coding-only ``TaskProgressPill``,
 * ``SessionTOC`` and the ``AgentTopbar`` right cluster with its action
 * descriptors. Props-driven — TeamChatView passes everything it needs.
 *
 * The Tauri drag handlers are spread onto the <header> by the caller
 * (see ``useTauriDrag``); ``data-no-drag`` on the interactive controls
 * opts them out of the window-drag guard.
 */
import { AnimatePresence, motion } from 'framer-motion'
import { BookOpen, Brain, CalendarClock, Check, ChevronDown, FolderOpen, Menu, Minimize2, MoreHorizontal, Terminal, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { TokenMeter } from '@/components/ui/token-meter'
import { TopbarAction } from '@/components/ui/topbar-action'
import { AgentTopbar, type AgentTopbarTokens } from '@/components/AgentTopbar'
import { TaskProgressPill } from '@/components/TaskProgressPill'
import { WorkflowProgressPill } from '@/components/WorkflowProgressPill'
import { SessionTOC } from '@/components/SessionTOC'
import { SessionScheduleIndicator } from '@/components/SessionScheduleIndicator'
import { WebBridgeBrowserInfo } from '@/components/shell/WebBridgeBrowserInfo'
import { isAgentRole, type AgentRole } from '@/lib/agent-roles'
import type { ActiveLoop, ActiveWorkflowExecution, AgentStream } from '@/stores/useTeamStore/types'
import type { Chapter } from '@/api/types'
import type { ViewMode } from '@/components/TeamChatView/types'

type AgentStatus = AgentStream['status']

/** Matches the return shape of ``useTauriDrag`` (no-op `{}` outside Tauri). */
interface DragHandlers {
  onMouseDown?: (event: React.MouseEvent<HTMLElement>) => void
}

interface ChatTopbarProps {
  dragHandlers: DragHandlers
  isMacOverlay: boolean
  isMobile: boolean
  mode: 'forge' | 'coding' | 'aim'
  workspace: string | null
  sessionId: string | null
  sessionTitle: string | null
  sessionTags?: string[] | null
  codingIdentityLabel: string | null
  activeAgent: string | null
  agentNames: string[]
  agentStatuses: Record<string, AgentStatus | undefined>
  onSelectAgent: (agent: string) => void
  effectiveViewMode: ViewMode
  viewMode: ViewMode
  onViewModeChange: (mode: ViewMode) => void
  activeLoop: ActiveLoop | null
  activeWorkflowExecution: ActiveWorkflowExecution | null
  onDismissWorkflowFailed: () => void
  isTeamWorking: boolean
  chapters: Chapter[]
  splitAgentCount: number
  headerTokens: AgentTopbarTokens | undefined
  contextUsed: number
  contextWindowSize: number | undefined
  summaryTriggerTokens: number | undefined
  dreamRunning: boolean
  terminalOpen: boolean
  onToggleTerminal: () => void
  onOpenScheduler: () => void
  onOpenMobileSidebar: () => void
  onCodingSidebarToggle: () => void
  codingPanelOpen: boolean
  showFilesPanel: boolean
  onWorkspaceFiles: () => void
  onToggleFilesPanel: () => void
  mobileActionsOpen: boolean
  onMobileActionsOpenChange: (open: boolean) => void
  onWiki: () => void
  wikiActive?: boolean
  onScheduler: () => void
  onCompact: () => void
}

export function ChatTopbar({
  dragHandlers,
  isMacOverlay,
  isMobile,
  mode,
  workspace,
  sessionId,
  sessionTitle,
  sessionTags,
  codingIdentityLabel,
  activeAgent,
  agentNames,
  agentStatuses,
  onSelectAgent,
  effectiveViewMode,
  viewMode,
  onViewModeChange,
  activeLoop,
  activeWorkflowExecution,
  onDismissWorkflowFailed,
  isTeamWorking,
  chapters,
  splitAgentCount,
  headerTokens,
  contextUsed,
  contextWindowSize,
  dreamRunning,
  terminalOpen,
  onToggleTerminal,
  onOpenScheduler,
  onOpenMobileSidebar,
  onCodingSidebarToggle,
  codingPanelOpen,
  showFilesPanel,
  onWorkspaceFiles,
  onToggleFilesPanel,
  mobileActionsOpen,
  onMobileActionsOpenChange,
  onWiki,
  wikiActive = false,
  onScheduler,
  onCompact,
}: ChatTopbarProps) {
  const isWebBridge = sessionTags?.includes('webbridge') ?? false

  const loopLabel = activeLoop
    ? `${activeLoop.paused ? 'Loop paused' : activeLoop.prompt ? 'Loop active' : 'Loop ready'}${activeLoop.prompt ? `: "${activeLoop.prompt}"` : ''}`
    : null
  const loopProgress = activeLoop ? `${activeLoop.used}/${activeLoop.limit}` : null

  return (
    <header
      {...dragHandlers}
      className={`mobile-safe-header relative z-(--z-header) flex shrink-0 items-center gap-1.5 px-1.5 py-1.5 ${
        isMacOverlay && isMobile ? 'select-none' : ''
      }`}
      style={
        isMacOverlay && isMobile
          ? { paddingLeft: 'calc(var(--spacing-mac-traffic-inset) + 6px)' }
          : undefined
      }
    >
        {/* Mobile only — hamburger + title */}
        {isMobile && (
          <div className="flex flex-1 shrink-0 items-center gap-1.5">
            <button
              type="button"
              onClick={() => {
                if (mode === 'coding') {
                  onCodingSidebarToggle()
                } else if (mode !== 'aim') {
                  onOpenMobileSidebar()
                }
              }}
              aria-label="Toggle sidebar"
              title="Toggle sidebar (Ctrl+B)"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            >
              <Menu size={15} aria-hidden="true" />
            </button>
            <div className="min-w-0 text-sm font-semibold text-(--color-text)">
              <div className="truncate">{codingIdentityLabel ?? (sessionTitle || 'EvoFlux')}</div>
              {activeAgent && <div className="truncate font-mono text-xs font-normal text-(--color-text-muted)">{activeAgent}</div>}
            </div>
          </div>
        )}

        {/* LEFT — agent switcher + loop status (desktop only) */}
        <div className="flex min-w-0 flex-1 items-center gap-2 overflow-visible">
          {effectiveViewMode === 'agent' && activeAgent && !isMobile && (
            <ActiveAgentSwitcher
              activeAgent={activeAgent}
              agents={agentNames}
              statuses={agentStatuses}
              onSelect={onSelectAgent}
            />
          )}
          {!isMobile && isWebBridge && <WebBridgeBrowserInfo />}
          {!isMobile && activeLoop && loopLabel && loopProgress && (
            <LoopStatusPill
              label={loopLabel}
              progress={loopProgress}
              compact={false}
            />
          )}
          {!isMobile && activeWorkflowExecution && (
            <WorkflowProgressPill
              execution={activeWorkflowExecution}
              onDismissFailed={onDismissWorkflowFailed}
            />
          )}
          {!isMobile && mode === 'coding' && (
            <TaskProgressPill
              isWorking={isTeamWorking}
              chapters={chapters}
            />
          )}
          {effectiveViewMode === 'split' && (
            <span className="text-xs text-(--color-text-muted)">
              Split · {splitAgentCount} agents
            </span>
          )}
        </div>

        {/* RIGHT — action cluster */}
        <div className="flex shrink-0 items-center gap-0.5">
        {isMobile ? (
          <>
            {headerTokens && (
              <TokenMeter
                input={headerTokens.input}
                output={headerTokens.output}
                cached={headerTokens.cached}
                trigger={headerTokens.trigger}
                pulsing={headerTokens.pulsing}
                className="mr-0.5"
              />
            )}
            <MobileHeaderAction
              Icon={FolderOpen}
              label={mode === 'coding' ? 'Workspace files' : 'Session files'}
              onClick={mode === 'coding'
                ? workspace ? onWorkspaceFiles : undefined
                : sessionId ? onToggleFilesPanel : undefined}
              active={mode === 'coding' ? codingPanelOpen : showFilesPanel}
              disabled={mode === 'coding' ? !workspace : !sessionId}
            />
            <MobileChatActions
              open={mobileActionsOpen}
              onOpenChange={onMobileActionsOpenChange}
              codingIdentityLabel={codingIdentityLabel}
              activeAgent={activeAgent}
              agents={agentNames}
              statuses={agentStatuses}
              onSelectAgent={onSelectAgent}
              onWiki={onWiki}
              onScheduler={onScheduler}
              onCompact={onCompact}
              activeLoop={activeLoop}
            />
          </>
        ) : (
          <>
          {!isMobile && onWiki && (
            <TopbarAction
              Icon={BookOpen}
              label="Wiki"
              onClick={onWiki}
              title="Wiki / session notes (Ctrl+M)"
              aria-pressed={wikiActive}
              indicator={wikiActive}
              indicatorClassName="bg-(--color-success)"
            />
          )}
          <SessionTOC sessionId={sessionId} />
          <AgentTopbar
            isMobile={false}
            tokens={headerTokens}
            contextBudget={contextUsed > 0 ? { used: contextUsed, max: contextWindowSize } : undefined}
            dreamRunning={dreamRunning}
            viewMode={viewMode}
            onViewModeChange={onViewModeChange}
            terminalAction={{
              Icon: Terminal,
              onClick: onToggleTerminal,
              title: 'AI Terminal (Ctrl+`)',
              ariaLabel: 'Terminal',
              indicator: terminalOpen,
            }}
            extraActions={
              <SessionScheduleIndicator
                sessionId={sessionId}
                onOpenScheduler={onOpenScheduler}
              />
            }
          />
          </>
        )}
        </div>
    </header>
  )
}

// ─── Loop status ────────────────────────────────────────────────────────────

function LoopStatusPill({
  label,
  progress,
  compact,
}: {
  label: string
  progress: string
  compact: boolean
}) {
  return (
    <div
      className="mx-1 flex max-w-[46vw] shrink-0 items-center gap-1 rounded-full border border-(--color-border) bg-(--bg-card) px-2 py-1 text-xs text-(--color-text) shadow-sm md:max-w-sm"
      title={`${label} · ${progress} turns`}
    >
      <span className="min-w-0 truncate font-medium">
        {compact ? 'Loop' : label}
      </span>
      <span className="shrink-0 font-mono text-xs text-(--color-text-muted)">{progress}</span>
    </div>
  )
}

function MobileLoopStatusCard({ activeLoop }: { activeLoop: ActiveLoop }) {
  const state = activeLoop.paused ? 'Paused' : activeLoop.prompt ? 'Active' : 'Ready'
  return (
    <div className="mb-1 rounded-md border border-(--color-border) bg-(--bg-card) px-2 py-2 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-(--color-text)">Loop {state.toLowerCase()}</span>
        <span className="font-mono text-xs text-(--color-text-muted)">{activeLoop.used}/{activeLoop.limit}</span>
      </div>
      {activeLoop.prompt && (
        <p className="mt-1 line-clamp-2 text-xs text-(--color-text-muted)" title={activeLoop.prompt}>
          {activeLoop.prompt}
        </p>
      )}
    </div>
  )
}

// ─── MobileChatActions ─────────────────────────────────────────────────────

function MobileHeaderAction({
  Icon,
  label,
  onClick,
  active = false,
  disabled = false,
  badge = 0,
}: {
  Icon: LucideIcon
  label: string
  onClick?: () => void
  active?: boolean
  disabled?: boolean
  badge?: number
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || !onClick}
      className={`relative flex h-9 w-9 items-center justify-center rounded-md transition-colors disabled:opacity-45 ${
        active
          ? 'bg-(--bg-key) text-(--color-text)'
          : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)'
      }`}
      aria-label={label}
      title={label}
    >
      <Icon size={16} aria-hidden="true" />
      {badge > 0 && (
        <span className="absolute right-0.5 top-0.5 min-w-3.5 rounded-full bg-(--color-accent) px-1 text-center font-mono text-xs leading-3.5 text-(--bg-page)">
          {badge > 9 ? '9+' : badge}
        </span>
      )}
    </button>
  )
}

interface MobileChatActionsProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  codingIdentityLabel: string | null
  activeAgent: string | null
  agents: string[]
  statuses: Record<string, AgentStatus | undefined>
  onSelectAgent: (agent: string) => void
  onWiki: () => void
  onScheduler: () => void
  onCompact: () => void
  activeLoop: ActiveLoop | null
}

function MobileChatActions({
  open,
  onOpenChange,
  codingIdentityLabel,
  activeAgent,
  agents,
  statuses,
  onSelectAgent,
  onWiki,
  onScheduler,
  onCompact,
  activeLoop,
}: MobileChatActionsProps) {
  return (
    <>
      <button
        type="button"
        data-no-drag
        onClick={() => onOpenChange(true)}
        className="mr-1 flex h-9 w-9 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
        aria-label="Open chat actions"
        title="Chat actions"
      >
        <MoreHorizontal size={17} aria-hidden="true" />
      </button>

      <AnimatePresence>
        {open && (
          <>
            <motion.div
              key="mobile-actions-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="mobile-safe-top fixed inset-x-0 bottom-0 z-(--z-drawer) bg-(--color-overlay) md:hidden"
              aria-hidden="true"
              onClick={() => onOpenChange(false)}
            />
            <motion.aside
              key="mobile-actions-drawer"
              initial={{ x: 280 }}
              animate={{ x: 0 }}
              exit={{ x: 280 }}
              transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
              className="mobile-safe-top fixed bottom-0 right-0 z-(--z-overlay) flex w-[min(272px,calc(100vw-2rem))] flex-col overflow-hidden border-l border-(--color-border) bg-(--bg-page) shadow-xl md:hidden"
              role="dialog"
              aria-modal="true"
              aria-label="Chat actions"
            >
              <div className="border-b border-(--color-border) px-3 py-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-(--color-text)">
                      {codingIdentityLabel ?? 'Chat actions'}
                    </p>
                    {activeAgent && (
                      <p className="mt-1 truncate font-mono text-xs font-normal text-(--color-text-muted)">Active: {activeAgent}</p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => onOpenChange(false)}
                    className="rounded-md p-1.5 text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                    aria-label="Close chat actions"
                  >
                    <X size={16} aria-hidden="true" />
                  </button>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto p-2">
                {activeLoop && (
                  <>
                    <div className="px-2 py-2 text-xs font-medium text-(--color-text-muted)">Loop</div>
                    <MobileLoopStatusCard activeLoop={activeLoop} />
                  </>
                )}
                {activeAgent && agents.length > 1 && (
                  <>
                    <div className="px-2 py-2 text-xs font-medium text-(--color-text-muted)">Agents</div>
                    {agents.map((name) => (
                      <button
                        type="button"
                        key={name}
                        onClick={() => { onSelectAgent(name); onOpenChange(false) }}
                        className="flex min-h-10 w-full items-center gap-2 rounded-md px-2 text-left text-sm transition-colors hover:bg-(--bg-key)"
                      >
                        <span className={`h-2 w-2 rounded-full ${dotClassFor(name, statuses[name])}`} aria-hidden="true" />
                        <span className="min-w-0 flex-1 truncate font-mono text-xs">{name}</span>
                        {name === activeAgent && <Check size={13} className="text-(--color-accent)" aria-hidden="true" />}
                      </button>
                    ))}
                  </>
                )}

                <div className="px-2 py-2 text-xs font-medium text-(--color-text-muted)">Session</div>
                <button type="button" onClick={onWiki} className="flex min-h-10 w-full items-center gap-2 rounded-md px-2 text-left text-sm transition-colors hover:bg-(--bg-key)">
                  <Brain size={15} aria-hidden="true" />
                  <span className="flex-1">Wiki</span>
                </button>
                <button type="button" onClick={onScheduler} className="flex min-h-10 w-full items-center gap-2 rounded-md px-2 text-left text-sm transition-colors hover:bg-(--bg-key)">
                  <CalendarClock size={15} aria-hidden="true" />
                  <span className="flex-1">Scheduler</span>
                </button>
                <button type="button" onClick={onCompact} className="flex min-h-10 w-full items-center gap-2 rounded-md px-2 text-left text-sm transition-colors hover:bg-(--bg-key)">
                  <Minimize2 size={15} aria-hidden="true" />
                  <span className="flex-1">Compact context</span>
                </button>
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  )
}

// ─── ActiveAgentSwitcher ───────────────────────────────────────────────────
//
// Single chip → dropdown of all members. Replaces the horizontal chip
// carousel that didn't scale past ~4 agents. ``data-no-drag`` on the
// trigger opts it out of ``useTauriDrag``'s interactive guard so the
// chip-as-trigger doesn't race the window-drag handler.

interface ActiveAgentSwitcherProps {
  activeAgent: string
  agents: string[]
  statuses: Record<string, AgentStatus | undefined>
  onSelect: (agent: string) => void
}

const DOT_BY_ROLE: Record<AgentRole, string> = {
  EvoFlux: 'bg-(--color-marker-mint)',
  executor: 'bg-(--color-marker-orange)',
  consultant: 'bg-(--color-marker-blue)',
  explorer: 'bg-(--color-text-muted)',
}

function dotClassFor(agent: string, status: AgentStatus | undefined): string {
  if (status === 'error') return 'bg-(--color-error)'
  if (status === 'working') return 'animate-pulse bg-(--color-accent)'
  if (status === 'offline') return 'bg-(--color-text-subtle) opacity-50'
  if (isAgentRole(agent)) return DOT_BY_ROLE[agent]
  return 'bg-(--color-success)'
}

function ActiveAgentSwitcher({
  activeAgent,
  agents,
  statuses,
  onSelect,
}: ActiveAgentSwitcherProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-no-drag
        className="inline-flex h-9 min-w-0 shrink items-center gap-2 rounded-md px-2 font-mono text-xs leading-none font-semibold text-(--color-text) outline-none transition-all hover:bg-(--bg-key) focus-visible:ring-2 focus-visible:ring-(--color-accent)/40 sm:h-8 sm:px-3 sm:py-0"
        aria-label={`Switch active agent (current: ${activeAgent})`}
      >
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${dotClassFor(activeAgent, statuses[activeAgent])}`}
          aria-hidden="true"
        />
        <span className="min-w-0 truncate">{activeAgent}</span>
        <ChevronDown size={12} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
      </DropdownMenuTrigger>

      {/* w-auto overrides w-(--anchor-width) so the menu sizes to its
          content rather than the (narrow) trigger. */}
      <DropdownMenuContent
        align="start"
        sideOffset={6}
        className="w-auto max-w-[min(90vw,24rem)]"
      >
        {agents.map((name) => (
          <DropdownMenuItem
            key={name}
            onClick={() => onSelect(name)}
            className="flex min-w-40 items-center gap-2 font-mono text-xs whitespace-nowrap"
          >
            <span
              className={`h-2 w-2 shrink-0 rounded-full ${dotClassFor(name, statuses[name])}`}
              aria-hidden="true"
            />
            <span>{name}</span>
            {name === activeAgent && (
              <Check size={12} className="ml-auto shrink-0 text-(--color-accent)" aria-hidden="true" />
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
