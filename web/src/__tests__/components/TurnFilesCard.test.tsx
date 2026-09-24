import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ContentBlock } from '@/api/types'
import { TurnFilesCard } from '@/components/TurnFilesCard'
import { useUIStore } from '@/stores/useUIStore'

const renders = ['slide-01.png', 'slide-02.png', 'crop_01.png', 'crop_02.png', 'sheet.png']

vi.mock('@/queries/useWorkspaceFilesQuery', () => ({
  useWorkspaceFilesQuery: (sessionId: string | null | undefined) => ({
    data: sessionId
      ? {
          workspace_root: '/ws',
          truncated: false,
          files: [
            { path: 'GalaxyCore_Q3.pptx', name: 'GalaxyCore_Q3.pptx', size: 83_763, mtime: 1, mime: '' },
            { path: 'build_deck.ts', name: 'build_deck.ts', size: 900, mtime: 1, mime: 'text/plain' },
            ...renders.map((name) => ({ path: `qa/${name}`, name, size: 1_000, mtime: 1, mime: 'image/png' })),
          ],
        }
      : undefined,
  }),
}))

const blocks: ContentBlock[] = [
  {
    id: 'edit',
    type: 'tool',
    content: '',
    toolName: 'edit',
    toolArgs: JSON.stringify({ path: 'build_deck.ts', old_string: 'a', new_string: 'b' }),
    toolDone: true,
  },
  {
    id: 'shell',
    type: 'tool',
    content: '',
    toolName: 'shell',
    toolArgs: JSON.stringify({ command: 'bun run build_deck.ts --out GalaxyCore_Q3.pptx' }),
    toolDone: true,
  },
]

let requestWorkspaceFile = vi.fn<(sessionId: string, path: string) => void>()

beforeEach(() => {
  requestWorkspaceFile = vi.fn<(sessionId: string, path: string) => void>()
  useUIStore.setState({ requestWorkspaceFile })
})

describe('TurnFilesCard', () => {
  it('shows a card per previewable file the turn produced and opens it in Files', () => {
    render(<TurnFilesCard blocks={blocks} sessionId="session-1" />)

    expect(screen.getByText('Slides · PPTX · 81.8 KB')).toBeInTheDocument()
    // The generator script is not a previewable document.
    expect(screen.queryByText('build_deck.ts')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Preview GalaxyCore_Q3.pptx' }))
    expect(requestWorkspaceFile).toHaveBeenCalledWith('session-1', 'GalaxyCore_Q3.pptx')
  })

  it('puts documents first and folds everything past four files behind "+N more"', () => {
    const qa: ContentBlock = {
      id: 'render',
      type: 'tool',
      content: '',
      toolName: 'shell',
      toolArgs: JSON.stringify({ command: `python crop.py ${renders.map((name) => `qa/${name}`).join(' ')}` }),
      toolDone: true,
    }
    // The renders are touched before the deck, yet the deck leads.
    render(<TurnFilesCard blocks={[qa, ...blocks]} sessionId="session-1" />)

    const previews = () => screen.getAllByRole('button', { name: /^Preview / })
    expect(previews().map((button) => button.getAttribute('aria-label'))).toEqual([
      'Preview GalaxyCore_Q3.pptx',
      'Preview slide-01.png',
      'Preview slide-02.png',
      'Preview crop_01.png',
    ])

    fireEvent.click(screen.getByRole('button', { name: '+2 more' }))
    expect(previews()).toHaveLength(6)
    fireEvent.click(screen.getByRole('button', { name: 'Show less' }))
    expect(previews()).toHaveLength(4)
  })

  it('renders nothing for a turn that produced no previewable file', () => {
    const { container } = render(<TurnFilesCard blocks={blocks.slice(0, 1)} sessionId="session-1" />)

    expect(container).toBeEmptyDOMElement()
  })
})
