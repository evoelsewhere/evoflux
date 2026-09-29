import { beforeEach, describe, expect, it } from 'vitest'

import { STORAGE_KEYS } from '@/lib/storage-keys'
import {
  clearLastCodingFocus,
  codingFocusId,
  isWorkspaceUnavailableError,
  loadLastCodingFocusId,
  saveLastCodingFocus,
} from '@/utils/workspace'

beforeEach(() => {
  localStorage.clear()
})

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

describe('last coding focus', () => {
  it('remembers only projects', () => {
    saveLastCodingFocus({ project_id: null })

    expect(loadLastCodingFocusId()).toBeNull()
  })

  it('drops a folder path left by a standalone workspace instead of restoring it', () => {
    localStorage.setItem(STORAGE_KEYS.coding.lastFocus, '/repos/previous-workspace')

    expect(loadLastCodingFocusId()).toBeNull()
    expect(localStorage.getItem(STORAGE_KEYS.coding.lastFocus)).toBeNull()
  })

  it('anchors a session URL on its project', () => {
    expect(codingFocusId({ project_id: 'p-1' })).toBe('p-1')
    expect(codingFocusId({ project_id: null })).toBeNull()
  })
})

describe('clearLastCodingFocus', () => {
  it('forgets the active project once it is deleted', () => {
    const projectId = '06a68187-7179-7ae0-8000-2d00ba15d730'
    saveLastCodingFocus({ project_id: projectId })

    clearLastCodingFocus(projectId)

    expect(loadLastCodingFocusId()).toBeNull()
  })

  it('keeps the current focus when a different project is deleted', () => {
    const currentProjectId = '06a68187-7179-7ae0-8000-2d00ba15d730'
    const deletedProjectId = '16a68187-7179-7ae0-8000-2d00ba15d731'
    saveLastCodingFocus({ project_id: currentProjectId })

    clearLastCodingFocus(deletedProjectId)

    expect(loadLastCodingFocusId()).toBe(currentProjectId)
  })
})
