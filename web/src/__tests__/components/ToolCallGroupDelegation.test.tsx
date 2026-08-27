import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ToolCallGroupCard, type ToolBlockGroup } from '@/components/ToolCallGroup'
import { createDefaultAgentStream } from '@/stores/useTeamStore/defaults'
import { useTeamStore } from '@/stores/useTeamStore'

const TASK_ID = '0198a1d2-3456-7890-abcd-ef0123456789'

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })

  const lead = createDefaultAgentStream()
  lead.blocks.push({
    id: 'handoff',
    type: 'user',
    content: 'The current branch is main.',
    timestamp: new Date(6_000),
    extra: {
      from_agent: 'explorer#1',
      _handoff_artifact: {
        task_id: TASK_ID,
        status: 'final',
        summary: 'The current branch is main.',
        confidence: 1,
      },
    },
  })
  useTeamStore.setState({
    leadName: 'lead',
    isTeamWorking: false,
    agentStreams: {
      lead,
      'explorer#1': createDefaultAgentStream(),
    },
    activityLog: [{
      id: 'delegation',
      kind: 'delegation',
      agent: 'lead',
      timestamp: new Date(1_000),
      label: 'Delegated task',
      meta: { from_agent: 'lead', to_agents: ['explorer#1'], task_ids: [TASK_ID] },
    }],
  })
})

describe('ToolCallGroup delegation lifecycle', () => {
  it('keeps the task status and result visible while technical tools stay collapsed', () => {
    const group: ToolBlockGroup = {
      kind: 'group',
      id: 'tool-group-ask',
      toolName: 'ask_user',
      blocks: [
        {
          id: 'ask',
          type: 'tool',
          content: '',
          toolName: 'ask_user',
          toolArgs: '{}',
          toolDone: true,
          toolResult: 'confirmed',
        },
        {
          id: 'delegate',
          type: 'tool',
          content: '',
          toolName: 'team_delegate',
          toolArgs: JSON.stringify({
            to: ['explorer'],
            title: 'Identify the current Git branch.',
          }),
          toolDone: true,
          toolResult: `Task delegated to explorer#1. Task IDs: ${TASK_ID}.`,
          startedAt: 1_000,
        },
      ],
    }

    render(<ToolCallGroupCard group={group} />)

    expect(screen.getByRole('button', { name: 'Expand Used tools, 1 action' })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
    expect(screen.getByText('lead delegated → explorer#1')).toBeInTheDocument()
    expect(screen.getByText('The current branch is main.')).toBeInTheDocument()
    expect(screen.getByLabelText('Elapsed 5s')).toBeInTheDocument()
    expect(screen.getByText('done')).toBeInTheDocument()
  })

  it('shows an unfinished offline task as paused instead of waiting forever', () => {
    const lead = createDefaultAgentStream()
    const member = createDefaultAgentStream()
    member.status = 'offline'
    useTeamStore.setState({
      leadName: 'lead',
      isTeamWorking: false,
      agentStreams: { lead, 'explorer#1': member },
      activityLog: [],
    })

    const group: ToolBlockGroup = {
      kind: 'group',
      id: 'tool-group-delegate',
      toolName: 'team_delegate',
      blocks: [{
        id: 'delegate',
        type: 'tool',
        content: '',
        toolName: 'team_delegate',
        toolArgs: JSON.stringify({
          to: ['explorer'],
          title: 'Identify the current Git branch.',
        }),
        toolDone: true,
        toolResult: `Task delegated to explorer#1. Task IDs: ${TASK_ID}.`,
        startedAt: 1_000,
      }],
    }

    render(<ToolCallGroupCard group={group} />)

    expect(screen.getByText('paused')).toBeInTheDocument()
    expect(screen.getByText('Session stopped before final handoff · resume to continue')).toBeInTheDocument()
    expect(screen.queryByText(/Waiting for \d+ agents?/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/Elapsed/)).not.toBeInTheDocument()
  })
})
