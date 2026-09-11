import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ModeSelector } from '@/components/ModeSelector'
import type { PermissionMode } from '@/api/types'

function open(mode: PermissionMode = 'auto') {
  const onModeChange = vi.fn()
  const view = render(<ModeSelector mode={mode} onModeChange={onModeChange} />)
  fireEvent.click(screen.getByRole('button', { expanded: false }))
  return { ...view, onModeChange, list: screen.getByRole('listbox') }
}

describe('ModeSelector', () => {
  it('states in full what each mode still asks about', () => {
    open()

    // The truncated half used to be the half that mattered: what a mode
    // keeps asking about, and what Bypass gives up.
    expect(
      screen.getByText(/Shell and destructive operations still ask/i),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/deny rules and irreversible-action confirmations do not apply/i),
    ).toBeInTheDocument()
    // Auto and Bypass are no longer described as the same thing.
    expect(
      screen.getByText(/still honours deny rules and confirms irreversible actions/i),
    ).toBeInTheDocument()
  })

  it('takes focus so its keys do not reach the composer behind it', () => {
    const { list } = open()

    expect(document.activeElement).toBe(list)
  })

  it('consumes the number shortcut instead of typing it', () => {
    const { onModeChange, list } = open()

    const event = new KeyboardEvent('keydown', {
      key: '5',
      bubbles: true,
      cancelable: true,
    })
    list.dispatchEvent(event)

    expect(onModeChange).toHaveBeenCalledWith('bypass')
    // Unprevented, this keystroke also landed in the user's unsent message —
    // and the mode it selects is the most permissive one in the list.
    expect(event.defaultPrevented).toBe(true)
  })

  it('moves through the options with the arrow keys', () => {
    const { list, onModeChange } = open('ask')

    // Opens on the active mode, so Enter alone changes nothing.
    expect(list.getAttribute('aria-activedescendant')).toBe(
      screen.getByRole('option', { name: /Ask permissions/ }).id,
    )

    fireEvent.keyDown(list, { key: 'ArrowDown' })
    expect(list.getAttribute('aria-activedescendant')).toBe(
      screen.getByRole('option', { name: /Accept edits/ }).id,
    )

    fireEvent.keyDown(list, { key: 'End' })
    fireEvent.keyDown(list, { key: 'Enter' })
    expect(onModeChange).toHaveBeenCalledWith('bypass')
  })

  it('wraps at both ends rather than stopping', () => {
    const { list } = open('ask')

    fireEvent.keyDown(list, { key: 'ArrowUp' })
    expect(list.getAttribute('aria-activedescendant')).toBe(
      screen.getByRole('option', { name: /Bypass permissions/ }).id,
    )
  })

  it('closes on Escape without changing the mode', () => {
    const { list, onModeChange } = open()

    fireEvent.keyDown(list, { key: 'Escape' })

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(onModeChange).not.toHaveBeenCalled()
  })

  it('keeps options out of the tab order, as a listbox should', () => {
    open()

    for (const option of screen.getAllByRole('option')) {
      expect(option).toHaveAttribute('tabindex', '-1')
    }
  })

  it('marks the trigger for a mode that changes what the agent may do', () => {
    const { container: guarded } = render(
      <ModeSelector mode="ask" onModeChange={vi.fn()} />,
    )
    const { container: neutral } = render(
      <ModeSelector mode="auto" onModeChange={vi.fn()} />,
    )

    // Bypass and Plan have to be legible without opening the menu.
    expect(guarded.querySelector('button')?.className).not.toBe(
      neutral.querySelector('button')?.className,
    )
  })
})
