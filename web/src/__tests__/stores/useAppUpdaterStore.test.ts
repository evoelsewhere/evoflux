import { beforeEach, describe, expect, it, vi } from 'vitest'

const updater = vi.hoisted(() => ({
  checkForAppUpdates: vi.fn(),
  installAppUpdate: vi.fn(),
}))

vi.mock('@/lib/app-updater', () => updater)

import { useAppUpdaterStore } from '@/stores/useAppUpdaterStore'
import { useToastStore } from '@/stores/useToastStore'

describe('useAppUpdaterStore', () => {
  beforeEach(() => {
    updater.checkForAppUpdates.mockReset()
    updater.installAppUpdate.mockReset()
    useAppUpdaterStore.setState({
      available: null,
      checking: false,
      installing: false,
      installError: null,
    })
    useToastStore.setState({ toasts: [] })
  })

  it('shows an in-app toast when EvoFlux is current', async () => {
    updater.checkForAppUpdates.mockResolvedValue({ status: 'up_to_date', version: '0.0.7' })

    await useAppUpdaterStore.getState().check()

    expect(useAppUpdaterStore.getState().available).toBeNull()
    expect(useToastStore.getState().toasts).toEqual([
      expect.objectContaining({
        tone: 'success',
        title: 'EvoFlux is up to date',
        description: 'You already have the latest version (0.0.7).',
      }),
    ])
  })

  it('opens the in-app install dialog when an update is available', async () => {
    updater.checkForAppUpdates.mockResolvedValue({
      status: 'available',
      version: '0.0.8',
      current_version: '0.0.7',
      notes: 'Updater UI polish',
    })

    await useAppUpdaterStore.getState().check()

    expect(useAppUpdaterStore.getState().available).toEqual(
      expect.objectContaining({ status: 'available', version: '0.0.8' }),
    )
    expect(useToastStore.getState().toasts).toHaveLength(0)
  })

  it('keeps the dialog open and reports an install failure in-app', async () => {
    useAppUpdaterStore.getState().handleResult({
      status: 'available',
      version: '0.0.8',
      current_version: '0.0.7',
      notes: null,
    })
    updater.installAppUpdate.mockRejectedValue('signature verification failed')

    await useAppUpdaterStore.getState().install()

    expect(useAppUpdaterStore.getState()).toMatchObject({
      installing: false,
      installError: 'signature verification failed',
      available: expect.objectContaining({ version: '0.0.8' }),
    })
    expect(useToastStore.getState().toasts.at(-1)).toEqual(
      expect.objectContaining({ tone: 'error', title: 'Update installation failed' }),
    )
  })
})
