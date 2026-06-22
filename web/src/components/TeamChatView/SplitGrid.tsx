/**
 * SplitGrid — resizable, reorderable, collapsible n-pane layout (split view).
 *
 * ≤4 agents: PanelGroup-based grid with drag handles for resize.
 *   1 → fullscreen
 *   2 → side-by-side columns (1 horizontal resize handle)
 *   3 → big left, two stacked right (horizontal + vertical handles)
 *   4 → 2×2 (1 horizontal + 2 vertical handles)
 *
 * Reorder: ← → arrows in each pane header cycle the agent through positions.
 * Collapse: ↑ button in the pane header hides the body; click ↓ to restore.
 *
 * ≥5 agents: fixed "command center" layout (no resize / reorder controls).
 */
import { useState, useEffect, useCallback } from 'react'
import type { ReactNode } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Panel, Group, Separator } from 'react-resizable-panels'
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

const SPRING_SOFT = [0.34, 1.2, 0.64, 1] as const
const MOTION_BASE_S = 0.24
const MOTION_FAST_S = 0.15
const COMMAND_CENTER_THRESHOLD = 5

function statusPriority(status: AgentStream['status']): number {
  if (status === 'working') return 0
  if (status === 'error') return 2
  return 1
}

// ── Resize handles (defined at module scope for stable identity) ─────────────

function HResizeHandle() {
  return (
    <Separator className="group relative z-10 flex w-2 cursor-col-resize items-center justify-center focus-visible:outline-none">
      <div className="h-10 w-0.5 rounded-full bg-(--color-border-subtle) transition-colors group-hover:bg-(--color-border) group-data-[resize-handle-active]:bg-(--color-accent)" />
    </Separator>
  )
}

function VResizeHandle() {
  return (
    <Separator className="group relative z-10 flex h-2 cursor-row-resize items-center justify-center focus-visible:outline-none">
      <div className="h-0.5 w-10 rounded-full bg-(--color-border-subtle) transition-colors group-hover:bg-(--color-border) group-data-[resize-handle-active]:bg-(--color-accent)" />
    </Separator>
  )
}

export function SplitGrid({
  agentNames, leadName, agentStreams, isContinuing = false, onContinue,
}: SplitGridProps) {
  const prefersReducedMotion = useReducedMotion()

  // User-controlled ordering — new agents appended, gone agents pruned.
  const [orderedNames, setOrderedNames] = useState(agentNames)
  useEffect(() => {
    setOrderedNames((prev) => {
      const nameSet = new Set(agentNames)
      const kept = prev.filter((n) => nameSet.has(n))
      const added = agentNames.filter((n) => !prev.includes(n))
      return [...kept, ...added]
    })
  }, [agentNames])

  const moveLeft = useCallback((name: string) => {
    setOrderedNames((prev) => {
      const i = prev.indexOf(name)
      if (i <= 0) return prev
      const arr = [...prev]
      ;[arr[i - 1], arr[i]] = [arr[i], arr[i - 1]]
      return arr
    })
  }, [])

  const moveRight = useCallback((name: string) => {
    setOrderedNames((prev) => {
      const i = prev.indexOf(name)
      if (i >= prev.length - 1) return prev
      const arr = [...prev]
      ;[arr[i], arr[i + 1]] = [arr[i + 1], arr[i]]
      return arr
    })
  }, [])

  const visibleNames = orderedNames.filter((name) => {
    const stream = agentStreams[name]
    return stream && stream.status !== 'offline'
  })

  if (visibleNames.length === 0) return null

  const enterTransition = prefersReducedMotion
    ? { duration: 0 }
    : { duration: MOTION_BASE_S, ease: SPRING_SOFT }
  const exitTransition = prefersReducedMotion
    ? { duration: 0 }
    : { duration: MOTION_FAST_S, ease: SPRING_SOFT }

  const renderPane = (name: string, fill = 'h-full') => {
    const stream = agentStreams[name]
    if (!stream) return null
    const idx = orderedNames.indexOf(name)
    return (
      <motion.div
        key={name}
        initial={{ opacity: 0, y: 10, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 10, scale: 0.98, transition: exitTransition }}
        transition={enterTransition}
        className={fill}
      >
        <AgentPane
          name={name}
          stream={stream}
          isLead={name === leadName}
          isContinuing={isContinuing && name === leadName}
          onContinue={name === leadName ? onContinue : undefined}
          canMoveLeft={idx > 0}
          canMoveRight={idx < visibleNames.length - 1}
          onMoveLeft={() => moveLeft(name)}
          onMoveRight={() => moveRight(name)}
        />
      </motion.div>
    )
  }

  // ── Command-center (≥5 agents, fixed layout) ──────────────────────────────
  if (
    visibleNames.length >= COMMAND_CENTER_THRESHOLD &&
    leadName &&
    visibleNames.includes(leadName)
  ) {
    const workerNames = visibleNames
      .filter((n) => n !== leadName)
      .sort((a, b) => {
        const pa = statusPriority(agentStreams[a]?.status ?? 'idle')
        const pb = statusPriority(agentStreams[b]?.status ?? 'idle')
        return pa - pb || a.localeCompare(b)
      })

    return (
      <div className="flex h-full gap-2">
        <div className="flex w-2/5 shrink-0 flex-col">
          <AnimatePresence initial={false}>
            {renderPane(leadName, 'min-h-0 flex-1')}
          </AnimatePresence>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="grid grid-cols-2 gap-2 pb-2" style={{ gridAutoRows: '240px' }}>
            <AnimatePresence initial={false}>
              {workerNames.map((name) => renderPane(name))}
            </AnimatePresence>
          </div>
        </div>
      </div>
    )
  }

  // ── Auto-grid (≤4 agents) — PanelGroup with resize handles ────────────────
  const columnCount = Math.ceil(Math.sqrt(visibleNames.length))
  const baseColumnSize = Math.floor(visibleNames.length / columnCount)
  const extraColumns = visibleNames.length % columnCount
  const columns: string[][] = []
  let offset = 0
  for (let col = 0; col < columnCount; col += 1) {
    const size = baseColumnSize + (col >= columnCount - extraColumns ? 1 : 0)
    columns.push(visibleNames.slice(offset, offset + size))
    offset += size
  }

  const defaultColSize = 100 / columns.length

  return (
    <Group orientation="horizontal" style={{ height: '100%' }}>
      {columns.flatMap((column, colIdx) => {
        const nodes: ReactNode[] = []

        if (colIdx > 0) {
          nodes.push(<HResizeHandle key={`hr-${colIdx}`} />)
        }

        nodes.push(
          <Panel key={colIdx} minSize={10} defaultSize={defaultColSize}>
            {column.length === 1 ? (
              <AnimatePresence initial={false}>
                {renderPane(column[0])}
              </AnimatePresence>
            ) : (
              <Group orientation="vertical" style={{ height: '100%' }}>
                {column.flatMap((name, paneIdx) => {
                  const panes: ReactNode[] = []
                  if (paneIdx > 0) {
                    panes.push(<VResizeHandle key={`vr-${colIdx}-${paneIdx}`} />)
                  }
                  panes.push(
                    <Panel
                      key={name}
                      minSize={5}
                      defaultSize={100 / column.length}
                      className="overflow-hidden"
                    >
                      <AnimatePresence initial={false}>
                        {renderPane(name)}
                      </AnimatePresence>
                    </Panel>,
                  )
                  return panes
                })}
              </Group>
            )}
          </Panel>,
        )

        return nodes
      })}
    </Group>
  )
}
