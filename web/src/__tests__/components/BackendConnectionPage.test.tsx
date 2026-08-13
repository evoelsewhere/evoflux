import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BackendConnectionPage } from '@/routes/settings.connection'

const backend = vi.hoisted(() => ({
  getStatus: vi.fn(),
  removeServer: vi.fn(),
  switchToBundled: vi.fn(),
  switchToExternal: vi.fn(),
}))

vi.mock('@/lib/app-backend', () => ({
  getAppBackendStatus: backend.getStatus,
  removeAppBackendServer: backend.removeServer,
  switchToBundledAppBackend: backend.switchToBundled,
  switchToExternalAppBackend: backend.switchToExternal,
}))

vi.mock('@/components/settings/ConductorConnectionSettings', () => ({
  ConductorConnectionSettings: () => <div>Conductor connection</div>,
}))

describe('BackendConnectionPage', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
    backend.getStatus.mockResolvedValue({
      base_url: 'http://127.0.0.1:4082',
      mode: 'bundled',
      sidecar_running: true,
      external: false,
      supports_bundled: true,
      servers: [{
        base_url: 'http://192.168.1.20:4082',
        name: 'Saved backend',
      }],
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200 }))
  })

  afterEach(() => {
    vi.clearAllMocks()
    vi.unstubAllGlobals()
  })

  it('does not expose the unsupported add or edit server form', async () => {
    render(<BackendConnectionPage />)

    expect(await screen.findByText('Saved backend')).toBeInTheDocument()
    expect(screen.queryByText('Add or edit a server')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Server URL')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Access key')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit Saved backend' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Connect' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove Saved backend' })).toBeInTheDocument()
  })
})
