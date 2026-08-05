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
          toolName: 'docx_document',
          toolArgs: '{}',
          toolDone: true,
          extra: {
            attachments: [
              {
                filename: 'report.docx',
                original_name: 'report.docx',
                category: 'document',
                media_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                url: '/api/team/session/media/report.docx',
              },
            ],
          },
        }}
        isStreaming={false}
        sessionId="session-1"
      />,
    )

    expect(screen.getByRole('button', { name: 'report.docx' })).toBeInTheDocument()
  })
})
