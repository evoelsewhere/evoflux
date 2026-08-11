import { describe, expect, it } from 'vitest'

import {
  shouldClearFilesEditor,
  shouldShowStandaloneEditor,
} from './codingFileViewer'

describe('coding file viewer placement', () => {
  it('clears a Files editor when the side panel closes', () => {
    expect(shouldClearFilesEditor('files', false, true)).toBe(true)
  })

  it('clears a Files editor when its tab is removed', () => {
    expect(shouldClearFilesEditor('files', true, false)).toBe(true)
  })

  it('does not promote a Files editor to a standalone panel', () => {
    expect(shouldShowStandaloneEditor('files', false, 'files')).toBe(false)
    expect(shouldShowStandaloneEditor('files', true, 'overview')).toBe(false)
  })

  it('keeps explicitly standalone editors independent from the workbench', () => {
    expect(shouldShowStandaloneEditor('standalone', false, null)).toBe(true)
    expect(shouldShowStandaloneEditor('standalone', true, 'overview')).toBe(true)
    expect(shouldShowStandaloneEditor('standalone', true, 'files')).toBe(false)
  })
})
