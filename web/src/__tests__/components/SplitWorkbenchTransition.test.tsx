import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SplitWorkbench } from '@/components/TeamChatView/SplitWorkbench'
import { createDefaultAgentStream } from '@/stores/useTeamStore/defaults'

vi.mock('@/components/AgentPane', () => ({
  AgentPane: ({ name }: { name: string }) => (
    <div data-testid="agent-pane">{name} transcript</div>
  ),
}))

vi.mock('@/lib/motion', () => ({
  useMotionPreset: () => ({
    distance: 0,
    transition: { duration: 0 },
    spring: { duration: 0 },
  }),
}))

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('SplitWorkbench transition staging', () => {
  it('paints the Split shell before mounting the transcript', () => {
    const frames = new Map<number, FrameRequestCallback>()
    let frameId = 0
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frameId += 1
      frames.set(frameId, callback)
      return frameId
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => {
      frames.delete(id)
    })

    render(
      <SplitWorkbench
        agentNames={['lead', 'explorer']}
        leadName="lead"
        activeAgent="lead"
        agentStreams={{
          lead: createDefaultAgentStream(),
          explorer: createDefaultAgentStream(),
        }}
        onSelectAgent={vi.fn()}
      />,
    )

    expect(screen.getByRole('status', { name: 'Preparing conversation' })).toBeVisible()
    expect(screen.queryByTestId('agent-pane')).not.toBeInTheDocument()

    act(() => {
      const [id, callback] = frames.entries().next().value as [number, FrameRequestCallback]
      frames.delete(id)
      callback(16)
    })
    expect(screen.queryByTestId('agent-pane')).not.toBeInTheDocument()

    act(() => {
      const [id, callback] = frames.entries().next().value as [number, FrameRequestCallback]
      frames.delete(id)
      callback(32)
    })
    expect(screen.getByTestId('agent-pane')).toHaveTextContent('lead transcript')
  })
})
