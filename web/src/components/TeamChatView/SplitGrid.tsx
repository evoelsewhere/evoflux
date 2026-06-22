/**
 * SplitGrid — automatic n-pane grid layout for the `split` view mode.
 *
 * ≤4 agents: automatic column grid (lead treated equally, columns by sqrt).
 *
 *   1 → fullscreen
 *   2 → side-by-side columns
 *   3 → big left, two stacked right
 *   4 → 2×2
 *
 * ≥5 agents: "command center" layout
 *   - Lead agent: dedicated left column (40% width), full height.
 *   - Worker agents: right side, 2-column scrollable grid, each card 240px.
 *   - Workers sorted by activity: working → idle/error.
 *
 * Spawn / dismiss animations are driven by framer-motion: panes fade + scale
 * in on mount, fade + scale out on unmount (offline). The dismissed pane
 * keeps its slot during its exit animation; remaining panes reflow via CSS
 * flex once the unmount completes. We intentionally avoid `layout` here so
 * external container resizes (e.g. sidebar collapse) don't trigger pane
 * layout animations.
 */
import { AnimatePresence, motion } from 'framer-motion'
import { AgentPane } from '../AgentPane'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import type { AgentStream } from '@/stores/useTeamStore'

interface SplitGridProps {
  agentNames: string[]
  leadName: string | null
  agentStreams: Record<string, AgentStream>
  isContinuing?: boolean
  onContinue?: () => void
}

// Easing + durations mirror tokens in index.css so the motion matches sibling
// animations (tool-row-enter, done-pulse, etc.). Per styling-specs/motion.md
// (Split pane enter / exit), exit is faster than enter so dismissal stays
// readable without delaying the next interaction.
const SPRING_SOFT = [0.34, 1.2, 0.64, 1] as const
const MOTION_BASE_S = 0.24 // matches --motion-base (240ms)
const MOTION_FAST_S = 0.15 // matches --motion-fast (150ms)

// At this agent count or above, switch to the command-center layout.
const COMMAND_CENTER_THRESHOLD = 5

// Working agents float to the top of the worker grid; ties broken by name.
function statusPriority(status: AgentStream['status']): number {
  if (status === 'working') return 0
  if (status === 'error') return 2
  return 1 // idle and everything else
}

export function SplitGrid({
  agentNames, leadName, agentStreams, isContinuing = false, onContinue,
}: SplitGridProps) {
  const prefersReducedMotion = useReducedMotion()

  const visibleAgentNames = agentNames.filter((name) => {
    const stream = agentStreams[name]
    return stream && stream.status !== 'offline'
  })

  if (visibleAgentNames.length === 0) return null

  const enterTransition = prefersReducedMotion
    ? { duration: 0 }
    : { duration: MOTION_BASE_S, ease: SPRING_SOFT }
  const exitTransition = prefersReducedMotion
    ? { duration: 0 }
    : { duration: MOTION_FAST_S, ease: SPRING_SOFT }

  // compact=true → pane fills its CSS grid cell (command-center workers).
  // compact=false → pane grows via flex-1 in the column layout.
  const renderPanel = (name: string, compact?: boolean) => {
    const stream = agentStreams[name]
    if (!stream) return null
    return (
      <motion.div
        key={name}
        initial={{ opacity: 0, y: 10, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 10, scale: 0.98, transition: exitTransition }}
        transition={enterTransition}
        className={compact ? 'h-full' : 'min-h-0 flex-1'}
      >
        <AgentPane
          name={name}
          stream={stream}
          isLead={name === leadName}
          isContinuing={isContinuing && name === leadName}
          onContinue={name === leadName ? onContinue : undefined}
        />
      </motion.div>
    )
  }

  // ── Command-center layout (≥5 agents) ─────────────────────────────────────
  if (
    visibleAgentNames.length >= COMMAND_CENTER_THRESHOLD &&
    leadName &&
    visibleAgentNames.includes(leadName)
  ) {
    const workerNames = visibleAgentNames
      .filter((n) => n !== leadName)
      .sort((a, b) => {
        const pa = statusPriority(agentStreams[a]?.status ?? 'idle')
        const pb = statusPriority(agentStreams[b]?.status ?? 'idle')
        return pa - pb || a.localeCompare(b)
      })

    return (
      <div className="flex h-full gap-3">
        {/* Lead agent — fixed-width left column, full height */}
        <div className="flex w-2/5 shrink-0 flex-col">
          <AnimatePresence initial={false}>
            {renderPanel(leadName, false)}
          </AnimatePresence>
        </div>

        {/* Worker grid — 2-column, independently scrollable */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div
            className="grid grid-cols-2 gap-3 pb-3"
            style={{ gridAutoRows: '240px' }}
          >
            <AnimatePresence initial={false}>
              {workerNames.map((name) => renderPanel(name, true))}
            </AnimatePresence>
          </div>
        </div>
      </div>
    )
  }

  // ── Auto-grid layout (≤4 agents, unchanged) ───────────────────────────────
  const columnCount = Math.ceil(Math.sqrt(visibleAgentNames.length))
  const baseColumnSize = Math.floor(visibleAgentNames.length / columnCount)
  const extraColumns = visibleAgentNames.length % columnCount
  const columns: string[][] = []
  let offset = 0

  for (let col = 0; col < columnCount; col += 1) {
    const size = baseColumnSize + (col >= columnCount - extraColumns ? 1 : 0)
    columns.push(visibleAgentNames.slice(offset, offset + size))
    offset += size
  }

  return (
    <div className="flex h-full flex-col gap-3 lg:flex-row">
      {columns.map((column, idx) => (
        <div key={idx} className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
          <AnimatePresence initial={false}>
            {column.map((name) => renderPanel(name))}
          </AnimatePresence>
        </div>
      ))}
    </div>
  )
}
