import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { apiWsBaseUrl, setApiBaseUrl } from '@/api/base-url'

function clearOverrides(): void {
  Object.defineProperty(window, '__OAD_API_BASE_URL__', {
    value: undefined,
    writable: true,
    configurable: true,
  })
  Object.defineProperty(window, '__OAD_BACKEND_UNAVAILABLE__', {
    value: false,
    writable: true,
    configurable: true,
  })
}

function setLocation(href: string): void {
  window.history.replaceState(null, '', href)
}

beforeEach(clearOverrides)
afterEach(clearOverrides)

describe('apiWsBaseUrl', () => {
  it('stays same-origin when the API base is relative so the serving port always wins', () => {
    // jsdom serves the test page from http://localhost:3000 by default.
    setLocation('/')
    expect(apiWsBaseUrl()).toBe(`ws://${window.location.host}/api`)
  })

  it('derives ws:// and wss:// from an absolute API base', () => {
    setApiBaseUrl('http://127.0.0.1:4082')
    expect(apiWsBaseUrl()).toBe('ws://127.0.0.1:4082/api')

    setApiBaseUrl('https://evoflux.example.com')
    expect(apiWsBaseUrl()).toBe('wss://evoflux.example.com/api')
  })

  it('never points at a hardcoded backend port', () => {
    setLocation('/')
    expect(apiWsBaseUrl()).not.toContain(':8000')
    expect(apiWsBaseUrl()).not.toContain(':4082')
  })

  it('keeps the backend-unavailable sentinel unroutable instead of guessing a port', () => {
    Object.defineProperty(window, '__OAD_BACKEND_UNAVAILABLE__', {
      value: true,
      writable: true,
      configurable: true,
    })
    expect(apiWsBaseUrl()).toBe('ws://api')
  })
})
