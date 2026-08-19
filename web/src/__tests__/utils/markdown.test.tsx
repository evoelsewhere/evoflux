import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { MarkdownBlock, splitStreamingMarkdown } from '@/utils/markdown'
import { useUIStore } from '@/stores/useUIStore'

beforeEach(() => {
  useUIStore.setState({
    workspaceFileRequest: null,
    workbenchTabs: [],
    activeWorkbenchTabId: null,
    activeWorkbenchTool: null,
    workbenchOpen: false,
  })
})

describe('splitStreamingMarkdown', () => {
  it('freezes completed prose blocks and leaves the growing tail isolated', () => {
    expect(splitStreamingMarkdown('First paragraph.\n\nSecond paragraph.')).toEqual([
      'First paragraph.\n\n',
      'Second paragraph.',
    ])
  })

  it('does not split blank lines inside a fenced code block', () => {
    expect(splitStreamingMarkdown(
      'Intro.\n\n```ts\nconst first = 1\n\nconst second = 2\n```\n\nOutro.',
    )).toEqual([
      'Intro.\n\n',
      '```ts\nconst first = 1\n\nconst second = 2\n```\n\n',
      'Outro.',
    ])
  })

  it('keeps loose list items in the same markdown segment', () => {
    expect(splitStreamingMarkdown('1. First\n\n2. Second\n\nAfter the list.')).toEqual([
      '1. First\n\n2. Second\n\n',
      'After the list.',
    ])
  })
})

describe('MarkdownBlock code fences', () => {
  it('renders a full-height native code block instead of a Monaco editor', () => {
    const diagram = Array.from(
      { length: 24 },
      (_, index) => `Step ${index + 1} -> Step ${index + 2}`,
    ).join('\n')

    const { container } = render(
      <MarkdownBlock content={`\`\`\`text\n${diagram}\n\`\`\``} />,
    )

    const pre = container.querySelector('pre')
    const code = container.querySelector('pre > code')

    expect(pre).not.toBeNull()
    expect(code).not.toBeNull()
    expect(pre).toHaveClass('overflow-x-auto')
    expect(code).toHaveClass('hljs', 'block', 'min-w-max')
    expect(code).toHaveTextContent('Step 24 -> Step 25')
    expect(container.querySelector('.monaco-editor')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy code' })).toBeInTheDocument()
  })

  it('does not guess a syntax language for an unlabeled text diagram', () => {
    const { container } = render(
      <MarkdownBlock content={'```\nSELECT estimate FROM historical_range\n```'} />,
    )

    const code = container.querySelector('pre > code')

    expect(code).toHaveClass('hljs')
    expect(code?.className).not.toContain('language-sql')
    expect(code?.querySelector('[class^="hljs-"]')).not.toBeInTheDocument()
  })
})

describe('MarkdownBlock workspace links', () => {
  it('opens generated documents in the Files workbench instead of a browser tab', () => {
    render(
      <MarkdownBlock
        content="[Tải deck](attention_is_all_you_need_vi.pptx)"
        sessionId="session-1"
      />,
    )

    const link = screen.getByRole('link', { name: 'Tải deck' })
    expect(link).not.toHaveAttribute('target')
    expect(link).toHaveAttribute(
      'title',
      'Preview attention_is_all_you_need_vi.pptx in Files',
    )
    fireEvent.click(link)

    expect(useUIStore.getState().workspaceFileRequest).toMatchObject({
      sessionId: 'session-1',
      path: 'attention_is_all_you_need_vi.pptx',
    })
    expect(useUIStore.getState().activeWorkbenchTool).toBe('files')
    expect(useUIStore.getState().workbenchOpen).toBe(true)
  })
})
