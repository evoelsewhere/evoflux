import { describe, expect, it } from 'vitest'

import type { ProjectWorkspaceItem } from '@/api/types'
import {
  projectRepositoryFallback,
  resolveGitWorkspace,
} from '@/components/git/git-workspace-selection'

const repositories: ProjectWorkspaceItem[] = [
  {
    workspace_id: 'repo-1',
    path: 'C:\\work\\api',
    name: 'api',
    display_name: null,
    sort_order: 0,
    kind: 'repo',
  },
  {
    workspace_id: 'repo-2',
    path: 'C:\\work\\web',
    name: 'web',
    display_name: null,
    sort_order: 1,
    kind: 'repo',
  },
]

describe('project Git workspace selection', () => {
  it('uses the first project repository when a project session has no workspace', () => {
    expect(resolveGitWorkspace(null, null, repositories)).toBe('C:\\work\\api')
  })

  it('keeps a selected project repository across Windows path formatting differences', () => {
    expect(resolveGitWorkspace(
      'C:\\work\\api',
      'c:/work/web/',
      repositories,
    )).toBe('C:\\work\\web')
  })

  it('falls back when an old session points at a non-Git aggregate folder', () => {
    expect(projectRepositoryFallback(
      'C:\\work',
      false,
      repositories,
    )).toBe('C:\\work\\api')
  })

  it('does not replace a valid member folder or a detected Git worktree', () => {
    expect(projectRepositoryFallback('C:\\work\\api', false, repositories)).toBeNull()
    expect(projectRepositoryFallback('C:\\worktrees\\api-task', true, repositories)).toBeNull()
  })
})
