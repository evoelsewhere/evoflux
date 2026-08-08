import { describe, expect, it } from 'vitest'

import {
  delegationActivityLabel,
  delegationDisplayStatus,
  delegationHandoff,
  delegationHandoffMatch,
  parseDelegationCall,
} from '@/lib/delegation-activity'
import { createDefaultAgentStream } from '@/stores/useTeamStore/defaults'
import type { ActivityItem } from '@/stores/useTeamStore'

const TASK_ID = '0198a1d2-3456-7890-abcd-ef0123456789'

describe('delegation activity', () => {
  it('uses resolved runtime handles and pairs them with durable task IDs', () => {
    const parsed = parseDelegationCall(
      JSON.stringify({
        to: ['executor'],
        goal: 'Audit the session lifecycle',
        isolation: 'worktree',
        target_repos: ['api', 'web'],
      }),
      `Task delegated to executor#1. Task IDs: ${TASK_ID}.`,
    )

    expect(parsed).toEqual({
      targets: [{ agent: 'executor#1', taskId: TASK_ID }],
      title: 'Audit the session lifecycle',
      isolation: 'worktree',
      repoCount: 2,
    })
  })

  it('does not absorb runtime state text into the resolved agent handle', () => {
    const parsed = parseDelegationCall(
      JSON.stringify({ to: ['explorer'], goal: 'Inspect the branch' }),
      `Task delegated to explorer#1. Running now: explorer#1. Task IDs: ${TASK_ID}.`,
    )

    expect(parsed.targets).toEqual([{ agent: 'explorer#1', taskId: TASK_ID }])
  })

  it('does not mark a delegation done merely because team_delegate returned', () => {
    const stream = createDefaultAgentStream()
    expect(delegationDisplayStatus({
      toolState: 'success',
      stream,
      handoff: null,
    })).toBe('queued')

    stream.status = 'working'
    expect(delegationDisplayStatus({
      toolState: 'success',
      stream,
      handoff: null,
    })).toBe('running')
  })

  it('surfaces the active subagent tool in the lead card', () => {
    const stream = createDefaultAgentStream()
    stream.status = 'working'
    stream.currentBlocks.push({
      id: 'tool-1',
      type: 'tool',
      content: '',
      toolName: 'grep',
      toolArgs: JSON.stringify({ query: 'delegation_status' }),
      toolDone: false,
    })

    expect(delegationActivityLabel('running', stream, null)).toBe(
      'grep · delegation_status',
    )
  })

  it('marks the matching final handoff done', () => {
    const stream = createDefaultAgentStream()
    const activity: ActivityItem = {
      id: 'handoff-1',
      kind: 'handoff',
      agent: 'executor#1',
      timestamp: new Date(),
      label: 'executor#1 → EvoFlux',
      artifact: {
        task_id: TASK_ID,
        status: 'final',
        summary: 'Audit completed successfully.',
      },
    }
    const handoff = delegationHandoff([activity], stream, TASK_ID)

    expect(delegationDisplayStatus({
      toolState: 'success',
      stream,
      handoff,
    })).toBe('done')
    expect(delegationActivityLabel('done', stream, handoff)).toBe(
      'Audit completed successfully.',
    )
  })

  it('restores a task handoff and completion time from transcript history', () => {
    const receivedAt = new Date('2026-08-08T10:00:05.000Z')
    const match = delegationHandoffMatch(
      [],
      createDefaultAgentStream(),
      TASK_ID,
      [{
        id: 'historical-handoff',
        type: 'user',
        content: 'Audit completed.',
        timestamp: receivedAt,
        extra: {
          from_agent: 'executor#1',
          _handoff_artifact: {
            task_id: TASK_ID,
            status: 'final',
            summary: 'Audit completed.',
          },
        },
      }],
    )

    expect(match).toEqual({
      artifact: {
        task_id: TASK_ID,
        status: 'final',
        summary: 'Audit completed.',
      },
      receivedAt: receivedAt.getTime(),
    })
  })

  it('keeps isolated changes in review after the final handoff', () => {
    expect(delegationDisplayStatus({
      toolState: 'success',
      stream: createDefaultAgentStream(),
      handoff: { status: 'final', workspace_result: { repositories: [] } },
    })).toBe('review')
  })

  it('keeps partial handoffs running and shows their latest summary', () => {
    const handoff = { status: 'partial', summary: 'Completed the audit; running tests next.' }
    expect(delegationDisplayStatus({
      toolState: 'success',
      stream: createDefaultAgentStream(),
      handoff,
    })).toBe('running')
    expect(delegationActivityLabel('running', undefined, handoff)).toBe(
      'Partial handoff · Completed the audit; running tests next.',
    )
  })
})
