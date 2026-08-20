import { beforeEach, describe, expect, it, vi } from 'vitest'

const platform = vi.hoisted(() => ({
  current: { isTauri: true, os: 'linux', isMacOverlay: false },
}))
const tauri = vi.hoisted(() => ({ invoke: vi.fn() }))

vi.mock('@/hooks/use-platform', () => ({
  getPlatform: () => platform.current,
}))

vi.mock('@tauri-apps/api/core', () => ({
  invoke: tauri.invoke,
}))

import { checkForAppUpdates, installAppUpdate } from '@/lib/app-updater'

describe('Linux DEB update policy', () => {
  beforeEach(() => {
    tauri.invoke.mockReset()
    platform.current = { isTauri: true, os: 'linux', isMacOverlay: false }
  })

  it('keeps checks package-manager-owned on Linux', async () => {
    await expect(checkForAppUpdates()).rejects.toThrow('newer EvoFlux .deb')
    expect(tauri.invoke).not.toHaveBeenCalled()
  })

  it('does not replace dpkg-owned files through the self updater', async () => {
    await expect(installAppUpdate()).rejects.toThrow('newer EvoFlux .deb')
    expect(tauri.invoke).not.toHaveBeenCalled()
  })
})
