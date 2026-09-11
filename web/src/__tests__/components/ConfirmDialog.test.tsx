import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import type { ConfirmRequest } from '@/hooks/use-confirm'

function request(overrides: Partial<ConfirmRequest> = {}): ConfirmRequest {
  return {
    title: 'Uninstall demo-plugin?',
    description: 'The installed package is removed and its MCP servers stop.',
    confirmLabel: 'Uninstall',
    destructive: true,
    onConfirm: vi.fn(),
    ...overrides,
  }
}

describe('ConfirmDialog', () => {
  it('states what the action does, not just that it is irreversible', () => {
    render(<ConfirmDialog request={request()} onClose={vi.fn()} />)

    expect(screen.getByText('Uninstall demo-plugin?')).toBeVisible()
    expect(
      screen.getByText('The installed package is removed and its MCP servers stop.'),
    ).toBeVisible()
    expect(screen.getByRole('button', { name: 'Uninstall' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeVisible()
  })

  it('runs the action only when it is confirmed', () => {
    const onConfirm = vi.fn()
    const onClose = vi.fn()
    render(
      <ConfirmDialog request={request({ onConfirm })} onClose={onClose} />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onConfirm).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'Uninstall' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('takes the caller cancel wording when one is given', () => {
    render(
      <ConfirmDialog
        request={request({ confirmLabel: 'Discard changes', cancelLabel: 'Keep editing' })}
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: 'Keep editing' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
  })

  it('cannot be dismissed while the action is running', () => {
    const onClose = vi.fn()
    render(<ConfirmDialog request={request()} busy onClose={onClose} />)

    const confirm = screen.getByRole('button', { name: 'Uninstall' })
    expect(confirm).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
  })
})
