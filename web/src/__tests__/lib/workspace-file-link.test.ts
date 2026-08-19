import { describe, expect, it } from 'vitest'

import { workspaceFilePathFromHref } from '@/lib/workspace-file-link'

describe('workspaceFilePathFromHref', () => {
  it('recognizes bare generated document paths', () => {
    expect(workspaceFilePathFromHref('attention_is_all_you_need_vi.pptx', 'session-1'))
      .toBe('attention_is_all_you_need_vi.pptx')
    expect(workspaceFilePathFromHref('./output/final%20report.pdf?download=1', 'session-1'))
      .toBe('output/final report.pdf')
  })

  it('recognizes current-session media URLs and rejects another session', () => {
    expect(workspaceFilePathFromHref(
      '/api/team/session-1/media/decks/final.pptx?download=1',
      'session-1',
    )).toBe('decks/final.pptx')
    expect(workspaceFilePathFromHref(
      '/api/team/session-2/media/decks/final.pptx?download=1',
      'session-1',
    )).toBeNull()
  })

  it('maps sandbox artifacts to their workspace basename', () => {
    expect(workspaceFilePathFromHref(
      'sandbox:/mnt/data/generated/deck.pptx',
      'session-1',
    )).toBe('deck.pptx')
  })

  it('leaves external links and unsafe paths to the normal link handler', () => {
    expect(workspaceFilePathFromHref('https://example.com/deck.pptx', 'session-1')).toBeNull()
    expect(workspaceFilePathFromHref('../private/deck.pptx', 'session-1')).toBeNull()
    expect(workspaceFilePathFromHref('javascript:alert(1)', 'session-1')).toBeNull()
  })
})
