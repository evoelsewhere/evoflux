import { describe, expect, it } from 'vitest'

import type { ContentBlock, WorkspaceFileInfo } from '@/api/types'
import { resolveTurnFiles, turnFileMentions } from '@/lib/turn-files'

const tool = (toolName: string, args: Record<string, unknown>): ContentBlock => ({
  id: `${toolName}-${JSON.stringify(args)}`,
  type: 'tool',
  content: '',
  toolName,
  toolArgs: JSON.stringify(args),
  toolDone: true,
})

const file = (path: string, mime = ''): WorkspaceFileInfo => ({
  path,
  name: path.split('/').pop() ?? path,
  size: 81_800,
  mtime: 1,
  mime,
})

describe('turnFileMentions', () => {
  it('collects written, edited and command-line files in first-touched order', () => {
    const blocks: ContentBlock[] = [
      { id: 'text', type: 'text', content: 'I made `notes.pptx` for you' },
      tool('write', { path: 'slides/01_cover.py', content: '' }),
      tool('shell', { command: 'uv run python deck_live.py init "C:\\ws\\review.pptx" --slides 3' }),
      tool('edit', { path: 'report.docx', old_string: 'a', new_string: 'b' }),
      tool('shell', { command: 'python chart.py && cp out/chart.png ./chart.png' }),
      tool('write', { path: 'slides/01_cover.py', content: '' }),
    ]

    expect(turnFileMentions(blocks)).toEqual([
      'slides/01_cover.py',
      'C:/ws/review.pptx',
      'report.docx',
      'out/chart.png',
      'chart.png',
    ])
  })

  it('leaves out files the turn removed', () => {
    const blocks = [tool('write', { path: 'draft.pptx' }), tool('rm', { path: 'draft.pptx' })]

    expect(turnFileMentions(blocks)).toEqual([])
  })
})

describe('resolveTurnFiles', () => {
  const files = [
    file('review.pptx'),
    file('slides/01_cover.py', 'text/x-python'),
    file('report.docx'),
    file('chart.png', 'image/png'),
    file('a/data.xlsx'),
    file('b/data.xlsx'),
  ]

  it('keeps only previewable workspace files, matched by path, root or unique name', () => {
    const mentions = [
      'slides/01_cover.py',
      'C:/ws/review.pptx',
      'report.docx',
      'out/chart.png',
      'data.xlsx',
      'missing.pptx',
    ]

    expect(resolveTurnFiles(mentions, files, 'C:\\ws').map((entry) => entry.path)).toEqual([
      'review.pptx',
      'report.docx',
      'chart.png',
    ])
  })

  it('lists a file once even when it was touched several ways', () => {
    expect(resolveTurnFiles(['review.pptx', './review.pptx'], files).map((entry) => entry.path)).toEqual([
      'review.pptx',
    ])
  })
})
