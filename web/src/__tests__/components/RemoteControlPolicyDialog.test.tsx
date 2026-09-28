import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RemoteControlPolicyDialog } from '@/components/settings/RemoteControlPolicyDialog'
import { isRemoteControlPolicyAcknowledged } from '@/lib/remote-control-policy'
import { STORAGE_KEYS } from '@/lib/storage-keys'

beforeEach(() => {
  localStorage.clear()
})

describe('RemoteControlPolicyDialog', () => {
  it('continues without remembering when the box is left unticked', () => {
    const onAccept = vi.fn()
    render(<RemoteControlPolicyDialog open onAccept={onAccept} onLeave={vi.fn()} />)

    expect(screen.getByText('Before you use Remote Control')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'I understand' }))

    expect(onAccept).toHaveBeenCalledOnce()
    expect(isRemoteControlPolicyAcknowledged()).toBe(false)
  })

  it('remembers the acknowledgement when asked not to show again', () => {
    const onAccept = vi.fn()
    render(<RemoteControlPolicyDialog open onAccept={onAccept} onLeave={vi.fn()} />)

    fireEvent.click(screen.getByRole('checkbox', { name: /Don.t show this again/ }))
    fireEvent.click(screen.getByRole('button', { name: 'I understand' }))

    expect(onAccept).toHaveBeenCalledOnce()
    expect(localStorage.getItem(STORAGE_KEYS.remoteControl.policyAcknowledged)).toBe('1')
    expect(isRemoteControlPolicyAcknowledged()).toBe(true)
  })

  it('leaves the page from Go back', () => {
    const onLeave = vi.fn()
    render(<RemoteControlPolicyDialog open onAccept={vi.fn()} onLeave={onLeave} />)

    fireEvent.click(screen.getByRole('button', { name: 'Go back' }))

    expect(onLeave).toHaveBeenCalledOnce()
    expect(isRemoteControlPolicyAcknowledged()).toBe(false)
  })
})
