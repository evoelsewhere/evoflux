/**
 * AgentTopbar — right-cluster composite for the chat header.
 *
 * Layout: dream pulse · tokens · view mode switch · todos/files/wiki etc.
 * Props-driven so previews and future single-agent surfaces can reuse
 * it without pulling in TeamChatView's stores. Design source:
 * `AgentTopbar` (`E8lml9`) in `.diagrams/EvoFlux-ui.pen`.
 */

import {
  Brain,
  CalendarClock,
  FolderOpen,
  ListChecks,
  Moon,
  TerminalSquare,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { motion } from 'framer-motion'

import { TopbarAction } from '@/components/ui/topbar-action'
import { TokenMeter } from '@/components/ui/token-meter'
import { ContextBudgetBar } from '@/components/ContextBudgetBar'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'

export type ViewMode = 'agent' | 'split' | 'monitor'

export interface AgentTopbarTokens {
  input: number
  output: number
  cached?: number
  trigger?: number
  pulsing?: boolean
}

const VIEW_MODES: { key: ViewMode; label: string }[] = [
  { key: 'agent', label: 'Agent' },
  { key: 'split', label: 'Split' },
  { key: 'monitor', label: 'Monitor' },
]

/** Merged view mode switch + context budget bar. */
function ViewModeSwitch({
  value,
  onValueChange,
  contextBudget,
}: {
  value: ViewMode
  onValueChange: (mode: ViewMode) => void
  contextBudget?: { used: number; max?: number }
}) {
  const preset = useMotionPreset()

  return (
    <div
      role="radiogroup"
      aria-label="View mode"
      className="relative isolate flex h-8 items-center rounded-[10px] border border-(--color-border) bg-(--bg-input) p-0.5 shadow-[inset_0_1px_0_rgb(255_255_255/0.04)]"
    >
      {VIEW_MODES.map(({ key, label }) => (
        <button
          key={key}
          type="button"
          role="radio"
          aria-checked={value === key}
          aria-label={label}
          onClick={() => onValueChange(key)}
          className={cn(
            'relative flex h-7 min-w-[3.2rem] items-center justify-center rounded-[8px] px-2.5 text-xs font-medium outline-none transition-[color,transform] duration-(--motion-fast) active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-(--focus-ring)/40',
            value === key
              ? 'text-(--color-text)'
              : 'text-(--color-text-muted) hover:text-(--color-text-2)',
          )}
        >
          {value === key && (
            <motion.span
              layoutId="view-mode-indicator"
              data-testid="view-mode-indicator"
              aria-hidden="true"
              className="absolute inset-0 -z-10 rounded-[8px] bg-(--color-surface-2) shadow-[0_1px_2px_rgb(0_0_0/0.14),inset_0_1px_0_rgb(255_255_255/0.06)]"
              initial={false}
              transition={preset.spring}
            />
          )}
          <span className="relative z-10">{label}</span>
        </button>
      ))}
      {contextBudget && contextBudget.used > 0 && (
        <>
          <div className="mx-0.5 h-4 w-px bg-(--color-border)" />
          <ContextBudgetBar used={contextBudget.used} max={contextBudget.max} compact />
        </>
      )}
    </div>
  )
}

export interface AgentTopbarActionDescriptor {
  /** Lucide icon component. */
  Icon: LucideIcon
  label?: string
  onClick: () => void
  /** Disable the action (renders muted, blocks click). */
  disabled?: boolean
  /** Native `title` attribute / tooltip text. */
  title?: string
  /** Override default aria-label. */
  ariaLabel?: string
  /** Show a small accent dot to signal an active/in-progress state. */
  indicator?: boolean
  /** Override the indicator dot color (e.g. error red). */
  indicatorClassName?: string
  className?: string
}

export interface AgentTopbarProps {
  /** Token totals; when omitted (or all zero) the TokenMeter is hidden. */
  tokens?: AgentTopbarTokens
  /**
   * Context window budget. When provided, shows a mini usage bar alongside
   * the token meter. `used` = input + output + cached tokens; `max` defaults
   * to 200 000 if omitted.
   */
  contextBudget?: { used: number; max?: number }
  /** Show "Dream…" indicator when the dream loop is running. */
  dreamRunning?: boolean
  /** Current view mode; when undefined the ViewToggle is hidden. */
  viewMode?: ViewMode
  onViewModeChange?: (mode: ViewMode) => void
  /** Force the mobile/desktop layout. Defaults to desktop. */
  isMobile?: boolean
  /**
   * Todos action — opens the task list (legacy topbar trigger).
   * When omitted no todos action is rendered.
   */
  todosAction?: AgentTopbarActionDescriptor
  /** Scheduler action — opens the scheduled-tasks drawer (Ctrl+S). */
  schedulerAction?: AgentTopbarActionDescriptor
  /** Wiki action — opens the wiki drawer (Ctrl+M). */
  wikiAction?: AgentTopbarActionDescriptor
  /** Terminal action — toggles the AI Terminal panel (Ctrl+`). */
  terminalAction?: AgentTopbarActionDescriptor
  /** Files action — typically toggles the workspace files panel. */
  filesAction?: AgentTopbarActionDescriptor
  /** Agents action — typically toggles the agent capabilities sidebar. */
  agentsAction?: AgentTopbarActionDescriptor
  /** Extra actions appended after Agents (rarely needed). */
  extraActions?: React.ReactNode
  className?: string
}

/**
 * Right-side cluster of the agent chat topbar. Always rendered as a
 * shrink-0 flex row so it can sit at the trailing edge of a `min-w-0`
 * left side.
 */
export function AgentTopbar({
  tokens,
  contextBudget,
  dreamRunning = false,
  viewMode,
  onViewModeChange,
  isMobile = false,
  todosAction,
  schedulerAction,
  wikiAction,
  terminalAction,
  filesAction,
  agentsAction,
  extraActions,
  className,
}: AgentTopbarProps) {
  const totalAll = tokens
    ? tokens.input + tokens.output + (tokens.cached ?? 0)
    : 0
  const showTokens = !isMobile && tokens && totalAll > 0
  const showViewToggle = !isMobile && viewMode && onViewModeChange

  return (
    <div
      className={cn(
        'flex shrink-0 items-center gap-1 py-0.5 md:gap-2 md:py-2',
        className,
      )}
    >
      {dreamRunning && (
        <div
          className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-(--color-text-muted)"
          title="Dream is running…"
        >
          <Moon size={11} className="animate-pulse" aria-hidden="true" />
          <span className="hidden sm:inline">Dream…</span>
        </div>
      )}

      {showTokens && tokens && (
        <TokenMeter
          input={tokens.input}
          output={tokens.output}
          cached={tokens.cached}
          trigger={tokens.trigger}
          pulsing={tokens.pulsing}
          className="mr-0.5"
        />
      )}

      {!isMobile && showViewToggle && viewMode && onViewModeChange && (
        <ViewModeSwitch
          value={viewMode}
          onValueChange={onViewModeChange}
          contextBudget={contextBudget}
        />
      )}

      {todosAction && <AgentTopbarActionButton action={todosAction} fallbackIcon={ListChecks} />}
      {schedulerAction && (
        <AgentTopbarActionButton action={schedulerAction} fallbackIcon={CalendarClock} />
      )}
      {wikiAction && (
        <AgentTopbarActionButton action={wikiAction} fallbackIcon={Brain} />
      )}
      {terminalAction && (
        <AgentTopbarActionButton action={terminalAction} fallbackIcon={TerminalSquare} />
      )}
      {filesAction && (
        <AgentTopbarActionButton action={filesAction} fallbackIcon={FolderOpen} />
      )}
      {agentsAction && (
        <AgentTopbarActionButton action={agentsAction} fallbackIcon={Users} />
      )}

      {extraActions}
    </div>
  )
}

function AgentTopbarActionButton({
  action,
  fallbackIcon,
}: {
  action: AgentTopbarActionDescriptor
  fallbackIcon: LucideIcon
}) {
  const Icon = action.Icon ?? fallbackIcon
  return (
    <TopbarAction
      Icon={Icon}
      label={action.label}
      onClick={action.onClick}
      disabled={action.disabled}
      className={action.className}
      title={action.title}
      aria-label={action.ariaLabel ?? action.label ?? action.title}
      indicator={action.indicator}
      indicatorClassName={action.indicatorClassName}
    />
  )
}
