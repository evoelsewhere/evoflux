import { beforeEach, describe, expect, it } from 'vitest'

import {
  appModeForPath,
  isSessionId,
  loadModeRoute,
  restoreLastRouteBeforeRouterMount,
  saveModeRoute,
} from '@/lib/mode-route'
import { STORAGE_KEYS } from '@/lib/storage-keys'

const SESSION = '/06ab9adf-e91d-70da-8000-480ba550eb21'

beforeEach(() => {
  localStorage.clear()
  window.history.replaceState(null, '', '/')
})

describe('mode route persistence', () => {
  it('classifies the two app modes without treating standalone pages as Work', () => {
    expect(appModeForPath(SESSION)).toBe('work')
    expect(appModeForPath('/coding/project/session')).toBe('coding')
    expect(appModeForPath('/telemetry')).toBeNull()
    expect(appModeForPath('/aim')).toBeNull()
    expect(appModeForPath('/aim/project/overview')).toBeNull()
  })

  it('recognises session ids as UUIDs only', () => {
    expect(isSessionId(SESSION.slice(1))).toBe(true)
    expect(isSessionId('settings')).toBe(false)
    expect(isSessionId('')).toBe(false)
  })

  it('keeps direct routes for Work but opens Coding without a session', () => {
    saveModeRoute(SESSION, SESSION)
    saveModeRoute('/coding/project/session', '/coding/project/session')

    expect(loadModeRoute('work')).toBe(SESSION)
    expect(localStorage.getItem(STORAGE_KEYS.modeRoutes.coding)).toBe('/coding')
    expect(loadModeRoute('coding')).toBe('/coding')
  })

  it('rejects a route stored under the wrong mode key', () => {
    localStorage.setItem(STORAGE_KEYS.modeRoutes.coding, SESSION)

    expect(loadModeRoute('coding')).toBeNull()
  })

  it('migrates the saved route from the legacy Forge storage key', () => {
    localStorage.setItem(STORAGE_KEYS.legacyModeRoutes.work, SESSION)

    expect(loadModeRoute('work')).toBe(SESSION)
    expect(localStorage.getItem(STORAGE_KEYS.modeRoutes.work)).toBe(SESSION)
  })

  it('restores Coding at its session-neutral landing page before router mount', () => {
    localStorage.setItem(STORAGE_KEYS.lastRoute, '/coding/project/session')

    restoreLastRouteBeforeRouterMount()

    expect(window.location.pathname).toBe('/coding')
  })

  it('restores a Work session before router mount', () => {
    localStorage.setItem(STORAGE_KEYS.lastRoute, SESSION)

    restoreLastRouteBeforeRouterMount()

    expect(window.location.pathname).toBe(SESSION)
  })

  it('never remembers or restores a stray non-session path like /settings', () => {
    localStorage.setItem(STORAGE_KEYS.lastRoute, '/settings')
    restoreLastRouteBeforeRouterMount()
    expect(window.location.pathname).toBe('/')
    expect(localStorage.getItem(STORAGE_KEYS.lastRoute)).toBeNull()

    localStorage.setItem(STORAGE_KEYS.modeRoutes.work, SESSION)
    saveModeRoute('/settings', '/settings')
    expect(loadModeRoute('work')).toBe(SESSION)

    localStorage.setItem(STORAGE_KEYS.modeRoutes.work, '/settings')
    expect(loadModeRoute('work')).toBeNull()
    expect(localStorage.getItem(STORAGE_KEYS.modeRoutes.work)).toBeNull()
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
    localStorage.setItem(STORAGE_KEYS.modeRoutes.work, SESSION)

    restoreLastRouteBeforeRouterMount()

    expect(window.location.pathname).toBe('/')
    expect(localStorage.getItem(STORAGE_KEYS.lastRoute)).toBeNull()
    // Work's own key is untouched; AIM paths never map to Work.
    expect(loadModeRoute('work')).toBe(SESSION)

    localStorage.setItem(STORAGE_KEYS.modeRoutes.work, '/aim/project/overview')
    expect(loadModeRoute('work')).toBeNull()
    expect(localStorage.getItem(STORAGE_KEYS.modeRoutes.work)).toBeNull()

    // Retired AIM paths must not rewrite Work's storage key.
    localStorage.setItem(STORAGE_KEYS.modeRoutes.work, SESSION)
    saveModeRoute('/aim/project/overview', '/aim/project/overview')
    expect(localStorage.getItem(STORAGE_KEYS.modeRoutes.work)).toBe(SESSION)
  })
})
