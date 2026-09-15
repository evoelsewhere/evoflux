/**
 * The dialog that waits while an update installs.
 *
 * It used to say "Installing…" beside a spinner from the moment the button
 * was pressed until the app restarted — through minutes of download, the
 * verification, and the install itself. A window that says one thing for
 * four minutes is indistinguishable from one that has hung.
 */

import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { AppUpdateDialog } from '@/components/AppUpdateDialog'
import type { AppUpdateProgress } from '@/lib/app-updater'
import { useAppUpdaterStore } from '@/stores/useAppUpdaterStore'

const available = {
  status: 'available',
  version: '2.0.2',
  current_version: '2.0.0',
} as const

function installing(patch: { progress: AppUpdateProgress | null }) {
  useAppUpdaterStore.setState({ available, installing: true, ...patch })
}

describe('AppUpdateDialog', () => {
  beforeEach(() => {
    useAppUpdaterStore.setState({
      available: null,
      installing: false,
      progress: null,
      installError: null,
    })
  })

  it('offers the update before anything starts', () => {
    useAppUpdaterStore.setState({ available })
    render(<AppUpdateDialog />)

    expect(screen.getByText('Install and restart')).toBeTruthy()
    expect(screen.queryByRole('progressbar')).toBeNull()
  })

  it('shows how much of the download has arrived', () => {
    installing({ progress: { phase: 'downloading', downloaded: 4_194_304, total: 8_388_608 } })
    render(<AppUpdateDialog />)

    const bar = screen.getByRole('progressbar')
    expect(bar.getAttribute('aria-valuenow')).toBe('50')
    expect(screen.getByText('Downloading 4.0 of 8.0 MB')).toBeTruthy()
    expect(screen.getByText('50%')).toBeTruthy()
  })

  it('does not invent a percentage when the size is unknown', () => {
    // Some release servers send no Content-Length; claiming 0% or 100% would
    // both be lies, so the bar sweeps and the text says what has arrived.
    installing({ progress: { phase: 'downloading', downloaded: 2_097_152, total: null } })
    render(<AppUpdateDialog />)

    const bar = screen.getByRole('progressbar')
    expect(bar.getAttribute('aria-valuenow')).toBeNull()
    expect(screen.getByText('Downloading 2.0 MB')).toBeTruthy()
  })

  it('names the stage it is in, because they are very different lengths', () => {
    installing({ progress: { phase: 'verifying' } })
    const view = render(<AppUpdateDialog />)
    expect(screen.getByText('Verifying the signature…')).toBeTruthy()
    expect(screen.getByText('Verifying…')).toBeTruthy()

    view.unmount()
    installing({ progress: { phase: 'installing' } })
    render(<AppUpdateDialog />)
    expect(screen.getByText('Installing — EvoFlux will restart')).toBeTruthy()
    expect(screen.getByText('Do not close EvoFlux — it restarts on its own.')).toBeTruthy()
  })

  it('says a download is starting before the first byte lands', () => {
    installing({ progress: null })
    render(<AppUpdateDialog />)

    expect(screen.getByText('Starting download…')).toBeTruthy()
    expect(screen.getByRole('progressbar')).toBeTruthy()
  })
})
