import { render, screen, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const storeMock = vi.hoisted(() => ({
  sendMessage: vi.fn(async (_prompt: string) => true),
}))

vi.mock('@/stores/useTeamStore', () => ({
  useTeamStore: (
    selector: (s: { sendMessage: (prompt: string) => Promise<boolean> }) => unknown,
  ) => selector({ sendMessage: storeMock.sendMessage }),
}))

import { UiBlockRenderer } from '@/components/ui/UiBlockRenderer'
import type { UiBlockNode } from '@/components/ui/ui-block-types'

beforeEach(() => {
  storeMock.sendMessage.mockClear()
})

describe('UiBlockRenderer (spec §5.5 / §9.4)', () => {
  it('renders stat cards and progress from block nodes', () => {
    render(
      <UiBlockRenderer
        blocks={
          [
            {
              type: 'stat_cards',
              cards: [
                { label: 'CPU', value: 42, delta: '+3%', delta_tone: 'up' },
                { label: 'Memory', value: '1.2 GB' },
              ],
            },
            { type: 'progress', label: 'Upload', value: 1, max: 4 },
          ] as UiBlockNode[]
        }
        title="metrics"
      />,
    )
    expect(screen.getByText('metrics')).toBeInTheDocument()
    expect(screen.getByText('CPU')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('Upload')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '1')
  })

  it('renders a neutral unsupported card for an unknown node type', () => {
    render(
      <UiBlockRenderer
        blocks={[{ type: 'timeline', entries: [] } as unknown as UiBlockNode]}
      />,
    )
    expect(screen.getByText(/Unsupported block/)).toBeInTheDocument()
  })

  it('button click dispatches send_prompt with the button prompt', async () => {
    const onSendPrompt = vi.fn()
    render(
      <UiBlockRenderer
        blocks={[{ type: 'buttons', buttons: [{ label: 'Approve', prompt: 'approve this plan' }] }]}
        onSendPrompt={onSendPrompt}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    expect(onSendPrompt).toHaveBeenCalledWith('approve this plan')
    expect(await screen.findByText(/Sent/)).toBeInTheDocument()
  })

  it('falls back to the store sendMessage action when no override is given', async () => {
    render(
      <UiBlockRenderer
        blocks={[{ type: 'buttons', buttons: [{ label: 'Run', prompt: 'run the tests' }] }]}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    expect(await screen.findByText(/Sent/)).toBeInTheDocument()
    expect(storeMock.sendMessage).toHaveBeenCalledWith('run the tests')
  })

  it('disables form submit until required fields have values', () => {
    render(
      <UiBlockRenderer
        blocks={[
          {
            type: 'form',
            title: 'Task report',
            fields: [{ name: 'owner', label: 'Owner', kind: 'text' }],
            submit_label: 'Send',
          },
        ]}
        onSendPrompt={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('form submit composes the send prompt from filled fields', () => {
    const onSendPrompt = vi.fn()
    render(
      <UiBlockRenderer
        blocks={[
          {
            type: 'form',
            title: 'Task report',
            fields: [
              { name: 'owner', label: 'Owner', kind: 'text' },
              { name: 'status', label: 'Status', kind: 'select', options: ['done'] },
            ],
            submit_label: 'Send',
          },
        ]}
        onSendPrompt={onSendPrompt}
      />,
    )
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'alice' } })
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(onSendPrompt).toHaveBeenCalledTimes(1)
    expect(onSendPrompt).toHaveBeenCalledWith('Task report:\n- Owner: alice')
  })
})
