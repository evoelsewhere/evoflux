/**
 * The live status line for a streaming turn.
 *
 * Replaces `StreamingTurnHeader`, which showed only a clock. Everything else
 * on the line was already in the stream and simply had nowhere to be read:
 * turn tokens and cost arrive on their own SSE event after every model call
 * (`app/agent/turn_usage.py`), and what the agent is doing is derivable from
 * the turn's own blocks (`utils/turn-status.ts`).
 *
 *   ✦ Editing main.rs   1m 57s · 1.1k tokens · $0.004
 *
 * It trails the turn rather than heading it, in the slot the footer takes
 * once the turn finishes, so the line always reports on the output above it.
 *
 * It ticks once a second, so it owns its own store subscriptions and stays
 * out of the memoized transcript turn that renders it — the transcript must
 * not re-render on the clock.
 */
import { useEffect, useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { motion } from 'framer-motion'

import { ActivityStatus } from './motion/ActivityStatus'
import { getToolIcon } from './ToolCallGroup'
import { subscribeClock } from './ToolCall'
import { useTeamStore } from '@/stores/useTeamStore'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'
import { formatTurnCost, formatTurnDuration, formatTurnTokens, shortModelName } from '@/utils/turn-meta'
import { liveTurnActivity } from '@/utils/turn-status'
import type { AgentStream, TeamStoreState } from '@/stores/useTeamStore'
import type { ContentBlock } from '@/api/types'

export interface TurnStatusLineProps {
  /** Blocks of the live turn — what the agent is doing is read from these. */
  blocks: ContentBlock[]
  /** Which agent's stream to read. Omitted: the first working one. */
  agentName?: string
  size?: 'roomy' | 'compact'
  className?: string
}

/**
 * The stream this line reports on.
 *
 * Resolution has to be stable for the whole turn. Picking "whichever agent is
 * working" is not: between two activations no stream is working, so the line
 * lost its start time and its spend, and came back reading `0ms` with the
 * previous turn's cost. The view's own agent is the answer, and the scan is
 * only the last resort.
 */
function targetStream(state: TeamStoreState, agentName?: string): AgentStream | null {
  const streams = state.agentStreams ?? {}
  const named = agentName ?? state.activeAgent ?? state.leadName
  if (named && streams[named]) return streams[named]
  for (const stream of Object.values(streams)) {
    if (stream.status === 'working') return stream
  }
  return null
}

/** Subscribe to the shared clock; it pauses in background tabs. */
function useLiveClock(): number {
  // The initializer runs on mount, so the first paint is already current and
  // the effect only has to attach the subscription.
  const [now, setNow] = useState(Date.now)
  useEffect(() => subscribeClock(setNow), [])
  return now
}

/**
 * A four-point spark that turns and breathes while the model has the turn.
 *
 * A generic spinner reads as "the page is loading". This is the agent
 * thinking, so it gets its own glyph in the user's accent colour — two
 * unsynchronised loops (a slow rotation, a faster pulse) so the motion never
 * settles into an obvious repeat.
 */
const SPARK_PATH =
  'M12 1.5c.5 4.2 1.8 6.3 4.6 7.2 2.1.7 4 .9 5.9 1-4.2.5-6.3 1.8-7.2 4.6'
  + '-.7 2.1-.9 4-1 5.9-.5-4.2-1.8-6.3-4.6-7.2-2.1-.7-4-.9-5.9-1 4.2-.5 6.3-1.8 7.2-4.6'
  + '.7-2.1.9-4 1-5.9z'

function ThinkingSpark({ size }: { size: number }) {
  return (
    <motion.svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      className="text-(--color-accent)"
      animate={{ rotate: 360 }}
      transition={{ duration: 3.2, ease: 'linear', repeat: Infinity }}
    >
      <motion.path
        d={SPARK_PATH}
        fill="currentColor"
        style={{ transformOrigin: '50% 50%' }}
        animate={{ scale: [1, 0.7, 1], opacity: [1, 0.55, 1] }}
        transition={{ duration: 1.5, ease: 'easeInOut', repeat: Infinity }}
      />
    </motion.svg>
  )
}

/**
 * The leading glyph: the running tool's own icon, else the thinking spark.
 * Split out so the icon lookup stays an unconditional call rather than a
 * component built inside a conditional expression.
 */
function StatusIcon({
  toolName,
  size,
  animated,
}: {
  toolName: string | null
  size: number
  animated: boolean
}) {
  if (!toolName) {
    if (!animated) {
      return <Loader2 size={size} aria-hidden="true" className="text-(--color-accent)" />
    }
    return <ThinkingSpark size={size} />
  }
  // Same dynamic lookup ToolCallGroupCard makes: the icon comes from the
  // tool name, so it cannot be a statically declared component.
  /* eslint-disable react-hooks/static-components */
  const Icon = getToolIcon(toolName)
  return (
    <Icon
      size={size}
      aria-hidden="true"
      className={cn('text-(--color-accent)', animated && 'animate-pulse')}
    />
  )
  /* eslint-enable react-hooks/static-components */
}

export function TurnStatusLine({
  blocks,
  agentName,
  size = 'roomy',
  className,
}: TurnStatusLineProps) {
  const preset = useMotionPreset()
  const now = useLiveClock()
  const [mountedAt] = useState(() => Date.now())

  // Primitive selectors only: this component re-renders on every usage event
  // and every clock tick, and nothing else should.
  const phase = useTeamStore((state) => targetStream(state, agentName)?.phase ?? null)
  const streamStartedAt = useTeamStore(
    (state) => targetStream(state, agentName)?._turnStartedAt ?? null,
  )
  const tokens = useTeamStore((state) => {
    const usage = targetStream(state, agentName)?.usage
    return (usage?.turnPromptTokens ?? 0) + (usage?.turnCompletionTokens ?? 0)
  })
  const costUsd = useTeamStore(
    (state) => targetStream(state, agentName)?.usage.turnCost?.estimated_usd ?? 0,
  )
  const sessionModel = useTeamStore((state) => state.sessionModel)

  // The turn's own model wins over the session default: a turn that fell back
  // to another model should say so while it is still running, not only in the
  // footer once it has finished.
  const turnModel = useMemo(() => {
    for (let index = blocks.length - 1; index >= 0; index -= 1) {
      const model = blocks[index].extra?.model
      if (typeof model === 'string' && model) return model
    }
    return null
  }, [blocks])
  const modelName = shortModelName(turnModel ?? sessionModel)

  const activity = useMemo(
    () => liveTurnActivity(blocks, phase, modelName),
    [blocks, phase, modelName],
  )

  // The clock must start when the turn did, not when this instance mounted.
  // The runway line and the turn's own line are two mounts of the same turn,
  // and a block-derived start made the elapsed jump backwards at the handover.
  // Keep the earliest start seen while this line is up. The store restarts
  // `_turnStartedAt` on every agent activation, and a turn that pauses and
  // resumes is still one answer to the reader — measured in the app, the
  // elapsed otherwise dropped from 20s back to 580ms mid-answer. The latch
  // resets with the component, which unmounts once the turn really ends.
  const [firstStart, setFirstStart] = useState<number | null>(streamStartedAt)
  if (streamStartedAt !== null && (firstStart === null || streamStartedAt < firstStart)) {
    setFirstStart(streamStartedAt)
  }
  const start = firstStart ?? mountedAt
  const elapsed = formatTurnDuration(Math.max(0, now - start))
  const meta = [elapsed]
  if (tokens > 0) meta.push(`${formatTurnTokens(tokens)} tokens`)
  if (costUsd > 0) meta.push(formatTurnCost(costUsd))

  const animated = preset.intensity !== 'reduced'
  const iconSize = size === 'roomy' ? 15 : 13

  const row = (
    <div
      className={cn(
        'flex min-w-0 items-center gap-2',
        size === 'roomy' ? 'pt-3' : 'pt-2',
        className,
      )}
      role="status"
      aria-label={`${activity.label} — ${meta.join(', ')}`}
    >
      <span className="flex size-4 shrink-0 items-center justify-center">
        <StatusIcon toolName={activity.toolName} size={iconSize} animated={animated} />
      </span>

      <ActivityStatus
        label={activity.label}
        className={cn('min-w-0 truncate', size === 'roomy' ? 'text-xs' : 'text-[11px]')}
        aria-label={activity.label}
      />

      <span className="shrink-0 font-mono text-(--color-text-subtle) text-[11px]">
        {meta.join(' · ')}
      </span>
    </div>
  )

  if (!animated) return row

  // The line is transient by nature, so it leaves by collapsing rather than
  // vanishing: what follows slides up into the space instead of jumping.
  // Callers wrap this in `AnimatePresence` for the exit to run.
  return (
    <motion.div
      className="overflow-hidden"
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      transition={preset.transition}
    >
      {row}
    </motion.div>
  )
}
