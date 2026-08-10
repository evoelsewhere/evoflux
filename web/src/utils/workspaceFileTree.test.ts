import { describe, expect, it } from 'vitest'
import type { WorkspaceFileInfo } from '@/api/types'
import { buildTree } from './workspaceFileTree'

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
