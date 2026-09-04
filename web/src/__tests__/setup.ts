import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

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
