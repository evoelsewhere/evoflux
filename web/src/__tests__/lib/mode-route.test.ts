import { beforeEach, describe, expect, it } from 'vitest'

import {
  appModeForPath,
  loadModeRoute,
  restoreLastRouteBeforeRouterMount,
  saveModeRoute,
} from '@/lib/mode-route'
import { STORAGE_KEYS } from '@/lib/storage-keys'

beforeEach(() => {
  localStorage.clear()
  window.history.replaceState(null, '', '/')
})

describe('mode route persistence', () => {
  it('classifies the two app modes without treating standalone pages as Work', () => {
    expect(appModeForPath('/session-id')).toBe('work')
    expect(appModeForPath('/coding/project/session')).toBe('coding')
    expect(appModeForPath('/telemetry')).toBeNull()
    expect(appModeForPath('/aim')).toBeNull()
    expect(appModeForPath('/aim/project/overview')).toBeNull()
  })

  it('keeps direct routes for Work but opens Coding without a session', () => {
    saveModeRoute('/session-id', '/session-id')
    saveModeRoute('/coding/project/session', '/coding/project/session')

    expect(loadModeRoute('work')).toBe('/session-id')
    expect(localStorage.getItem(STORAGE_KEYS.modeRoutes.coding)).toBe('/coding')
    expect(loadModeRoute('coding')).toBe('/coding')
  })

  it('rejects a route stored under the wrong mode key', () => {
    localStorage.setItem(STORAGE_KEYS.modeRoutes.coding, '/session-id')

    expect(loadModeRoute('coding')).toBeNull()
  })

  it('migrates the saved route from the legacy Forge storage key', () => {
    localStorage.setItem(STORAGE_KEYS.legacyModeRoutes.work, '/session-id')

    expect(loadModeRoute('work')).toBe('/session-id')
    expect(localStorage.getItem(STORAGE_KEYS.modeRoutes.work)).toBe('/session-id')
  })

  it('restores Coding at its session-neutral landing page before router mount', () => {
    localStorage.setItem(STORAGE_KEYS.lastRoute, '/coding/project/session')

    restoreLastRouteBeforeRouterMount()

    expect(window.location.pathname).toBe('/coding')
  })

  it('normalizes a Coding session route saved by an older release', () => {
    localStorage.setItem(
      STORAGE_KEYS.modeRoutes.coding,
      '/coding/project/session',
    )

    expect(loadModeRoute('coding')).toBe('/coding')
  })

  it('ignores retired AIM last-route values so Work is not poisoned', () => {
    localStorage.setItem(STORAGE_KEYS.lastRoute, '/aim/project/overview')
    localStorage.setItem(STORAGE_KEYS.modeRoutes.work, '/session-id')

    restoreLastRouteBeforeRouterMount()

    expect(window.location.pathname).toBe('/')
    expect(localStorage.getItem(STORAGE_KEYS.lastRoute)).toBeNull()
    // Work's own key is untouched; AIM paths never map to Work.
    expect(loadModeRoute('work')).toBe('/session-id')

    localStorage.setItem(STORAGE_KEYS.modeRoutes.work, '/aim/project/overview')
    expect(loadModeRoute('work')).toBeNull()
    expect(localStorage.getItem(STORAGE_KEYS.modeRoutes.work)).toBeNull()

    // Retired AIM paths must not rewrite Work's storage key.
    localStorage.setItem(STORAGE_KEYS.modeRoutes.work, '/session-id')
    saveModeRoute('/aim/project/overview', '/aim/project/overview')
    expect(localStorage.getItem(STORAGE_KEYS.modeRoutes.work)).toBe('/session-id')
  })
})
