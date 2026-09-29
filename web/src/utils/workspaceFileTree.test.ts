import { describe, expect, it } from 'vitest'
import type { WorkspaceFileInfo, WorkspaceGitDiffResponse } from '@/api/types'
import { buildTree, changedFileStatuses, collectChangedFiles } from './workspaceFileTree'

function makeFile(path: string): WorkspaceFileInfo {
  return {
    path,
    name: path.split('/').pop() ?? path,
    size: 0,
    mtime: Date.parse('2024-01-01T00:00:00.000Z'),
    mime: 'text/plain',
  } as WorkspaceFileInfo
}

describe('buildTree', () => {
  it('sorts directories before files and uses natural ordering', () => {
    const tree = buildTree([
      makeFile('src/file10.ts'),
      makeFile('src/file2.ts'),
      makeFile('src/components/button.ts'),
      makeFile('src/docs/readme.md'),
      makeFile('src/alpha.ts'),
    ])

    const srcNode = tree.children.get('src')
    expect(srcNode).toBeDefined()

    const names = Array.from(srcNode!.children.values()).map((child) => child.name)
    expect(names).toEqual(['components', 'docs', 'alpha.ts', 'file2.ts', 'file10.ts'])
  })
})

describe('collectChangedFiles', () => {
  it('tells an untracked file from a staged new one and a modification', () => {
    const diff = {
      is_git_repo: true,
      diff: [
        'diff --git a/app.py b/app.py',
        '--- a/app.py',
        '+++ b/app.py',
        '+x = 1',
        'diff --git a/new.py b/new.py',
        'new file mode 100644',
        '+y = 2',
      ].join('\n'),
      untracked: ['src/util.ts'],
    } as unknown as WorkspaceGitDiffResponse

    const statuses = changedFileStatuses(collectChangedFiles(diff))

    expect(statuses.get('app.py')).toBe('M')
    expect(statuses.get('new.py')).toBe('A')
    // A file the agent just wrote is untracked, not modified.
    expect(statuses.get('src/util.ts')).toBe('U')
  })
})
