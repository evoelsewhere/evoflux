import { beforeEach, describe, expect, it } from 'vitest'

import {
  appModeForPath,
  loadModeRoute,
  restoreLastRouteBeforeRouterMount,
  saveModeRoute,
} from '@/lib/mode-route'
import { STORAGE_KEYS } from '@/lib/storage-keys'

beforeEach(() => {
  window.history.replaceState(null, '', '/')
})

describe('mode route persistence', () => {
  it('classifies the three app modes without treating standalone pages as Forge', () => {
    expect(appModeForPath('/session-id')).toBe('forge')
    expect(appModeForPath('/coding/project/session')).toBe('coding')
    expect(appModeForPath('/aim/project/overview')).toBe('aim')
    expect(appModeForPath('/telemetry')).toBeNull()
  })

  it('keeps and restores a direct route for each mode', () => {
    saveModeRoute('/session-id', '/session-id')
    saveModeRoute('/coding/project/session', '/coding/project/session')
    saveModeRoute('/aim/project/pipelines', '/aim/project/pipelines')

    expect(loadModeRoute('forge')).toBe('/session-id')
    expect(loadModeRoute('coding')).toBe('/coding/project/session')
    expect(loadModeRoute('aim')).toBe('/aim/project/pipelines')
  })

  it('rejects a route stored under the wrong mode key', () => {
    localStorage.setItem(STORAGE_KEYS.modeRoutes.coding, '/aim/project/overview')

    expect(loadModeRoute('coding')).toBeNull()
  })

  it('restores the last route before the router mounts', () => {
    localStorage.setItem(STORAGE_KEYS.lastRoute, '/coding/project/session')

    restoreLastRouteBeforeRouterMount()

    expect(window.location.pathname).toBe('/coding/project/session')
  })
})
