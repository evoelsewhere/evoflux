/**
 * The dialog that carries an update from download to restart.
 *
 * It used to say "Installing…" beside a spinner from the moment the button
 * was pressed until the app restarted — through minutes of download, the
 * verification, and the install itself. A window that says one thing for
 * four minutes is indistinguishable from one that has hung. The install now
 * waits for the user: the download finishes, and the dialog asks.
 */

import { act, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { AppUpdateDialog } from '@/components/AppUpdateDialog'
import type { AppUpdateProgress } from '@/lib/app-updater'
import { useAppUpdaterStore } from '@/stores/useAppUpdaterStore'

const available = {
  status: 'available',
  version: '2.0.2',
  current_version: '2.0.0',
} as const

function downloading(patch: { progress: AppUpdateProgress | null }) {
  useAppUpdaterStore.setState({ available, downloading: true, ...patch })
}

function reset() {
  useAppUpdaterStore.setState({
    available: null,
    downloading: false,
    ready: false,
    restarting: false,
    progress: null,
    hidden: false,
    error: null,
  })
}

describe('AppUpdateDialog', () => {
  beforeEach(reset)

  it('offers the download before anything starts', () => {
    useAppUpdaterStore.setState({ available })
    render(<AppUpdateDialog />)

    expect(screen.getByText('Download update')).toBeTruthy()
    expect(screen.queryByText('Restart now')).toBeNull()
    expect(screen.queryByRole('progressbar')).toBeNull()
  })

  it('shows how much of the download has arrived', () => {
    downloading({ progress: { phase: 'downloading', downloaded: 4_194_304, total: 8_388_608 } })
    render(<AppUpdateDialog />)

    const bar = screen.getByRole('progressbar')
    expect(bar.getAttribute('aria-valuenow')).toBe('50')
    expect(screen.getByText('Downloading 4.0 of 8.0 MB')).toBeTruthy()
    expect(screen.getByText('50%')).toBeTruthy()
  })

  it('does not invent a percentage when the size is unknown', () => {
    // Some release servers send no Content-Length; claiming 0% or 100% would
    // both be lies, so the bar sweeps and the text says what has arrived.
    downloading({ progress: { phase: 'downloading', downloaded: 2_097_152, total: null } })
    render(<AppUpdateDialog />)

    const bar = screen.getByRole('progressbar')
    expect(bar.getAttribute('aria-valuenow')).toBeNull()
    expect(screen.getByText('Downloading 2.0 MB')).toBeTruthy()
  })

  it('names the stage it is in, because they are very different lengths', () => {
    downloading({ progress: { phase: 'verifying' } })
    const view = render(<AppUpdateDialog />)
    expect(screen.getByText('Verifying the signature…')).toBeTruthy()
    expect(screen.getByText('Verifying…')).toBeTruthy()

    view.unmount()
    useAppUpdaterStore.setState({ available, ready: true, restarting: true })
    render(<AppUpdateDialog />)
    expect(screen.getByText('Installing — EvoFlux will restart')).toBeTruthy()
    expect(
      screen.getByText('EvoFlux closes to install the update and opens again when it is done.'),
    ).toBeTruthy()
  })

  it('says a download is starting before the first byte lands', () => {
    downloading({ progress: null })
    render(<AppUpdateDialog />)

    expect(screen.getByText('Starting download…')).toBeTruthy()
    expect(screen.getByRole('progressbar')).toBeTruthy()
  })

  it('asks before restarting once the update is downloaded', () => {
    useAppUpdaterStore.setState({ available, ready: true, progress: { phase: 'ready' } })
    render(<AppUpdateDialog />)

    expect(screen.getByText('EvoFlux update ready to install')).toBeTruthy()
    expect(screen.getByText('Restart now')).toBeTruthy()
    expect(screen.getByText('Install when I quit')).toBeTruthy()
    expect(screen.queryByRole('progressbar')).toBeNull()
  })
})

describe('AppUpdateDialog — getting out of the way', () => {
  beforeEach(reset)

  it('lets a download be put aside instead of trapping the window', () => {
    // The modal used to refuse to close for the whole download: no Later, no
    // close button, and nothing on screen that said how long it would be.
    downloading({ progress: { phase: 'downloading', downloaded: 1, total: 100 } })
    render(<AppUpdateDialog />)

    const later = screen.getByText('Continue in background')
    expect((later as HTMLButtonElement).disabled).toBe(false)

    act(() => useAppUpdaterStore.getState().dismiss())

    const state = useAppUpdaterStore.getState()
    expect(state.hidden).toBe(true)
    // Put aside, not cancelled.
    expect(state.downloading).toBe(true)
    expect(state.available).not.toBeNull()
    expect(screen.queryByRole('progressbar')).toBeNull()
  })

  it('comes back to ask when the download finishes', () => {
    useAppUpdaterStore.setState({ available, downloading: true, hidden: true })
    render(<AppUpdateDialog />)
    expect(screen.queryByRole('progressbar')).toBeNull()

    act(() => useAppUpdaterStore.getState().handleProgress({ phase: 'ready' }))

    expect(useAppUpdaterStore.getState().hidden).toBe(false)
    expect(screen.getByText('Restart now')).toBeTruthy()
  })

  it('will not let the install itself be dismissed', () => {
    useAppUpdaterStore.setState({ available, ready: true, restarting: true })
    render(<AppUpdateDialog />)

    expect((screen.getByText('Install when I quit') as HTMLButtonElement).disabled).toBe(true)

    act(() => useAppUpdaterStore.getState().dismiss())
    expect(useAppUpdaterStore.getState().hidden).toBe(false)
  })
})
