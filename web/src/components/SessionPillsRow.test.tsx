import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SessionPillsRow } from './SessionPillsRow'

let prefersReducedMotion = false

vi.mock('@/queries', () => ({
  useRegistryQuery: () => ({
    data: {
      models: [
        { id: 'codex:gpt-5.6-sol', thinking_levels: ['low', 'medium', 'high', 'xhigh'] },
        { id: 'openai:gpt-4o', thinking_levels: ['low', 'high'] },
      ],
    },
  }),
}))

vi.mock('@/hooks/useReducedMotion', () => ({
  useReducedMotion: () => prefersReducedMotion,
}))

vi.mock('./AgentInfoPopover', () => ({
  AgentInfoPopover: () => <button type="button">Agent info</button>,
}))

describe('SessionPillsRow', () => {
  beforeEach(() => {
    prefersReducedMotion = false
  })

  it('renders one stable combined trigger in advanced mode', () => {
    render(
      <SessionPillsRow
        sessionModel="codex:gpt-5.6-sol"
        sessionThinkingLevel="medium"
        sessionFastMode={false}
      />,
    )

    expect(screen.getByRole('button', { name: /model settings: gpt-5\.6-sol, medium/i })).toBeInTheDocument()
    expect(screen.queryByTitle('Fast mode')).not.toBeInTheDocument()
  })

  it('uses None as the lowest thinking effort and never exposes Default', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <SessionPillsRow
        sessionModel="codex:gpt-5.6-sol"
        sessionThinkingLevel={null}
        sessionFastMode={false}
        onSessionModelSettingsChange={onChange}
      />,
    )

    await user.click(screen.getByRole('button', { name: /model settings/i }))
    const slider = screen.getByRole('slider', { name: /thinking effort/i })
    expect(slider).toHaveAttribute('aria-valuetext', 'None')

    fireEvent.keyDown(slider, { key: 'ArrowRight' })
    expect(onChange).toHaveBeenLastCalledWith('codex:gpt-5.6-sol', 'low', false)

    fireEvent.keyDown(slider, { key: 'Home' })
    expect(onChange).toHaveBeenLastCalledWith('codex:gpt-5.6-sol', 'none', false)
    expect(screen.queryByText('Default')).not.toBeInTheDocument()
  })

  it('closes on Escape and restores focus to the stable trigger', async () => {
    const user = userEvent.setup()
    render(
      <SessionPillsRow
        sessionModel="codex:gpt-5.6-sol"
        sessionThinkingLevel="medium"
        sessionFastMode={false}
      />,
    )

    const trigger = screen.getByRole('button', { name: /model settings/i })
    await user.click(trigger)
    expect(screen.getByRole('slider', { name: /thinking effort/i })).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('slider', { name: /thinking effort/i })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('resets unsupported effort and fast mode when the model changes', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <SessionPillsRow
        sessionModel="codex:gpt-5.6-sol"
        sessionThinkingLevel="xhigh"
        sessionFastMode
        onSessionModelSettingsChange={onChange}
      />,
    )

    await user.click(screen.getByRole('button', { name: /model settings/i }))
    await user.click(screen.getByRole('button', { name: /choose model/i }))
    await user.click(screen.getByRole('option', { name: 'openai:gpt-4o' }))

    expect(onChange).toHaveBeenLastCalledWith('openai:gpt-4o', 'none', false)
  })

  it('always renders the advanced combined control', () => {
    render(
      <SessionPillsRow
        sessionModel="codex:gpt-5.6-sol"
        sessionThinkingLevel="medium"
        sessionFastMode
      />,
    )

    expect(screen.getByRole('button', { name: /model settings/i })).toBeInTheDocument()
    expect(screen.queryByTitle('Session model')).not.toBeInTheDocument()
    expect(screen.queryByTitle('Thinking level')).not.toBeInTheDocument()
  })

  it('renders a larger custom effort rail with a stable white thumb', async () => {
    const user = userEvent.setup()
    render(
      <SessionPillsRow
        sessionModel="codex:gpt-5.6-sol"
        sessionThinkingLevel="medium"
        sessionFastMode={false}
      />,
    )

    await user.click(screen.getByRole('button', { name: /model settings/i }))

    expect(screen.getByTestId('thinking-effort-slider')).toHaveAttribute('data-reduced-motion', 'false')
    expect(screen.getByTestId('thinking-effort-slider')).not.toHaveClass('focus-within:ring-2')
    expect(screen.getByTestId('thinking-effort-rail')).toHaveClass('h-3')
    expect(screen.getByTestId('thinking-effort-thumb')).toHaveClass('size-6')
  })

  it('opens the model list as a right-side flyout on hover without replacing effort controls', async () => {
    const user = userEvent.setup()
    render(
      <SessionPillsRow
        sessionModel="codex:gpt-5.6-sol"
        sessionThinkingLevel="medium"
        sessionFastMode={false}
      />,
    )

    await user.click(screen.getByRole('button', { name: /model settings/i }))
    expect(screen.getByRole('dialog')).toHaveAttribute('data-align', 'end')
    expect(screen.queryByRole('listbox', { name: 'Models' })).not.toBeInTheDocument()
    const chooser = screen.getByRole('button', { name: 'Choose model' })
    fireEvent.mouseEnter(chooser)

    expect(screen.getByRole('listbox', { name: 'Models' })).toBeInTheDocument()
    expect(screen.getByTestId('model-flyout')).toHaveClass('w-[min(19rem,calc(100vw-1rem))]')
    expect(screen.getByTestId('model-flyout')).toHaveClass('max-[1180px]:left-0')
    expect(screen.getByTestId('model-flyout')).toHaveClass('max-[1180px]:bottom-[calc(100%+0.5rem)]')
    expect(screen.getByRole('slider', { name: /thinking effort/i })).toBeInTheDocument()
  })

  it('shows deterministic Fast particles only while Fast is enabled', async () => {
    const user = userEvent.setup()
    const { rerender } = render(
      <SessionPillsRow
        sessionModel="codex:gpt-5.6-sol"
        sessionThinkingLevel="medium"
        sessionFastMode
      />,
    )

    await user.click(screen.getByRole('button', { name: /model settings/i }))
    expect(screen.getAllByTestId(/fast-particle-/)).toHaveLength(7)
    expect(screen.getByTestId('fast-mode-zap')).toHaveAttribute('data-fast-active', 'true')

    rerender(
      <SessionPillsRow
        sessionModel="codex:gpt-5.6-sol"
        sessionThinkingLevel="medium"
        sessionFastMode={false}
      />,
    )
    expect(screen.queryByTestId(/fast-particle-/)).not.toBeInTheDocument()
  })

  it('keeps Fast state visible without looping particles in reduced motion', async () => {
    prefersReducedMotion = true
    const user = userEvent.setup()
    render(
      <SessionPillsRow
        sessionModel="codex:gpt-5.6-sol"
        sessionThinkingLevel="high"
        sessionFastMode
      />,
    )

    await user.click(screen.getByRole('button', { name: /model settings/i }))

    expect(screen.getByTestId('thinking-effort-slider')).toHaveAttribute('data-reduced-motion', 'true')
    expect(screen.queryByTestId(/fast-particle-/)).not.toBeInTheDocument()
    expect(screen.getByTestId('fast-static-indicator')).toBeInTheDocument()
  })
})
