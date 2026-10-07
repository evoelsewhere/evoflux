import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Some managed Node hosts expose a placeholder localStorage instead of jsdom's
// Storage object. Keep the browser API consistent for locale and cleanup tests.
if (typeof window.localStorage?.getItem !== 'function' || typeof window.localStorage?.clear !== 'function') {
  const values = new Map<string, string>()
  const storage: Storage = {
    get length() { return values.size },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => { values.delete(key) },
    setItem: (key, value) => { values.set(key, String(value)) },
  }
  Object.defineProperty(window, 'localStorage', { configurable: true, value: storage })
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage })
}

// jsdom implements `scrollTop` but not `Element.prototype.scrollTo`, which
// every browser has. Without it any component that scrolls a container
// throws on mount here for a reason that has nothing to do with the test.
if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
  Element.prototype.scrollTo = function scrollTo(
    this: Element,
    options?: ScrollToOptions | number,
    y?: number,
  ) {
    const top = typeof options === 'number' ? y : options?.top
    if (typeof top === 'number') this.scrollTop = top
  } as typeof Element.prototype.scrollTo
}

afterEach(() => {
  cleanup()
  localStorage.clear()
})
