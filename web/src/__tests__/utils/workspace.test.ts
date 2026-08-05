import { beforeEach, describe, expect, it } from 'vitest'

import {
  clearLastCodingFocus,
  isWorkspaceUnavailableError,
  loadLastCodingFocusId,
  saveLastCodingFocus,
  saveLastCodingWorkspace,
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

describe('clearLastCodingFocus', () => {
  it('does not restore a legacy workspace after the active project is deleted', () => {
    const projectId = '06a68187-7179-7ae0-8000-2d00ba15d730'
    saveLastCodingWorkspace('/repos/previous-workspace')
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
