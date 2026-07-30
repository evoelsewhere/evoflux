import { describe, expect, it } from 'vitest'

import { errorMessage, isTransientNetworkError } from '@/utils/errors'

describe('network error helpers', () => {
  it('normalizes Error and non-Error values', () => {
    expect(errorMessage(new Error('boom'))).toBe('boom')
    expect(errorMessage(503)).toBe('503')
  })

  it.each([
    'Load failed',
    'Failed to fetch',
    'NetworkError when attempting to fetch resource',
    'Network request failed',
  ])('recognizes transient browser failures: %s', (message) => {
    expect(isTransientNetworkError(new Error(message))).toBe(true)
  })

  it('does not treat application failures as transient', () => {
    expect(isTransientNetworkError(new Error('Permission denied'))).toBe(false)
  })
})
