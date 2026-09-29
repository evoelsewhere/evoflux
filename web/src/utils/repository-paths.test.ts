import { describe, expect, it } from 'vitest'

import type { CodingProject } from '@/api/types'
import {
  agentPath,
  normalizePath,
  resolveRepositoryPath,
  sessionProject,
  worktreeSourceRepository,
} from './repository-paths'

const API = 'C:\\repos\\mr-api'
const WEB = 'C:\\repos\\mr-web'
const WORKTREE = 'C:\\repos\\mr-web\\.evoflux\\worktrees\\qa-wt'

function project(): CodingProject {
  return {
    id: 'p',
    name: 'MR',
    description: null,
    kind: 'coding',
    settings: {},
    workspaces: [
      { workspace_id: 'a', path: API, name: 'mr-api', display_name: null, sort_order: 0, kind: 'repo' },
      { workspace_id: 'w', path: WEB, name: 'mr-web', display_name: null, sort_order: 1, kind: 'repo' },
    ],
    created_at: '',
    updated_at: '',
  }
}

describe('repository paths', () => {
  it('folds separators and dot segments', () => {
    expect(normalizePath('C:\\repos\\mr-api\\..\\mr-web\\.\\src')).toBe('C:/repos/mr-web/src')
    expect(normalizePath('/srv/a/../b')).toBe('/srv/b')
    expect(normalizePath('../mr-web/src')).toBe('../mr-web/src')
  })

  it('routes relative, climbing and absolute paths to their repository', () => {
    const repos = [API, WEB]
    expect(resolveRepositoryPath(API, repos, 'src/main.py')).toEqual({ workspace: API, path: 'src/main.py' })
    expect(resolveRepositoryPath(API, repos, '../mr-web/src/users.ts')).toEqual({
      workspace: WEB,
      path: 'src/users.ts',
    })
    expect(resolveRepositoryPath(API, repos, 'c:/REPOS/mr-web/README.md')).toEqual({
      workspace: WEB,
      path: 'README.md',
    })
    expect(resolveRepositoryPath(API, repos, '../elsewhere/x.txt')).toBeNull()
  })

  it('prefers a worktree over the repository that contains it', () => {
    expect(resolveRepositoryPath(WORKTREE, [API, WEB], 'README.md')).toEqual({
      workspace: WORKTREE,
      path: 'README.md',
    })
  })

  it('addresses another repository by absolute path', () => {
    expect(agentPath(API, API, 'src/main.py')).toBe('src/main.py')
    expect(agentPath(API, WEB, 'src/users.ts')).toBe('C:/repos/mr-web/src/users.ts')
  })

  it('lets a worktree stand in for its source repository', () => {
    expect(worktreeSourceRepository(WORKTREE, [API, WEB])).toBe(WEB)
    const seen = sessionProject(project(), WORKTREE)
    expect(seen.workspaces.map((item) => item.path)).toEqual([API, WORKTREE])
    expect(seen.workspaces[1]?.display_name).toBe('mr-web (qa-wt)')
    expect(sessionProject(project(), API)).toEqual(project())
  })

  it('finds a worktree outside its repository through the overview', () => {
    const outside = 'C:\\data\\worktrees\\abc\\task'
    const overview = {
      projects: [],
      repositories: [
        { workspace_id: 'w', path: WEB, name: 'mr-web', project_id: 'p', worktrees: [{ path: outside, name: 'task', managed: true }] },
      ],
    }
    expect(worktreeSourceRepository(outside, [API, WEB], overview)).toBe(WEB)
  })
})
