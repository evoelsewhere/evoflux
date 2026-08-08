import { useMemo } from 'react'

import { SubagentTaskCard } from '@/components/SubagentTaskCard'
import {
  delegationActivityLabel,
  delegationDisplayStatus,
  delegationHandoff,
  parseDelegationCall,
} from '@/lib/delegation-activity'
import { useTeamStore } from '@/stores/useTeamStore'
import type { ToolCallState } from '@/components/ToolCall/types'

export function DelegationTaskCards({
  args,
  result,
  toolState,
}: {
  args?: string
  result?: string
  toolState: ToolCallState
}) {
  const parsed = useMemo(() => parseDelegationCall(args, result), [args, result])
  const agentStreams = useTeamStore((state) => state.agentStreams)
  const activityLog = useTeamStore((state) => state.activityLog)
  const setActiveAgent = useTeamStore((state) => state.setActiveAgent)

  return (
    <div className="my-2 space-y-1.5">
      {parsed.targets.map((target) => {
        const stream = agentStreams[target.agent]
        const handoff = delegationHandoff(activityLog, stream, target.taskId)
        const status = delegationDisplayStatus({ toolState, stream, handoff })
        return (
          <SubagentTaskCard
            key={target.taskId ?? target.agent}
            agent={target.agent}
            title={parsed.title}
            status={status}
            activity={delegationActivityLabel(status, stream, handoff)}
            taskId={target.taskId}
            isolation={parsed.isolation}
            repoCount={parsed.repoCount}
            onFocus={() => setActiveAgent(target.agent)}
          />
        )
      })}
    </div>
  )
}
