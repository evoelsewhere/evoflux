import { act, fireEvent, render, screen } from '@testing-library/react'
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
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }))
    expect(onSendPrompt).toHaveBeenCalledWith('approve this plan')
    expect(await screen.findByText('Sent — the agent will reply in this chat.')).toBeInTheDocument()
  })

  it('falls back to the store sendMessage action when no override is given', async () => {
    render(
      <UiBlockRenderer
        blocks={[{ type: 'buttons', buttons: [{ label: 'Run', prompt: 'run the tests' }] }]}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Run/ }))
    expect(await screen.findByText('Sent — the agent will reply in this chat.')).toBeInTheDocument()
    expect(storeMock.sendMessage).toHaveBeenCalledWith('run the tests')
  })

  it('buttons hint and accessible names explain that each button sends a message', () => {
    render(
      <UiBlockRenderer
        blocks={[
          {
            type: 'buttons',
            buttons: [{ label: 'Approve', prompt: 'approve this plan' }],
            hint: 'Each button sends that message to the agent.',
          },
        ]}
        onSendPrompt={vi.fn()}
      />,
    )
    expect(
      screen.getByRole('button', { name: 'Approve — sends this message to the agent' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Each button sends that message to the agent.')).toBeInTheDocument()
  })

  it('keeps the pending and failed round-trip copy in the status region', async () => {
    let settle: (ok: boolean) => void = () => {}
    storeMock.sendMessage.mockReturnValueOnce(
      new Promise<boolean>((resolve) => {
        settle = resolve
      }),
    )
    render(
      <UiBlockRenderer
        blocks={[{ type: 'buttons', buttons: [{ label: 'Run', prompt: 'run' }] }]}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Run/ }))
    expect(await screen.findByText('Sending…')).toBeInTheDocument()
    await act(async () => {
      settle(false)
    })
    expect(await screen.findByText('Could not send — please try again.')).toBeInTheDocument()
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

  it('form shows its purpose, per-field helpers, and required markers with a blocked hint', () => {
    const onSendPrompt = vi.fn()
    render(
      <UiBlockRenderer
        blocks={[
          {
            type: 'form',
            title: 'Project intake',
            description:
              'Your answers are sent to the agent as one message — it replies right in this chat.',
            fields: [
              {
                name: 'goal',
                label: 'Goal',
                kind: 'text',
                helper: 'One sentence: what should the agent build?',
              },
              { name: 'channel', label: 'Channel', kind: 'select', options: ['slack'] },
            ],
            submit_label: 'Send answers',
          },
        ]}
        onSendPrompt={onSendPrompt}
      />,
    )
    expect(
      screen.getByText(
        'Your answers are sent to the agent as one message — it replies right in this chat.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('One sentence: what should the agent build?')).toBeInTheDocument()

    const goal = screen.getByRole('textbox', { name: 'Goal' })
    expect(goal).toHaveAttribute('aria-required', 'true')
    expect(screen.getByLabelText('Channel')).not.toHaveAttribute('aria-required')
    expect(screen.getByText('*')).toBeInTheDocument()

    // Submit is blocked while the free-text field is empty — and the UI says why.
    expect(screen.getByRole('button', { name: 'Send answers' })).toBeDisabled()
    expect(screen.getByText('Fill in the required (*) fields to send.')).toBeInTheDocument()

    fireEvent.change(goal, { target: { value: 'a task runner' } })
    expect(screen.getByRole('button', { name: 'Send answers' })).toBeEnabled()
    expect(screen.queryByText('Fill in the required (*) fields to send.')).not.toBeInTheDocument()
  })

  it('steps read like a guided sequence with status words and a framing description', () => {
    render(
      <UiBlockRenderer
        blocks={[
          {
            type: 'steps',
            description: 'Follow these four steps to launch your first project.',
            steps: [
              { title: 'Create a project', status: 'done', detail: 'Any name works' },
              { title: 'Add a repository', status: 'active' },
              { title: 'Invite your team', status: 'pending' },
              { title: 'Ship it', status: 'error' },
            ],
          },
        ]}
      />,
    )
    expect(
      screen.getByText('Follow these four steps to launch your first project.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Done')).toBeInTheDocument()
    expect(screen.getByText('Now')).toBeInTheDocument()
    expect(screen.getByText('Next')).toBeInTheDocument()
    expect(screen.getByText('Blocked')).toBeInTheDocument()
    expect(screen.getByText('Add a repository').className).toContain('font-semibold')
    expect(screen.getByText('Create a project').className).not.toContain('font-semibold')
  })

  it('stat cards render the per-card hint under the value', () => {
    render(
      <UiBlockRenderer
        blocks={[{ type: 'stat_cards', cards: [{ label: 'CPU', value: 42, hint: '12% of 8 cores' }] }]}
      />,
    )
    expect(screen.getByText('12% of 8 cores')).toBeInTheDocument()
  })
})

describe('UiBlockRenderer layout/custom dispatch (spec §2/§3)', () => {
  it('dispatches a layout node to UiLayout sections', () => {
    render(
      <UiBlockRenderer
        blocks={[
          {
            type: 'layout',
            orientation: 'columns',
            sections: [
              { title: 'Left', children: [{ type: 'callout', body: 'left note' }] },
              { title: 'Right', children: [{ type: 'progress', label: 'Sync', value: 1, max: 2 }] },
            ],
          },
        ]}
      />,
    )
    expect(screen.getByText('Left')).toBeInTheDocument()
    expect(screen.getByText('left note')).toBeInTheDocument()
    expect(screen.getByText('Right')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '1')
  })

  it('renders nested layouts recursively through renderChild', () => {
    render(
      <UiBlockRenderer
        blocks={[
          {
            type: 'layout',
            orientation: 'stack',
            sections: [
              {
                children: [
                  {
                    type: 'layout',
                    orientation: 'columns',
                    sections: [{ children: [{ type: 'callout', body: 'deep leaf' }] }],
                  },
                ],
              },
            ],
          },
        ]}
      />,
    )
    expect(screen.getByText('deep leaf')).toBeInTheDocument()
  })

  it('falls back to UiCallout for a layout past the depth cap', () => {
    // Hand-edited/legacy tool args can bypass server validation (history
    // args are validated at creation time, not on read); the client mirror
    // must terminate anyway (spec §2.3).
    const deep = { type: 'callout', body: 'leaf' }
    const block = [4, 3, 2, 1].reduce<UiBlockNode>(
      (child) => ({
        type: 'layout',
        orientation: 'stack',
        sections: [{ children: [child] }],
      }),
      deep as UiBlockNode,
    )
    render(<UiBlockRenderer blocks={[block]} />)
    expect(screen.getByText('Layout nested too deep')).toBeInTheDocument()
    expect(screen.queryByText('leaf')).not.toBeInTheDocument()
  })

  it('renders a layout exactly at the depth cap (3 levels)', () => {
    const level3: UiBlockNode = {
      type: 'layout',
      orientation: 'stack',
      sections: [{ children: [{ type: 'callout', body: 'cap leaf' }] }],
    }
    const level2: UiBlockNode = {
      type: 'layout',
      orientation: 'stack',
      sections: [{ children: [level3] }],
    }
    const level1: UiBlockNode = {
      type: 'layout',
      orientation: 'stack',
      sections: [{ children: [level2] }],
    }
    render(<UiBlockRenderer blocks={[level1]} />)
    expect(screen.getByText('cap leaf')).toBeInTheDocument()
  })

  it('dispatches a custom node to the sandboxed widget iframe', () => {
    render(
      <UiBlockRenderer blocks={[{ type: 'custom', html: '<div id="custom-widget">w</div>' }]} />,
    )
    const frame = document.querySelector('iframe')
    expect(frame).not.toBeNull()
    const html = frame?.contentDocument?.body?.innerHTML
      ? frame?.contentDocument?.documentElement?.outerHTML ?? ''
      : frame?.getAttribute('srcdoc') ?? ''
    expect(html).toContain('custom-widget')
    expect(html).toContain('evoflux-widget-tokens')
  })

  it('renders buttons/forms nested inside layout sections with prompt wiring', async () => {
    const onSendPrompt = vi.fn()
    render(
      <UiBlockRenderer
        blocks={[
          {
            type: 'layout',
            orientation: 'columns',
            sections: [
              { children: [{ type: 'buttons', buttons: [{ label: 'Run', prompt: 'run it' }] }] },
            ],
          },
        ]}
        onSendPrompt={onSendPrompt}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /Run/ }))
    expect(onSendPrompt).toHaveBeenCalledWith('run it')
  })
})
