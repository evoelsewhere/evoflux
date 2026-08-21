import { describe, expect, it } from 'vitest'

import { resolveCodingSidebarSelection } from '@/utils/coding-sidebar-selection'

describe('resolveCodingSidebarSelection', () => {
  it('follows the active scope when it is visible', () => {
    expect(resolveCodingSidebarSelection(['a', 'b'], 'b', 'a')).toBe('b')
  })

  it('keeps a manual selection when no visible active scope exists', () => {
    expect(resolveCodingSidebarSelection(['a', 'b'], null, 'b')).toBe('b')
    expect(resolveCodingSidebarSelection(['a', 'b'], 'missing', 'b')).toBe('b')
  })

  it('falls back to the first visible scope and clears empty lists', () => {
    expect(resolveCodingSidebarSelection(['a', 'b'], null, 'missing')).toBe('a')
    expect(resolveCodingSidebarSelection([], null, 'missing')).toBeNull()
  })
})
