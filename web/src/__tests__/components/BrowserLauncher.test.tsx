import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import type { PreviewTarget, PreviewTargetListResponse } from '@/api/types'
import { BrowserLauncher } from '@/components/BrowserViewer/BrowserLauncher'

const api = vi.hoisted(() => ({
  getPreviewTargets: vi.fn(),
  startPreviewTarget: vi.fn(),
  stopPreviewTarget: vi.fn(),
}))

vi.mock('@/api/client', () => api)

function target(overrides: Partial<PreviewTarget> = {}): PreviewTarget {
  return {
    name: 'web',
    port: 5173,
    url: 'http://localhost:5173',
    command: 'npm run dev',
    cwd: 'web',
    depends_on: null,
    configured: true,
    running: false,
    reused: false,
    pid: null,
    ...overrides,
  }
}

function listing(
  targets: PreviewTarget[],
  overrides: Partial<PreviewTargetListResponse> = {},
): PreviewTargetListResponse {
  return {
    workspace: '/repo',
    source: '/repo/.evoflux/launch.json',
    suggested_source: '.evoflux/launch.json',
    error: null,
    targets,
    ...overrides,
  }
}

function renderLauncher(onOpen = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <BrowserLauncher workspace="/repo" onOpen={onOpen} />
    </QueryClientProvider>,
  )
  return onOpen
}

describe('BrowserLauncher', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getPreviewTargets.mockResolvedValue(listing([target()]))
  })

  it('starts a stopped server and opens the URL it reports', async () => {
    api.startPreviewTarget.mockResolvedValue({
      ok: true,
      message: "Server 'web' ready on http://localhost:5173 (pid 42).",
      url: 'http://localhost:5173',
    })
    const onOpen = renderLauncher()

    fireEvent.click(await screen.findByRole('button', { name: 'Start web' }))

    await waitFor(() => expect(onOpen).toHaveBeenCalledWith('http://localhost:5173'))
    expect(api.startPreviewTarget).toHaveBeenCalledWith('/repo', 'web')
  })

  it('opens a server that is already running instead of starting a second copy', async () => {
    api.getPreviewTargets.mockResolvedValue(
      listing([target({ running: true, pid: 42 })]),
    )
    const onOpen = renderLauncher()

    fireEvent.click(await screen.findByRole('button', { name: 'Open web' }))

    await waitFor(() => expect(onOpen).toHaveBeenCalledWith('http://localhost:5173'))
    expect(api.startPreviewTarget).not.toHaveBeenCalled()
  })

  it('offers no stop button for a server it did not spawn', async () => {
    api.getPreviewTargets.mockResolvedValue(
      listing([target({ running: true, reused: true })]),
    )
    renderLauncher()

    expect(await screen.findByRole('button', { name: 'Open web' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Stop web' })).toBeNull()
  })

  it('shows the log tail when a server fails to start', async () => {
    api.startPreviewTarget.mockResolvedValue({
      ok: false,
      message: "Server 'web' exited with code 1 before opening port 5173.\nEADDRINUSE",
      url: null,
    })
    const onOpen = renderLauncher()

    fireEvent.click(await screen.findByRole('button', { name: 'Start web' }))

    expect(await screen.findByText(/EADDRINUSE/)).toBeInTheDocument()
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('points at the config file when the workspace declares no servers', async () => {
    api.getPreviewTargets.mockResolvedValue(listing([], { source: null }))
    renderLauncher()

    expect(
      await screen.findByText(/Create \.evoflux\/launch\.json/),
    ).toBeInTheDocument()
  })
})
