/**
 * ChatTopbar — the team chat header strip (extracted from TeamChatView).
 *
 * Owns the full <header> chrome: mobile hamburger + title, the desktop
 * ``ActiveAgentSwitcher`` dropdown, ``LoopStatusPill``,
 * ``WorkflowProgressPill``, coding-only ``TaskProgressPill``,
 * and the ``AgentTopbar`` right cluster with its action descriptors.
 * Props-driven — TeamChatView passes everything it needs.
 *
 * The Tauri drag handlers are spread onto the <header> by the caller
 * (see ``useTauriDrag``); ``data-no-drag`` on the interactive controls
 * opts them out of the window-drag guard.
 */
import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'
import { BookOpen, Brain, CalendarClock, Check, ChevronDown, FolderOpen, Menu, Minimize2, MoreHorizontal, Terminal, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ContextBudgetBar } from '@/components/ContextBudgetBar'
import { TopbarAction } from '@/components/ui/topbar-action'
import { AgentTopbar, type AgentTopbarTokens } from '@/components/AgentTopbar'
import { TaskProgressPill } from '@/components/TaskProgressPill'
import { WorkflowProgressPill } from '@/components/WorkflowProgressPill'
import { SessionScheduleIndicator } from '@/components/SessionScheduleIndicator'
import { resolveAgentRole } from '@/lib/agent-roles'
import { AgentChip } from '@/components/ui/agent-chip'
import { useMotionPreset } from '@/lib/motion'
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
  const headerRef = useRef<HTMLElement>(null)
  const [compactHeader, setCompactHeader] = useState(false)

  useEffect(() => {
    const header = headerRef.current
    if (!header || isMobile) return
    const update = () => setCompactHeader(header.clientWidth < 760)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(header)
    return () => observer.disconnect()
  }, [isMobile])

  const loopLabel = activeLoop
    ? `${activeLoop.paused ? 'Loop paused' : activeLoop.prompt ? 'Loop active' : 'Loop ready'}${activeLoop.prompt ? `: "${activeLoop.prompt}"` : ''}`
    : null
  const loopProgress = activeLoop ? `${activeLoop.used}/${activeLoop.limit}` : null

  return (
    <header
      ref={headerRef}
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
          {!compactHeader && effectiveViewMode === 'agent' && activeAgent && !isMobile && (
            <ActiveAgentSwitcher
              activeAgent={activeAgent}
              agents={agentNames}
              statuses={agentStatuses}
              onSelect={onSelectAgent}
            />
          )}
          {!compactHeader && !isMobile && activeLoop && loopLabel && loopProgress && (
            <LoopStatusPill
              label={loopLabel}
              progress={loopProgress}
              compact={false}
            />
          )}
          {!compactHeader && !isMobile && activeWorkflowExecution && (
            <WorkflowProgressPill
              execution={activeWorkflowExecution}
              onDismissFailed={onDismissWorkflowFailed}
            />
          )}
          {!compactHeader && !isMobile && mode === 'coding' && (
            <TaskProgressPill
              isWorking={isTeamWorking}
              chapters={chapters}
            />
          )}
          {!compactHeader && effectiveViewMode === 'split' && (
            <span className="text-xs text-(--color-text-muted)">
              Split · {splitAgentCount} agents
            </span>
          )}
        </div>

        {/* RIGHT — action cluster */}
        <div className="flex shrink-0 items-center gap-0.5">
        {isMobile ? (
          <>
            {(contextWindowSize !== undefined || contextUsed > 0) && (
              <ContextBudgetBar
                used={contextUsed}
                max={contextWindowSize}
                input={headerTokens?.input}
                output={headerTokens?.output}
                cached={headerTokens?.cached}
                trigger={headerTokens?.trigger}
                compact
              />
            )}
            <MobileHeaderAction
              Icon={FolderOpen}
              label={mode === 'coding' ? (workspace ? 'Workspace files' : 'Open workspace') : 'Session files'}
              onClick={mode === 'coding' ? onWorkspaceFiles : sessionId ? onToggleFilesPanel : undefined}
              active={mode === 'coding' ? codingPanelOpen : showFilesPanel}
              disabled={mode !== 'coding' && !sessionId}
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
          {compactHeader ? (
            <>
              {(contextWindowSize !== undefined || contextUsed > 0) && (
                <ContextBudgetBar
                  used={contextUsed}
                  max={contextWindowSize}
                  input={headerTokens?.input}
                  output={headerTokens?.output}
                  cached={headerTokens?.cached}
                  trigger={headerTokens?.trigger}
                  compact
                />
              )}
              <DesktopHeaderOverflow
                mode={mode}
                workspace={workspace}
                sessionId={sessionId}
                activeAgent={activeAgent}
                agents={agentNames}
                onSelectAgent={onSelectAgent}
                viewMode={viewMode}
                onViewModeChange={onViewModeChange}
                onWiki={onWiki}
                onWorkspaceFiles={onWorkspaceFiles}
                onToggleTerminal={onToggleTerminal}
                onScheduler={onScheduler}
                onCompact={onCompact}
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
          <TopbarAction
            Icon={FolderOpen}
            label={mode === 'coding' ? (workspace ? 'Workspace' : 'Open workspace') : 'Files'}
            onClick={mode === 'coding' ? onWorkspaceFiles : sessionId ? onToggleFilesPanel : undefined}
            title={mode === 'coding' ? (workspace ? 'Workspace panel' : 'Open workspace') : 'Session files'}
            aria-pressed={mode === 'coding' ? codingPanelOpen : showFilesPanel}
            indicator={mode === 'coding' ? codingPanelOpen : showFilesPanel}
            disabled={mode !== 'coding' && !sessionId}
          />
          <AgentTopbar
            isMobile={false}
            tokens={headerTokens}
            contextBudget={
              contextWindowSize !== undefined || contextUsed > 0
                ? { used: contextUsed, max: contextWindowSize }
                : undefined
            }
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
          </>
        )}
        </div>
    </header>
  )
}

function DesktopHeaderOverflow({
  mode,
  workspace,
  sessionId,
  activeAgent,
  agents,
  onSelectAgent,
  viewMode,
  onViewModeChange,
  onWiki,
  onWorkspaceFiles,
  onToggleTerminal,
  onScheduler,
  onCompact,
}: {
  mode: ChatTopbarProps['mode']
  workspace: string | null
  sessionId: string | null
  activeAgent: string | null
  agents: string[]
  onSelectAgent: (agent: string) => void
  viewMode: ViewMode
  onViewModeChange: (mode: ViewMode) => void
  onWiki: () => void
  onWorkspaceFiles: () => void
  onToggleTerminal: () => void
  onScheduler: () => void
  onCompact: () => void
}) {
  const workspaceLabel = mode === 'coding'
    ? workspace ? 'Workspace' : 'Open workspace'
    : 'Files'

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-no-drag
        className="flex h-8 w-8 items-center justify-center rounded-[9px] text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/40"
        aria-label="More chat actions"
        title="More chat actions"
      >
        <MoreHorizontal size={17} aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {activeAgent && agents.map((agent) => (
          <DropdownMenuItem key={agent} onClick={() => onSelectAgent(agent)}>
            <span className="min-w-0 flex-1 truncate">{agent}</span>
            {agent === activeAgent && <Check size={14} className="text-(--color-accent)" aria-hidden="true" />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuItem onClick={onWiki}>
          <BookOpen size={14} aria-hidden="true" /> Wiki
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={onWorkspaceFiles}
          disabled={mode !== 'coding' && !sessionId}
        >
          <FolderOpen size={14} aria-hidden="true" /> {workspaceLabel}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={onToggleTerminal}>
          <Terminal size={14} aria-hidden="true" /> Terminal
        </DropdownMenuItem>
        <DropdownMenuItem onClick={onScheduler}>
          <CalendarClock size={14} aria-hidden="true" /> Scheduler
        </DropdownMenuItem>
        <DropdownMenuItem onClick={onCompact}>
          <Minimize2 size={14} aria-hidden="true" /> Compact context
        </DropdownMenuItem>
        {(['agent', 'split', 'monitor'] as ViewMode[]).map((candidate) => (
          <DropdownMenuItem key={candidate} onClick={() => onViewModeChange(candidate)}>
            <span className="min-w-0 flex-1 capitalize">{candidate} view</span>
            {candidate === viewMode && <Check size={14} className="text-(--color-accent)" aria-hidden="true" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
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

function statusDotClass(status: AgentStatus | undefined): string | undefined {
  if (status === 'error') return 'bg-(--color-error)'
  if (status === 'working') return 'animate-pulse bg-(--color-accent)'
  if (status === 'offline') return 'bg-(--color-text-subtle) opacity-50'
  return undefined
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
  const preset = useMotionPreset()
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
              className="mobile-safe-top fixed inset-x-0 bottom-0 z-(--z-drawer) bg-(--color-overlay) md:hidden"
              aria-hidden="true"
              onClick={() => onOpenChange(false)}
            />
            <motion.aside
              key="mobile-actions-drawer"
              initial={{ x: 280 }}
              animate={{ x: 0 }}
              exit={{ x: 280 }}
              transition={preset.spring}
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
                    <div className="px-2 py-2 text-xs font-medium text-(--color-text-muted)">Team</div>
                    <div className="mb-2 flex flex-wrap gap-1.5 px-2">
                      {agents.map((name) => (
                        <AgentChip
                          key={name}
                          role={resolveAgentRole(name)}
                          label={name}
                          active={name === activeAgent}
                          className="px-2 py-1"
                          dotClassName={statusDotClass(statuses[name])}
                          onClick={() => { onSelectAgent(name); onOpenChange(false) }}
                        />
                      ))}
                    </div>
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
        className="inline-flex h-9 min-w-0 shrink items-center gap-1.5 rounded-md px-1.5 outline-none transition-colors hover:bg-(--bg-key) focus-visible:ring-2 focus-visible:ring-(--color-accent)/40 sm:h-8 sm:px-2"
        aria-label={`Switch active agent (current: ${activeAgent})`}
      >
        <AgentChip
          role={resolveAgentRole(activeAgent)}
          label={activeAgent}
          active
          className="min-w-0 truncate px-2 py-1"
          dotClassName={statusDotClass(statuses[activeAgent])}
        />
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
            className="flex min-w-40 items-center gap-2 whitespace-nowrap"
          >
            <AgentChip
              role={resolveAgentRole(name)}
              label={name}
              active={name === activeAgent}
              className="min-w-0 flex-1 truncate px-2 py-1"
              dotClassName={statusDotClass(statuses[name])}
            />
            {name === activeAgent && (
              <Check size={12} className="ml-auto shrink-0 text-(--color-accent)" aria-hidden="true" />
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
