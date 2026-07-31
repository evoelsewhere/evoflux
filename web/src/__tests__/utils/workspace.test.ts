import { describe, expect, it } from 'vitest'

import { isWorkspaceUnavailableError } from '@/utils/workspace'

describe('isWorkspaceUnavailableError', () => {
  it('recognizes a stale workspace returned by the backend', () => {
    expect(
      isWorkspaceUnavailableError(
        new Error(
          'Workspace does not exist or is not a directory: /Users/example/old-repo',
        ),
      ),
    ).toBe(true)
  })

  it('does not classify a real backend failure as a stale workspace', () => {
    expect(isWorkspaceUnavailableError(new Error('Failed to fetch'))).toBe(false)
  })
})
