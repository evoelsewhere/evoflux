import { describe, expect, it, vi } from 'vitest'

import type { CodingProject, WorkspaceGitDiffResponse } from '@/api/types'
import { queryKeys } from '@/queries'
import { applyCacheInvalidations } from '@/stores/cache-invalidation-bridge'

const getCodingWorkspaceGitDiff = vi.fn()

vi.mock('@/api/client', () => ({
  getCodingWorkspaceGitDiff: (...args: unknown[]) => getCodingWorkspaceGitDiff(...args),
}))

const API = 'C:\\repos\\mr-api'
const WEB = 'C:\\repos\\mr-web'

const project: CodingProject = {
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

function client() {
  const data = new Map<string, unknown>([
    [JSON.stringify(queryKeys.projects.detail('p')), project],
    [JSON.stringify(queryKeys.coding.diff(WEB)), { workspace: WEB, is_git_repo: true, diff: '' } satisfies WorkspaceGitDiffResponse],
  ])
  return {
    invalidateQueries: vi.fn(),
    getQueryData: vi.fn((key: readonly unknown[]) => data.get(JSON.stringify(key))),
    setQueryData: vi.fn(),
  }
}

type BridgeClient = Parameters<typeof applyCacheInvalidations>[0]

function invalidatedKeys(queryClient: ReturnType<typeof client>) {
  return queryClient.invalidateQueries.mock.calls.map(([arg]) => (arg as { queryKey: unknown }).queryKey)
}

describe('cache invalidation bridge', () => {
  it('refreshes the repository a tool wrote to, with the path relative to it', () => {
    getCodingWorkspaceGitDiff.mockResolvedValue({ workspace: WEB, is_git_repo: true, diff: '' })
    const queryClient = client()

    applyCacheInvalidations(queryClient as unknown as BridgeClient, [
      { kind: 'coding_workspace_paths', workspace: API, projectId: 'p', paths: ['../mr-web/src/users.ts'] },
    ])

    const keys = invalidatedKeys(queryClient)
    expect(keys).toContainEqual(queryKeys.coding.files(WEB))
    expect(keys).toContainEqual(queryKeys.coding.status(WEB))
    expect(keys).not.toContainEqual(queryKeys.coding.files(API))
    expect(getCodingWorkspaceGitDiff).toHaveBeenCalledWith(WEB, ['src/users.ts'])
  })

  it('refreshes every repository when no path is known', () => {
    const queryClient = client()

    applyCacheInvalidations(queryClient as unknown as BridgeClient, [
      { kind: 'coding_workspace', workspace: API, projectId: 'p' },
    ])

    const keys = invalidatedKeys(queryClient)
    expect(keys).toContainEqual(queryKeys.coding.diff(API))
    expect(keys).toContainEqual(queryKeys.coding.diff(WEB))
  })
})
