import { useMemo } from 'react'

import { SubagentTaskCard } from '@/components/SubagentTaskCard'
import {
  delegationActivityLabel,
  delegationDisplayStatus,
  delegationHandoffMatch,
  parseDelegationCall,
} from '@/lib/delegation-activity'
import { useTeamStore } from '@/stores/useTeamStore'
import { ActivityStatus } from '@/components/motion/ActivityStatus'
import type { ToolCallState } from '@/components/ToolCall/types'

export function DelegationTaskCards({
  args,
  result,
  toolState,
  startedAt,
}: {
  args?: string
  result?: string
  toolState: ToolCallState
  startedAt?: number
}) {
  const parsed = useMemo(() => parseDelegationCall(args, result), [args, result])
  const agentStreams = useTeamStore((state) => state.agentStreams)
  const activityLog = useTeamStore((state) => state.activityLog)
  const sessionWorking = useTeamStore((state) => state.isTeamWorking)
  const leadName = useTeamStore((state) => state.leadName)
  const setActiveAgent = useTeamStore((state) => state.setActiveAgent)
  const leadStream = leadName ? agentStreams[leadName] : undefined
  const leadInboxBlocks = leadStream
    ? [...leadStream.blocks, ...leadStream.currentBlocks]
    : []

  // Confirmation/cancellation attempts do not own a durable task and should
  // not leave a stale queued card in the transcript after the tool resolves.
  if (
    (toolState === 'success' || toolState === 'failed')
    && parsed.targets.every((target) => !target.taskId)
  ) {
    return null
  }

  const targets = parsed.targets.map((target) => {
    const stream = agentStreams[target.agent]
    const handoffMatch = delegationHandoffMatch(
      activityLog,
      stream,
      target.taskId,
      leadInboxBlocks,
    )
    const handoff = handoffMatch?.artifact ?? null
    const status = delegationDisplayStatus({
      toolState,
      stream,
      handoff,
      sessionWorking,
    })
    return { handoff, handoffMatch, status, stream, target }
  })
  const activeCount = targets.filter(
    ({ status }) => status === 'queued' || status === 'running',
  ).length

  return (
    <div className="my-2 space-y-1.5">
      {targets.map(({ handoff, handoffMatch, status, stream, target }) => (
        <SubagentTaskCard
          key={target.taskId ?? target.agent}
          agent={target.agent}
          title={parsed.title}
          status={status}
          activity={delegationActivityLabel(status, stream, handoff)}
          handoff={handoff}
          taskId={target.taskId}
          startedAt={startedAt}
          completedAt={handoffMatch?.receivedAt}
          isolation={parsed.isolation}
          repoCount={parsed.repoCount}
          onFocus={() => setActiveAgent(target.agent)}
        />
      ))}
      {activeCount > 0 && (
        <ActivityStatus
          label={`Waiting for ${activeCount} ${activeCount === 1 ? 'agent' : 'agents'}…`}
          className="px-2.5 py-1 text-xs"
        />
      )}
    </div>
  )
}
