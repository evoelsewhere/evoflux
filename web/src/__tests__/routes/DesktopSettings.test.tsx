import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DesktopSettingsPage } from '@/routes/settings.desktop'

const desktop = vi.hoisted(() => ({
  os: 'windows' as 'windows' | 'macos',
  isTauri: true,
  settings: { run_on_startup: false, tray_icon: true, keep_awake: false },
  invoke: vi.fn(),
}))

vi.mock('@tauri-apps/api/core', () => ({ invoke: desktop.invoke }))
vi.mock('@/hooks/use-platform', () => {
  const platform = () => ({
    isTauri: desktop.isTauri,
    os: desktop.os,
    isMacOverlay: desktop.isTauri && desktop.os === 'macos',
    isWindowsTitleBar: desktop.isTauri && desktop.os === 'windows',
  })
  return { getPlatform: platform, usePlatform: platform }
})

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <DesktopSettingsPage />
    </QueryClientProvider>,
  )
}

describe('DesktopSettingsPage', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
    desktop.os = 'windows'
    desktop.isTauri = true
    desktop.settings = { run_on_startup: false, tray_icon: true, keep_awake: false }
    desktop.invoke.mockReset()
    desktop.invoke.mockImplementation(
      async (command: string, args?: { patch: Partial<typeof desktop.settings> }) => {
        if (command === 'app_desktop_settings') return desktop.settings
        if (command === 'app_update_desktop_settings') {
          desktop.settings = { ...desktop.settings, ...args?.patch }
          return desktop.settings
        }
        return undefined
      },
    )
  })

  it('shows what the desktop reports and sends one field per change', async () => {
    renderPage()

    const keepAwake = await screen.findByRole('switch', { name: 'Keep computer awake' })
    await waitFor(() => expect(keepAwake.hasAttribute('data-disabled')).toBe(false))
    expect(screen.getByRole('switch', { name: 'Show in system tray' }).getAttribute('aria-checked')).toBe('true')

    fireEvent.click(keepAwake)

    await waitFor(() =>
      expect(desktop.invoke).toHaveBeenCalledWith('app_update_desktop_settings', {
        patch: { keep_awake: true },
      }),
    )
    await waitFor(() => expect(keepAwake.getAttribute('aria-checked')).toBe('true'))
  })

  it('explains that closing the last window quits once the tray icon is off', async () => {
    desktop.settings = { ...desktop.settings, tray_icon: false }
    renderPage()

    expect(
      await screen.findByText(
        'Open EvoFlux when you sign in to this computer. With the tray icon off, it opens its window.',
      ),
    ).toBeTruthy()
  })

  it('calls it the menu bar on macOS', async () => {
    desktop.os = 'macos'
    renderPage()

    expect(await screen.findByRole('switch', { name: 'Show in menu bar' })).toBeTruthy()
  })

  it('stays inert outside the desktop app', () => {
    desktop.isTauri = false
    renderPage()

    expect(screen.getByText('These settings are available in the EvoFlux desktop app.')).toBeTruthy()
    expect(desktop.invoke).not.toHaveBeenCalled()
  })
})
