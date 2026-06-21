import { describe, expect, it } from 'bun:test'
import { patchSessionInPageData } from '@/queries/session-cache'
import type { SessionPageResponse, SessionResponse } from '@/api/types'

function makeSession(id: string, title: string): SessionResponse {
  return { id, title, agent_name: 'lead', created_at: null, updated_at: null }
}

function makeData(pages: SessionResponse[][]): { pages: SessionPageResponse[]; pageParams: null[] } {
  return {
    pages: pages.map((data) => ({ data, next_cursor: null, has_more: false })),
    pageParams: pages.map(() => null),
  }
}

describe('patchSessionInPageData', () => {
  it('updates the matching session across every infinite-query page', () => {
    const old = makeData([
      [makeSession('s1', 'Old title')],
      [makeSession('s2', 'Other title'), makeSession('s1', 'Duplicate old title')],
    ])

    const patched = patchSessionInPageData(old, makeSession('s1', 'New title')) as typeof old

    expect(patched.pages[0].data[0].title).toBe('New title')
    expect(patched.pages[1].data[0].title).toBe('Other title')
    expect(patched.pages[1].data[1].title).toBe('New title')
    expect(patched.pageParams).toEqual(old.pageParams)
  })

  it('preserves unrelated session objects and page metadata', () => {
    const other = makeSession('s2', 'Other title')
    const old = {
      pages: [{ data: [other], next_cursor: 'cursor', has_more: true }],
      pageParams: [null],
    }

    const patched = patchSessionInPageData(old, makeSession('s1', 'New title')) as typeof old

    expect(patched.pages[0].data[0]).toBe(other)
    expect(patched.pages[0].next_cursor).toBe('cursor')
    expect(patched.pages[0].has_more).toBe(true)
  })

  it('returns non-infinite cache shapes unchanged', () => {
    const detail = { id: 's1', title: 'Old title' }

    expect(patchSessionInPageData(detail, makeSession('s1', 'New title'))).toBe(detail)
    expect(patchSessionInPageData(undefined, makeSession('s1', 'New title'))).toBeUndefined()
  })
})
