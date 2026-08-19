import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BlockRenderer } from '@/components/BlockRenderer'

vi.mock('@/utils/LazyMarkdownBlock', () => ({
  LazyMarkdownBlock: ({ content }: { content: string }) => <div>{content}</div>,
}))

vi.mock('@/queries', () => ({
  useWorkspaceFilesQuery: () => ({
    data: {
      files: [
        { path: 'src/integrity.rs', name: 'integrity.rs', mime: 'text/x-rust' },
        { path: 'src/hook_check.rs', name: 'hook_check.rs', mime: 'text/x-rust' },
      ],
    },
  }),
}))

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
})

describe('BlockRenderer assistant artifacts', () => {
  it('does not turn inline-code file mentions into attachment cards', () => {
    render(
      <BlockRenderer
        block={{
          id: 'assistant-text',
          type: 'text',
          content: 'Review `integrity.rs` and `hook_check.rs` next.',
        }}
        isStreaming={false}
        sessionId="session-1"
      />,
    )

    expect(screen.getByText(/Review/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Generated files')).not.toBeInTheDocument()
  })

  it('still renders files explicitly attached by a tool', () => {
    render(
      <BlockRenderer
        block={{
          id: 'tool-result',
          type: 'tool',
          content: '',
          toolName: 'artifact',
          toolArgs: '{}',
          toolDone: true,
          extra: {
            attachments: [
              {
                filename: 'report.md',
                original_name: 'report.md',
                category: 'document',
                media_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                url: '/api/team/session/media/report.md',
              },
            ],
          },
        }}
        isStreaming={false}
        sessionId="session-1"
      />,
    )

    expect(screen.getByRole('button', { name: 'report.md' })).toBeInTheDocument()
  })

  it('does not render task-bound handoffs as separate chat bubbles', () => {
    const { container } = render(
      <BlockRenderer
        block={{
          id: 'delegation-handoff',
          type: 'user',
          content: 'The audit is complete.',
          extra: {
            from_agent: 'explorer#1',
            _handoff_artifact: {
              task_id: '0198a1d2-3456-7890-abcd-ef0123456789',
              status: 'final',
              summary: 'The audit is complete.',
            },
          },
        }}
        isStreaming={false}
      />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('keeps untracked handoffs visible', () => {
    render(
      <BlockRenderer
        block={{
          id: 'standalone-handoff',
          type: 'user',
          content: 'A standalone finding.',
          extra: {
            from_agent: 'reviewer#1',
            _handoff_artifact: {
              status: 'final',
              summary: 'A standalone finding.',
            },
          },
        }}
        isStreaming={false}
      />,
    )

    expect(screen.getByText('Handoff from reviewer#1')).toBeInTheDocument()
    expect(screen.getByText('A standalone finding.')).toBeInTheDocument()
  })
})
