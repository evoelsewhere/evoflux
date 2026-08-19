import { render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useNativeSidebarGlass } from '@/hooks/use-native-sidebar-glass'

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

function GlassSurface() {
  useNativeSidebarGlass()
  return <div>Surface</div>
}

describe('useNativeSidebarGlass', () => {
  afterEach(() => {
    delete document.documentElement.dataset.nativeSidebarGlass
    setTheme.mockClear()
  })

  it('marks the native platform before paint and removes it on cleanup', async () => {
    const view = render(<GlassSurface />)

    expect(document.documentElement.dataset.nativeSidebarGlass).toBe('windows')
    await waitFor(() => expect(setTheme).toHaveBeenCalledWith(null))

    view.unmount()
    expect(document.documentElement.dataset.nativeSidebarGlass).toBeUndefined()
  })
})
