import type { MouseEvent as ReactMouseEvent } from 'react'
import { motion } from 'framer-motion'
import {
  Check,
  ChevronDown,
  ClipboardList,
  FileDiff,
  GitPullRequest,
  Menu,
  Users,
  UsersRound,
} from 'lucide-react'
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
import type { TeamLeadOption } from '@/api/types'
import { useRegistryQuery, useWebBridgeSettingsQuery } from '@/queries'
import { ContextBudgetBar } from '@/components/ContextBudgetBar'
import { WebBridgeStatusPopover } from '@/components/shell/WebBridgeStatusDialog'

interface WorkbenchBarProps {
  activeAgent: string | null
  leadName: string | null
  leadOptions: TeamLeadOption[]
  leadChanging: boolean
  onLeadChange: (leadName: string) => void
  viewMode: ViewMode
  onViewModeChange: (mode: ViewMode) => void
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
  const sidebarCollapsed = useUIStore((state) => state.sidebarCollapsed)
  const workbenchOpen = useUIStore((state) => state.workbenchOpen)
  const activeWorkbenchTool = useUIStore((state) => state.activeWorkbenchTool)
  const toggleWorkbench = useUIStore((state) => state.toggleWorkbench)
  const openWorkbenchTool = useUIStore((state) => state.openWorkbenchTool)
  const turnChanges = useTeamStore((s) => s.turnChanges)
  const showTurnChanges = useTeamStore((s) => s.showTurnChanges)
  const planApproval = useTeamStore((s) => s.planApproval)
  const sessionModel = useTeamStore((s) => s.sessionModel)
  const sessionId = useTeamStore((s) => s.sessionId)
  const leadName = useTeamStore((s) => s.leadName)
  const isTeamWorking = useTeamStore((s) => s.isTeamWorking)
  const compactTeam = useTeamStore((s) => s.compactTeam)
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
  const canCompactContext = Boolean(sessionId && props.activeAgent === leadName)
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
  const handleWorkbenchToggle = () => {
    if (!workbenchOpen && props.mode === 'coding' && props.workspace && activeWorkbenchTool === null) {
      openWorkbenchTool('overview')
      return
    }
    toggleWorkbench()
  }

  return (
    <header
      {...props.dragHandlers}
      className={cn(
        'workbench-topbar flex h-12 shrink-0 items-center gap-2 overflow-hidden bg-(--bg-page) px-3',
        props.isMacOverlay && 'mac-drag-region',
        props.isMacOverlay
          ? (props.isMobile || sidebarCollapsed || props.sidebarOverlay)
            && 'pl-(--spacing-mac-window-controls-inset)'
          : !props.isMobile && !props.sidebarOverlay && 'pl-12',
      )}
    >
      {!props.isMacOverlay && (props.isMobile || props.sidebarOverlay) && (
        <motion.button
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

      <div className="flex min-w-0 flex-1 items-center gap-2">
        <DropdownMenu>
          <DropdownMenuTrigger
            className="group flex h-7 w-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-(--color-border) bg-(--bg-card)/55 px-0 text-xs font-medium text-(--color-text) outline-none transition-colors hover:bg-(--bg-key) data-[popup-open]:bg-(--bg-key) disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto sm:max-w-56 sm:justify-start sm:px-2"
            aria-label="Select lead agent"
            disabled={isTeamWorking || props.leadChanging || props.leadOptions.length === 0}
            title={isTeamWorking ? 'Finish or stop the active turn before changing lead' : 'Select lead agent and owned team'}
            data-no-drag
          >
            <UsersRound data-lead-icon size={14} className="shrink-0 text-(--color-accent)" />
            <span className="hidden truncate sm:inline">{props.leadName ?? 'Choose lead'}</span>
            <ChevronDown size={11} className="hidden shrink-0 text-(--color-text-subtle) transition-transform group-data-[popup-open]:rotate-180 sm:block" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-[min(18rem,calc(100vw-1rem))]">
            <div className="px-2 py-1.5">
              <p className="text-xs font-medium text-(--color-text)">{props.mode === 'coding' ? 'Coding' : 'Work'} leads</p>
              <p className="mt-0.5 text-[10px] text-(--color-text-muted)">Each lead uses only the members shown below.</p>
            </div>
            {props.leadOptions.map((lead) => (
              <DropdownMenuItem
                key={lead.name}
                disabled={isTeamWorking || props.leadChanging || lead.name === props.leadName}
                onClick={() => props.onLeadChange(lead.name)}
                className="items-start py-2"
              >
                <UsersRound data-lead-icon size={14} className="mt-0.5 shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 font-medium">
                    <span className="truncate">{lead.name}</span>
                    {lead.is_default && <span className="rounded bg-(--bg-key) px-1 text-[9px] text-(--color-text-muted)">default</span>}
                  </span>
                  <span className="mt-0.5 flex items-start gap-1 whitespace-normal break-words text-[10px] leading-4 text-(--color-text-muted)">
                    <Users size={10} />
                    {lead.members.length === 0 ? 'No members' : lead.members.map((member) => member.name).join(', ')}
                  </span>
                </span>
                {lead.name === props.leadName && <Check size={13} className="mt-0.5 text-(--color-accent)" />}
              </DropdownMenuItem>
            ))}
            {props.leadOptions.length === 0 && <p className="px-2 py-2 text-xs text-(--color-text-muted)">No lead agents configured for this mode.</p>}
          </DropdownMenuContent>
        </DropdownMenu>
        {props.reviewContext && props.onOpenReviewContext && (
          <motion.button
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
      </div>

      <div
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
              <span className="inline-block">{viewModeLabel}</span>
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
            contextLength={contextMax}
            input={activeUsage.promptTokens}
            cached={activeUsage.cachedTokens}
            cacheWrite={activeUsage.cacheWriteTokens}
            turnInput={activeUsage.turnPromptTokens}
            turnOutput={activeUsage.turnCompletionTokens}
            turnCached={activeUsage.turnCachedTokens}
            turnCacheWrite={activeUsage.turnCacheWriteTokens}
            turnCalls={activeUsage.turnCalls}
            cost={activeUsage.turnCost}
            trigger={summaryTrigger}
            onCompact={canCompactContext ? compactTeam : undefined}
            compactDisabled={isTeamWorking}
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
            <span
              className="absolute inset-0 rounded-lg bg-(--bg-key)"
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
      </div>
    </header>
  )
}
