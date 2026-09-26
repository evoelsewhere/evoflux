import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { MacPermissions } from '@/components/ComputerAppViewer/MacPermissions'

const desktop = vi.hoisted(() => ({
  permissions: { required: true, accessibility: false, screen_recording: false },
  invoke: vi.fn(),
}))

vi.mock('@tauri-apps/api/core', () => ({ invoke: desktop.invoke }))
vi.mock('@/hooks/use-platform', () => ({
  getPlatform: () => ({ isTauri: true, os: 'macos', isMacOverlay: true }),
}))

function renderPermissions() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MacPermissions />
    </QueryClientProvider>,
  )
}

describe('MacPermissions', () => {
  beforeEach(() => {
    desktop.permissions = { required: true, accessibility: false, screen_recording: false }
    desktop.invoke.mockReset()
    desktop.invoke.mockImplementation(async (command: string, args?: { kind: string }) => {
      if (command === 'app_computer_permissions') return desktop.permissions
      if (command === 'app_computer_request_permission') {
        if (args?.kind === 'accessibility') {
          desktop.permissions = { ...desktop.permissions, accessibility: true }
        }
        return desktop.permissions
      }
      return undefined
    })
  })

  it('shows what is missing and opens the pane for it', async () => {
    renderPermissions()

    expect(await screen.findAllByText('Not allowed')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: 'Allow Accessibility in System Settings' }))

    await waitFor(() =>
      expect(desktop.invoke).toHaveBeenCalledWith('app_computer_request_permission', {
        kind: 'accessibility',
      }),
    )
    expect(await screen.findByText('Allowed')).toBeTruthy()
  })

  it('offers a restart while Screen Recording is not in effect, however it was allowed', async () => {
    // Allowed from macOS's own prompt or System Settings: nothing pressed here.
    renderPermissions()

    const restart = await screen.findByRole('button', { name: 'Restart EvoFlux' })
    fireEvent.click(restart)

    await waitFor(() => expect(desktop.invoke).toHaveBeenCalledWith('app_computer_restart'))
  })

  it('confirms when everything is granted', async () => {
    desktop.permissions = { required: true, accessibility: true, screen_recording: true }
    renderPermissions()

    expect(
      await screen.findByText('EvoFlux has everything it needs to control apps on this Mac.'),
    ).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Allow/ })).toBeNull()
  })
})
