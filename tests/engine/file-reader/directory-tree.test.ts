import { describe, it, expect } from 'vitest'
import { buildTree, treeToString } from '../../../src/engine/file-reader/directory-tree'

describe('DirectoryTree', () => {
  const mockReaddir = (p: string): string[] => {
    const tree: Record<string, string[]> = {
      '/project': ['src', 'package.json', 'README.md'],
      '/project/src': ['components', 'utils', 'index.ts'],
      '/project/src/components': ['App.tsx', 'Header.tsx'],
      '/project/src/utils': ['helpers.ts']
    }
    return tree[p] || []
  }

  const mockIsDir = (p: string): boolean => {
    return ['/project', '/project/src', '/project/src/components', '/project/src/utils'].includes(p)
  }

  it('should build tree structure', () => {
    const tree = buildTree('/project', mockReaddir, mockIsDir, { excludePatterns: [] })
    expect(tree).not.toBeNull()
    expect(tree!.name).toBe('project')
    expect(tree!.isDirectory).toBe(true)
    expect(tree!.children).toBeDefined()
    expect(tree!.children!.length).toBe(3) // src, package.json, README.md
  })

  it('should render tree as string', () => {
    const tree = buildTree('/project', mockReaddir, mockIsDir, { excludePatterns: [] })
    const str = treeToString(tree!)
    expect(str).toContain('project/')
    expect(str).toContain('src/')
    expect(str).toContain('package.json')
    expect(str).toContain('README.md')
    expect(str).toContain('App.tsx')
  })

  it('should exclude patterns', () => {
    const tree = buildTree('/project', mockReaddir, mockIsDir, { excludePatterns: ['utils'] })
    const str = treeToString(tree!)
    expect(str).not.toContain('utils/')
    expect(str).not.toContain('helpers.ts')
  })

  it('should respect max depth', () => {
    const tree = buildTree('/project', mockReaddir, mockIsDir, { excludePatterns: [], maxDepth: 1 })
    const str = treeToString(tree!)
    expect(str).toContain('src/')
    expect(str).not.toContain('App.tsx') // depth 3, should be excluded
  })
})
