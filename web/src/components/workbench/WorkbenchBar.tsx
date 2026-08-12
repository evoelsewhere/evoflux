import type { MouseEvent as ReactMouseEvent } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Check,
  ChevronDown,
  ClipboardList,
  FileDiff,
  GitPullRequest,
  Menu,
} from 'lucide-react'
import { AgentLogo } from '@/components/AgentLogo'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { useMotionPreset } from '@/lib/motion'
import { usePlatform } from '@/hooks/use-platform'
import { useTeamStore } from '@/stores/useTeamStore'
import { useUIStore } from '@/stores/useUIStore'
import { OpenWithMenu } from '@/components/workbench/OpenWithMenu'
import {
  FocusViewIcon,
  MonitorViewIcon,
  SidePanelIcon,
  SplitViewIcon,
} from '@/components/ui/layout-icons'
import type { ViewMode } from '@/components/TeamChatView/types'
import type { CodeReviewSessionContext } from '@/lib/code-review-session'
import { useRegistryQuery, useWebBridgeSettingsQuery } from '@/queries'
import { ContextBudgetBar } from '@/components/ContextBudgetBar'
import { WebBridgeStatusPopover } from '@/components/shell/WebBridgeStatusDialog'

interface WorkbenchBarProps {
  identity: string
  activeAgent: string | null
  agentNames: string[]
  viewMode: ViewMode
  onViewModeChange: (mode: ViewMode) => void
  onSelectAgent: (agent: string) => void
  onOpenMobileSidebar: () => void
  isMobile: boolean
  /** Show the navigation button when desktop navigation is in drawer mode. */
  sidebarOverlay?: boolean
  isMacOverlay: boolean
  /** Current mode — 'work' or 'coding'. */
  mode: 'work' | 'coding'
  /** Absolute workspace root for the "Open in" menu. */
  workspace?: string | null
  /** Opens the workspace picker when no workspace is active. */
  onChooseWorkspace?: () => void
  reviewContext?: CodeReviewSessionContext | null
  onOpenReviewContext?: () => void
  /** Controls whether the active session can use the connected browser. */
  webBridgeEnabled: boolean
  onWebBridgeEnabledChange: (enabled: boolean) => void
  webBridgePopoverOpen: boolean
  onWebBridgePopoverOpenChange: (open: boolean) => void
  dragHandlers?: {
    onMouseDown?: (event: ReactMouseEvent<HTMLElement>) => void
  }
}

export function WorkbenchBar(props: WorkbenchBarProps) {
  const workbenchOpen = useUIStore((state) => state.workbenchOpen)
  const activeWorkbenchTool = useUIStore((state) => state.activeWorkbenchTool)
  const toggleWorkbench = useUIStore((state) => state.toggleWorkbench)
  const openWorkbenchTool = useUIStore((state) => state.openWorkbenchTool)
  const turnChanges = useTeamStore((s) => s.turnChanges)
  const showTurnChanges = useTeamStore((s) => s.showTurnChanges)
  const planApproval = useTeamStore((s) => s.planApproval)
  const sessionModel = useTeamStore((s) => s.sessionModel)
  const activeUsage = useTeamStore((s) =>
    props.activeAgent ? s.agentStreams[props.activeAgent]?.usage : undefined,
  )
  const activeModel = useTeamStore((s) =>
    props.activeAgent ? s.agentStreams[props.activeAgent]?.model : null,
  )
  const registry = useRegistryQuery()
  const webBridgeSettings = useWebBridgeSettingsQuery()
  const motionPreset = useMotionPreset()
  const { isTauri, os } = usePlatform()
  const isDesktopShell = isTauri && os !== 'ios' && os !== 'android'
  const showOpenWith =
    isDesktopShell &&
    !props.isMobile &&
    (props.workspace != null || props.onChooseWorkspace != null)
  const webBridgePolicyEnabled = webBridgeSettings.data?.enabled !== false
  const changesCount = turnChanges?.files.length ?? 0
  const planPending = Boolean(planApproval)
  const modelId = sessionModel ?? activeModel ?? null
  const modelEntry = modelId
    ? registry.data?.models.find((entry) => entry.id === modelId)
    : undefined
  const contextMax = modelEntry?.context_length ?? undefined
  const summaryTrigger = modelEntry?.summary_trigger_tokens
  const viewModeLabel =
    props.viewMode === 'agent'
      ? 'Agent'
      : props.viewMode === 'split'
        ? 'Split'
        : 'Monitor'
  const ViewModeIcon =
    props.viewMode === 'agent'
      ? FocusViewIcon
      : props.viewMode === 'split'
        ? SplitViewIcon
        : MonitorViewIcon
  const activeAgentLabel = props.activeAgent ?? props.identity
  const handleWorkbenchToggle = () => {
    if (!workbenchOpen && props.mode === 'coding' && props.workspace && activeWorkbenchTool === null) {
      openWorkbenchTool('overview')
      return
    }
    toggleWorkbench()
  }

  return (
    <motion.header
      layout="position"
      transition={motionPreset.spring}
      {...props.dragHandlers}
      className={cn(
        'workbench-topbar flex h-12 shrink-0 items-center gap-2 overflow-hidden bg-(--bg-page) px-3 will-change-transform',
        props.isMacOverlay && 'mac-drag-region pt-3',
      )}
    >
      {(props.isMobile || props.sidebarOverlay) && (
        <motion.button
          layout
          type="button"
          onClick={props.onOpenMobileSidebar}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.92 }}
          transition={motionPreset.spring}
          className="flex h-8 w-8 items-center justify-center rounded-xl text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
          aria-label="Open navigation"
          data-no-drag
        >
          <Menu size={16} />
        </motion.button>
      )}

      <motion.div
        layout="position"
        transition={motionPreset.spring}
        className="flex min-w-0 flex-1 items-center gap-2"
      >
        <DropdownMenu>
          <DropdownMenuTrigger
            className="group flex h-9 min-w-0 max-w-full items-center gap-2 rounded-xl border border-transparent bg-(--bg-card)/45 py-1 pl-1.5 pr-2.5 text-sm font-medium text-(--color-text) outline-none transition-[background-color,border-color,box-shadow] hover:border-(--color-border) hover:bg-(--bg-card) hover:shadow-sm data-[popup-open]:border-(--color-border) data-[popup-open]:bg-(--bg-card)"
            aria-label="Choose active agent"
            data-no-drag
          >
            <AgentLogo
              name={props.activeAgent ?? 'EvoFlux'}
              size="sm"
              className="size-6 rounded-lg"
              statusClassName="bg-(--color-success)"
            />
            <AnimatePresence initial={false} mode="popLayout">
              <motion.span
                key={activeAgentLabel}
                initial={{ opacity: 0, y: 4 * motionPreset.distance }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 * motionPreset.distance }}
                transition={motionPreset.transition}
                className="workbench-identity-label max-w-44 truncate"
              >
                {activeAgentLabel}
              </motion.span>
            </AnimatePresence>
            <ChevronDown
              size={13}
              className="shrink-0 text-(--color-text-subtle) transition-transform group-data-[popup-open]:rotate-180"
            />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <div className="px-1.5 py-1 text-xs font-medium text-(--color-text-muted)">
              Active agent
            </div>
            {props.agentNames.map((agent) => (
              <DropdownMenuItem
                key={agent}
                onClick={() => props.onSelectAgent(agent)}
                className={cn(agent === props.activeAgent && 'bg-(--bg-key)')}
              >
                <AgentLogo name={agent} size="xs" />
                <span className="truncate">{agent}</span>
                {agent === props.activeAgent && (
                  <Check size={13} className="ml-auto text-(--color-accent)" />
                )}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        {props.reviewContext && props.onOpenReviewContext && (
          <motion.button
            layout
            type="button"
            onClick={props.onOpenReviewContext}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.96 }}
            transition={motionPreset.spring}
            className="flex h-7 shrink-0 items-center gap-1.5 rounded-lg border border-(--color-accent)/30 bg-(--color-accent)/8 px-2 text-[11px] font-medium text-(--color-accent) transition-colors hover:border-(--color-accent)/40 hover:bg-(--color-accent)/12"
            aria-label={`Open linked review #${props.reviewContext.number}`}
            title="Open linked PR/MR"
            data-no-drag
          >
            <GitPullRequest size={13} />
            <span>Review #{props.reviewContext.number}</span>
          </motion.button>
        )}
      </motion.div>

      <motion.div
        layout="position"
        transition={motionPreset.spring}
        className="flex shrink-0 items-center rounded-xl border border-(--color-border) bg-(--bg-card)/55 p-0.5 shadow-sm"
        data-no-drag
      >
        {showOpenWith && (
          <>
            <OpenWithMenu
              workspace={props.workspace ?? null}
              onChooseWorkspace={props.onChooseWorkspace}
            />
            <span className="mx-0.5 h-4 w-px bg-(--color-border)" aria-hidden="true" />
          </>
        )}
        <WebBridgeStatusPopover
          open={props.webBridgePopoverOpen}
          onOpenChange={props.onWebBridgePopoverOpenChange}
          enabled={props.webBridgeEnabled}
          onEnabledChange={props.onWebBridgeEnabledChange}
          policyEnabled={webBridgePolicyEnabled}
        />

        <span className="mx-0.5 h-4 w-px bg-(--color-border)" aria-hidden="true" />

        <DropdownMenu>
          <DropdownMenuTrigger
            className="group flex h-7 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-(--color-text-muted) outline-none transition-colors hover:bg-(--bg-key) hover:text-(--color-text) data-[popup-open]:bg-(--bg-key) data-[popup-open]:text-(--color-text)"
            aria-label="Choose conversation layout"
          >
            <ViewModeIcon size={14} />
            <span className="workbench-view-label overflow-hidden">
              <AnimatePresence initial={false} mode="popLayout">
                <motion.span
                  key={viewModeLabel}
                  initial={{ opacity: 0, y: 4 * motionPreset.distance }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 * motionPreset.distance }}
                  transition={motionPreset.transition}
                  className="inline-block"
                >
                  {viewModeLabel}
                </motion.span>
              </AnimatePresence>
            </span>
            <ChevronDown
              size={11}
              className="text-(--color-text-subtle) transition-transform group-data-[popup-open]:rotate-180"
            />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <div className="px-1.5 py-1 text-xs font-medium text-(--color-text-muted)">
              Conversation layout
            </div>
            <DropdownMenuItem onClick={() => props.onViewModeChange('agent')}>
              <FocusViewIcon size={15} />
              <span>Agent</span>
              {props.viewMode === 'agent' && <Check size={13} className="ml-auto text-(--color-accent)" />}
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={props.isMobile}
              onClick={() => props.onViewModeChange('split')}
            >
              <SplitViewIcon size={15} />
              <span>Split</span>
              {props.viewMode === 'split' && <Check size={13} className="ml-auto text-(--color-accent)" />}
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={props.isMobile}
              onClick={() => props.onViewModeChange('monitor')}
            >
              <MonitorViewIcon size={15} />
              <span>Monitor</span>
              {props.viewMode === 'monitor' && <Check size={13} className="ml-auto text-(--color-accent)" />}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <span className="mx-0.5 h-4 w-px bg-(--color-border)" aria-hidden="true" />

        {activeUsage && activeUsage.promptTokens + activeUsage.completionTokens > 0 && (
          <ContextBudgetBar
            compact
            used={activeUsage.promptTokens}
            max={contextMax}
            input={activeUsage.promptTokens}
            output={activeUsage.completionTokens}
            cached={activeUsage.cachedTokens}
            trigger={summaryTrigger}
          />
        )}

        {planPending && (
          <span
            className="flex h-7 items-center gap-1.5 rounded-lg border border-(--color-border) bg-(--bg-key) px-2 text-[11px] font-medium text-(--color-text)"
            title="Plan awaiting approval"
            aria-label="Plan awaiting approval"
          >
            <ClipboardList size={12} className="text-(--color-text-muted)" aria-hidden />
            Plan
          </span>
        )}

        {changesCount > 0 && (
          <button
            type="button"
            onClick={() => {
              if (props.workspace) {
                useUIStore.getState().openGitChanges()
              } else {
                showTurnChanges()
              }
            }}
            className="focus-ring-control flex h-7 items-center gap-1.5 rounded-lg border border-(--color-border) bg-(--bg-key) px-2 font-mono text-[11px] tabular-nums text-(--color-text) transition-colors hover:border-(--color-border-strong)"
            title="Files changed this turn"
            aria-label={`Changes +${turnChanges?.additions ?? 0} −${turnChanges?.deletions ?? 0}`}
          >
            <FileDiff size={12} className="text-(--color-text-muted)" aria-hidden />
            <span className="text-(--color-success)">+{turnChanges?.additions ?? 0}</span>
            <span className="text-(--color-error)">−{turnChanges?.deletions ?? 0}</span>
            <span className="text-(--color-text-muted)">·{changesCount}</span>
          </button>
        )}

        <motion.button
          layout
          type="button"
          onClick={handleWorkbenchToggle}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.9 }}
          transition={motionPreset.spring}
          className={cn(
            'relative flex h-7 w-8 shrink-0 items-center justify-center overflow-hidden rounded-lg transition-colors',
            workbenchOpen
              ? 'text-(--color-text)'
              : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
          )}
          aria-label={workbenchOpen ? 'Hide side panel' : 'Show side panel'}
          title={workbenchOpen ? 'Hide side panel' : 'Show side panel'}
        >
          {workbenchOpen && (
            <motion.span
              layoutId="workbench-toggle-active"
              className="absolute inset-0 rounded-lg bg-(--bg-key)"
              transition={motionPreset.spring}
            />
          )}
          <motion.span
            className="relative z-10"
            animate={{ scaleX: workbenchOpen ? 1 : 0.92 }}
            transition={motionPreset.spring}
          >
            <SidePanelIcon size={15} />
          </motion.span>
        </motion.button>
      </motion.div>
    </motion.header>
  )
}
