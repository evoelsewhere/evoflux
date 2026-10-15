import { describe, expect, it } from 'vitest'
import { projectRelativePath } from '@/lib/project-relative-path'

describe('projectRelativePath', () => {
  it('accepts a save-dialog path inside a Windows workspace', () => {
    expect(projectRelativePath('D:\\Projects\\demo', 'D:\\Projects\\demo\\ui\\index.html'))
      .toBe('ui/index.html')
  })

  it('accepts a save-dialog path inside a POSIX workspace', () => {
    expect(projectRelativePath('/work/demo', '/work/demo/ui/index.html'))
      .toBe('ui/index.html')
  })

  it('rejects sibling paths that only share a workspace prefix', () => {
    expect(projectRelativePath('C:\\repo', 'C:\\repo-old\\index.html')).toBeNull()
  })

  it('rejects paths outside the repository and traversal segments', () => {
    expect(projectRelativePath('/work/demo', '/tmp/index.html')).toBeNull()
    expect(projectRelativePath('/work/demo', '/work/demo/../outside.html')).toBeNull()
  })
})
