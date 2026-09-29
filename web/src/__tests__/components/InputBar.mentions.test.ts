import { describe, expect, it } from 'vitest'

import { rankFileRefs, type FileRef } from '@/components/InputBar.mentions'

describe('rankFileRefs', () => {
  it('matches another repository’s files by their label, not their absolute path', () => {
    const refs: FileRef[] = [
      { path: 'src/main.py', name: 'main.py', type: 'file' },
      { path: 'C:/Users/dev/repos/web/src/app.ts', label: 'web/src/app.ts', name: 'app.ts', type: 'file' },
      { path: 'C:/Users/dev/repos/web/src/users.ts', label: 'web/src/users.ts', name: 'users.ts', type: 'file' },
    ]

    const ranked = rankFileRefs(refs, 'users', 10)

    // `users` must not match every file through the `C:/Users` prefix.
    expect(ranked.map((ref) => ref.path)).toEqual(['C:/Users/dev/repos/web/src/users.ts'])
  })

  it('lists another repository’s root among the top-level folders', () => {
    const refs: FileRef[] = [
      { path: 'src/main.py', name: 'main.py', type: 'file' },
      { path: 'src', name: 'src', type: 'directory' },
      { path: 'C:/Users/dev/repos/web', label: 'web', name: 'web', type: 'directory' },
    ]

    expect(rankFileRefs(refs, '', 10).slice(0, 2).map((ref) => ref.name)).toEqual(['src', 'web'])
  })
})
