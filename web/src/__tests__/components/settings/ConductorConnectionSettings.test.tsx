import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ConductorConnectionSettings } from '@/components/settings/ConductorConnectionSettings'

const mocks = vi.hoisted(() => ({
  getSettings: vi.fn(),
  getStatus: vi.fn(),
  updateSettings: vi.fn(),
  connect: vi.fn(),
  disconnect: vi.fn(),
  sync: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  getConductorSettings: mocks.getSettings,
  getConductorStatus: mocks.getStatus,
  updateConductorSettings: mocks.updateSettings,
  connectConductor: mocks.connect,
  disconnectConductor: mocks.disconnect,
  syncConductor: mocks.sync,
}))

const settings = {
  enabled: true,
  url: '',
  machine_credential_path: null,
  sync_interval_seconds: 60,
  heartbeat_interval_seconds: 60,
  request_timeout_seconds: 15,
  enforcement_mode: 'report',
}

const disconnectedStatus = {
  enabled: true,
  enrolled: false,
  state: 'disconnected',
  installation_id: null,
  project_id: null,
  project_name: null,
  project_display_name: null,
  project_logo_url: null,
  member_display_name: null,
  member_primary_role: null,
  collection_level: null,
  heartbeat_interval_seconds: 60,
  last_heartbeat_at: null,
  last_sync_at: null,
  last_success_at: null,
  manifest_revision: null,
  etag: null,
  offline: false,
  maintenance_required: false,
  error: null,
  resources: [],
}

const connectedStatus = {
  ...disconnectedStatus,
  enrolled: true,
  state: 'connected',
  installation_id: 'installation-1',
  project_id: 'project-1',
  project_name: 'evo-platform',
  project_display_name: 'Evo Platform',
  member_display_name: 'Mai Nguyen',
  member_primary_role: 'contribute',
  collection_level: 'L1',
}

describe('ConductorConnectionSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.getSettings.mockResolvedValue(settings)
    mocks.getStatus.mockResolvedValue(disconnectedStatus)
    mocks.updateSettings.mockImplementation(async (value) => value)
    mocks.connect.mockResolvedValue(connectedStatus)
    mocks.disconnect.mockResolvedValue(disconnectedStatus)
    mocks.sync.mockResolvedValue(connectedStatus)
  })

  it('validates the URL and evc_ token before connecting', async () => {
    render(<ConductorConnectionSettings />)

    const url = await screen.findByLabelText('Conductor URL')
    const token = screen.getByLabelText('V1 connection token')
    const connect = screen.getByRole('button', { name: 'Connect' })

    fireEvent.change(url, { target: { value: 'conductor.internal/api' } })
    fireEvent.change(token, { target: { value: 'wrong-token' } })

    expect(screen.getByText('Enter an http:// or https:// URL.')).toBeVisible()
    expect(screen.getByText('Connection tokens must start with evc_.')).toBeVisible()
    expect(connect).toBeDisabled()
    expect(mocks.connect).not.toHaveBeenCalled()
  })

  it('connects, clears the submitted token, and renders server-owned branding', async () => {
    render(<ConductorConnectionSettings />)

    fireEvent.change(await screen.findByLabelText('Conductor URL'), {
      target: { value: 'http://127.0.0.1:4700' },
    })
    fireEvent.change(screen.getByLabelText('V1 connection token'), {
      target: { value: 'evc_scoped-secret' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }))

    await screen.findByText('Evo Platform')
    expect(mocks.connect).toHaveBeenCalledWith('evc_scoped-secret')
    expect(screen.queryByDisplayValue('evc_scoped-secret')).not.toBeInTheDocument()
    expect(screen.getByText(/Mai Nguyen · contribute · Privacy L1/)).toBeVisible()
    expect(screen.queryByLabelText('V1 connection token')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Conductor URL')).not.toBeInTheDocument()
    expect(screen.getByText('E')).toBeVisible()
  })

  it('disconnects explicitly and returns to connection inputs', async () => {
    mocks.getSettings.mockResolvedValue({ ...settings, url: 'http://127.0.0.1:4700' })
    mocks.getStatus.mockResolvedValue(connectedStatus)
    render(<ConductorConnectionSettings />)

    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))

    await waitFor(() => expect(mocks.disconnect).toHaveBeenCalledTimes(1))
    expect(await screen.findByLabelText('V1 connection token')).toBeVisible()
    expect(screen.getByText('Disconnected')).toBeVisible()
  })
})
