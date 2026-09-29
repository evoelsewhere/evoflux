import { waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const platform = vi.hoisted(() => ({
  isTauri: true,
  os: 'windows' as const,
  isMacOverlay: false,
}))
const setTheme = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))

vi.mock('@/hooks/use-platform', () => ({
  usePlatform: () => platform,
}))

vi.mock('@/hooks/useThemePreference', () => ({
  useThemePreference: () => ({ preference: 'system' }),
}))

vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: () => ({ setTheme }),
}))

function stubPlatformVersion(platformVersion: string | undefined) {
  Object.defineProperty(navigator, 'userAgentData', {
    configurable: true,
    value:
      platformVersion === undefined
        ? undefined
        : { getHighEntropyValues: vi.fn().mockResolvedValue({ platformVersion }) },
  })
}

// The Windows version probe is cached per module, so each case loads a fresh copy.
async function renderSurface() {
  vi.resetModules()
  const { render } = await import('@testing-library/react')
  const { useNativeSidebarGlass } = await import('@/hooks/use-native-sidebar-glass')
  function GlassSurface() {
    useNativeSidebarGlass()
    return <div>Surface</div>
  }
  return render(<GlassSurface />)
}

describe('useNativeSidebarGlass', () => {
  afterEach(() => {
    delete document.documentElement.dataset.nativeSidebarGlass
    delete document.documentElement.dataset.nativeSidebarMaterial
    Reflect.deleteProperty(navigator, 'userAgentData')
    setTheme.mockClear()
  })

  it('marks the native platform before paint and removes it on cleanup', async () => {
    stubPlatformVersion(undefined)
    const view = await renderSurface()

    expect(document.documentElement.dataset.nativeSidebarGlass).toBe('windows')
    await waitFor(() => expect(setTheme).toHaveBeenCalledWith(null))
    expect(document.documentElement.dataset.nativeSidebarMaterial).toBeUndefined()

    view.unmount()
    expect(document.documentElement.dataset.nativeSidebarGlass).toBeUndefined()
  })

  it('flags the untinted Acrylic material on Windows 10', async () => {
    stubPlatformVersion('10.0.0')
    const view = await renderSurface()

    await waitFor(() =>
      expect(document.documentElement.dataset.nativeSidebarMaterial).toBe('acrylic'),
    )

    view.unmount()
    expect(document.documentElement.dataset.nativeSidebarMaterial).toBeUndefined()
  })

  it('leaves Windows 11 on the Mica path', async () => {
    stubPlatformVersion('15.0.0')
    await renderSurface()

    await waitFor(() => expect(setTheme).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(document.documentElement.dataset.nativeSidebarMaterial).toBeUndefined()
  })
})
