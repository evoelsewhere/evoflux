import { beforeEach, describe, expect, it, vi } from 'vitest'

const updater = vi.hoisted(() => ({
  checkForAppUpdates: vi.fn(),
  downloadAppUpdate: vi.fn(),
  restartToUpdate: vi.fn(),
}))

vi.mock('@/lib/app-updater', () => updater)

import { useAppUpdaterStore } from '@/stores/useAppUpdaterStore'
import { useToastStore } from '@/stores/useToastStore'

const available = {
  status: 'available',
  version: '0.0.8',
  current_version: '0.0.7',
  notes: null,
} as const

describe('useAppUpdaterStore', () => {
  beforeEach(() => {
    updater.checkForAppUpdates.mockReset()
    updater.downloadAppUpdate.mockReset()
    updater.restartToUpdate.mockReset()
    useAppUpdaterStore.setState({
      available: null,
      checking: false,
      downloading: false,
      ready: false,
      restarting: false,
      progress: null,
      hidden: false,
      error: null,
    })
    useToastStore.setState({ toasts: [] })
  })

  it('stays quiet when EvoFlux is current', async () => {
    updater.checkForAppUpdates.mockResolvedValue({ status: 'up_to_date', version: '0.0.7' })

    await useAppUpdaterStore.getState().check()

    expect(useAppUpdaterStore.getState().available).toBeNull()
    expect(useToastStore.getState().toasts).toEqual([])
  })

  it('opens the in-app dialog when an update is available', async () => {
    updater.checkForAppUpdates.mockResolvedValue({ ...available, notes: 'Updater UI polish' })

    await useAppUpdaterStore.getState().check()

    expect(useAppUpdaterStore.getState().available).toEqual(
      expect.objectContaining({ status: 'available', version: '0.0.8' }),
    )
    expect(useAppUpdaterStore.getState().ready).toBe(false)
    expect(useToastStore.getState().toasts).toHaveLength(0)
  })

  it('goes straight to the restart when the update was downloaded before', () => {
    // A relaunch in the middle of an install used to fetch the whole update
    // again; the shell now finds the staged package during the check.
    useAppUpdaterStore.getState().handleResult({ ...available, ready: true })

    expect(useAppUpdaterStore.getState()).toMatchObject({
      ready: true,
      progress: { phase: 'ready' },
    })
  })

  it('downloads without installing, then waits for the restart', async () => {
    useAppUpdaterStore.getState().handleResult(available)
    updater.downloadAppUpdate.mockResolvedValue(undefined)

    await useAppUpdaterStore.getState().download()

    expect(updater.restartToUpdate).not.toHaveBeenCalled()
    expect(useAppUpdaterStore.getState()).toMatchObject({
      downloading: false,
      ready: true,
      restarting: false,
    })
  })

  it('keeps the dialog open and reports a download failure in-app', async () => {
    useAppUpdaterStore.getState().handleResult(available)
    updater.downloadAppUpdate.mockRejectedValue('signature verification failed')

    await useAppUpdaterStore.getState().download()

    expect(useAppUpdaterStore.getState()).toMatchObject({
      downloading: false,
      ready: false,
      error: 'signature verification failed',
      available: expect.objectContaining({ version: '0.0.8' }),
    })
    expect(useToastStore.getState().toasts.at(-1)).toEqual(
      expect.objectContaining({ tone: 'error', title: 'Update download failed' }),
    )
  })

  it('forgets stale progress when a download fails', async () => {
    updater.downloadAppUpdate.mockRejectedValue(new Error('disk full'))
    useAppUpdaterStore.setState({
      available,
      progress: { phase: 'downloading', downloaded: 10, total: 100 },
    })

    await useAppUpdaterStore.getState().download()

    const state = useAppUpdaterStore.getState()
    expect(state.downloading).toBe(false)
    expect(state.progress).toBeNull()
    expect(state.error).toBe('disk full')
  })

  it('restarts only once the update is ready', async () => {
    useAppUpdaterStore.getState().handleResult(available)

    await useAppUpdaterStore.getState().restart()
    expect(updater.restartToUpdate).not.toHaveBeenCalled()

    useAppUpdaterStore.setState({ ready: true })
    updater.restartToUpdate.mockReturnValue(new Promise(() => {}))
    void useAppUpdaterStore.getState().restart()

    expect(updater.restartToUpdate).toHaveBeenCalledTimes(1)
    expect(useAppUpdaterStore.getState().restarting).toBe(true)
  })

  it('falls back to downloading again when the restart cannot install', async () => {
    useAppUpdaterStore.setState({ available, ready: true })
    updater.restartToUpdate.mockRejectedValue(new Error('No downloaded update is waiting'))

    await useAppUpdaterStore.getState().restart()

    expect(useAppUpdaterStore.getState()).toMatchObject({
      restarting: false,
      ready: false,
      error: 'No downloaded update is waiting',
    })
    expect(useToastStore.getState().toasts.at(-1)).toEqual(
      expect.objectContaining({ tone: 'error', title: 'Update installation failed' }),
    )
  })

  it('carries how far along the update is', () => {
    const store = useAppUpdaterStore.getState()

    store.handleProgress({ phase: 'downloading', downloaded: 1_048_576, total: 8_388_608 })
    expect(useAppUpdaterStore.getState().progress).toEqual({
      phase: 'downloading',
      downloaded: 1_048_576,
      total: 8_388_608,
    })
    // Progress is itself proof a download is running, even if this window
    // was not the one that started it.
    expect(useAppUpdaterStore.getState().downloading).toBe(true)

    store.handleProgress({ phase: 'ready' })
    expect(useAppUpdaterStore.getState()).toMatchObject({ downloading: false, ready: true })

    store.handleProgress({ phase: 'installing' })
    expect(useAppUpdaterStore.getState().restarting).toBe(true)
  })

  it('keeps a ready update when the dialog is put away', () => {
    useAppUpdaterStore.setState({ available, ready: true })

    useAppUpdaterStore.getState().dismiss()

    // It installs when EvoFlux quits, so nothing is forgotten.
    expect(useAppUpdaterStore.getState()).toMatchObject({
      hidden: true,
      ready: true,
      available: expect.objectContaining({ version: '0.0.8' }),
    })
  })
})
