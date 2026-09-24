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

const text = (content: string): ContentBlock => ({ id: `text-${content}`, type: 'text', content })

const file = (path: string, mime = ''): WorkspaceFileInfo => ({
  path,
  name: path.split('/').pop() ?? path,
  size: 81_800,
  mtime: 1,
  mime,
})

describe('turnFileMentions', () => {
  it('collects what the tools produced and what the reply links, in order', () => {
    const blocks: ContentBlock[] = [
      text('I will make `notes.pptx` for you'),
      tool('write', { path: 'slides/01_cover.py', content: '' }),
      tool('shell', { command: 'uv run python deck_live.py init "C:\\ws\\review.pptx" --slides 3' }),
      tool('edit', { path: 'report.docx', old_string: 'a', new_string: 'b' }),
      // A render the agent made for itself: named on the command line only.
      tool('shell', { command: 'python render.py review.pptx --out qa/slide-01.png' }),
      text('Done: [the deck](review.pptx) and ![chart](charts/revenue.png) — see https://example.com/x.png'),
    ]

    expect(turnFileMentions(blocks, 'session-1')).toEqual({
      produced: ['slides/01_cover.py', 'C:/ws/review.pptx', 'report.docx', 'review.pptx'],
      linked: ['review.pptx', 'charts/revenue.png'],
    })
  })

  it('leaves out files the turn removed', () => {
    const blocks = [tool('write', { path: 'draft.pptx' }), tool('rm', { path: 'draft.pptx' }), text('[draft](draft.pptx)')]

    expect(turnFileMentions(blocks)).toEqual({ produced: [], linked: [] })
  })
})

describe('resolveTurnFiles', () => {
  const files = [
    file('review.pptx'),
    file('slides/01_cover.py', 'text/x-python'),
    file('report.docx'),
    file('qa/slide-01.png', 'image/png'),
    file('charts/revenue.png', 'image/png'),
    file('a/data.xlsx'),
    file('b/data.xlsx'),
  ]

  it('cards the documents produced and whatever previewable file the reply links', () => {
    const mentions = {
      produced: ['slides/01_cover.py', 'C:/ws/review.pptx', 'report.docx', 'qa/slide-01.png', 'data.xlsx', 'missing.pptx'],
      linked: ['charts/revenue.png'],
    }

    expect(resolveTurnFiles(mentions, files, 'C:\\ws').map((entry) => entry.path)).toEqual([
      'review.pptx',
      'report.docx',
      'charts/revenue.png',
    ])
  })

  it('shows an image only when the reply links it, whatever folder it is in', () => {
    const produced = ['qa/slide-01.png']

    expect(resolveTurnFiles({ produced, linked: [] }, files)).toEqual([])
    expect(resolveTurnFiles({ produced, linked: ['qa/slide-01.png'] }, files).map((entry) => entry.path)).toEqual([
      'qa/slide-01.png',
    ])
  })

  it('lists a file once even when it was produced and linked', () => {
    const mentions = { produced: ['review.pptx', './review.pptx'], linked: ['review.pptx'] }

    expect(resolveTurnFiles(mentions, files).map((entry) => entry.path)).toEqual(['review.pptx'])
  })
})
