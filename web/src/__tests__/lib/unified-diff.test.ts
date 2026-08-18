import { describe, expect, it } from 'vitest'

import { parseUnifiedDiff } from '@/lib/unified-diff'

describe('parseUnifiedDiff', () => {
  it('parses context, additions, deletions, and no-newline markers', () => {
    const hunks = parseUnifiedDiff([
      '@@ -3,2 +3,3 @@ function run()',
      ' context',
      '-old',
      '+new',
      '+more',
      '\\ No newline at end of file',
    ].join('\n'))

    expect(hunks).toEqual([{
      header: '@@ -3,2 +3,3 @@ function run()',
      oldStart: 3,
      newStart: 3,
      lines: [
        { type: 'ctx', content: 'context' },
        { type: 'del', content: 'old' },
        { type: 'add', content: 'new' },
        { type: 'add', content: 'more' },
        { type: 'info', content: '\\ No newline at end of file' },
      ],
    }])
  })

  it('accepts one-line hunk ranges and ignores file headers', () => {
    expect(parseUnifiedDiff('--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new')).toHaveLength(1)
  })
})
