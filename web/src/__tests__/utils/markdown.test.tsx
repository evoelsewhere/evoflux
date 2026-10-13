import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { escapeCurrencyDollars, MarkdownBlock, splitStreamingMarkdown } from '@/utils/markdown'
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

describe('escapeCurrencyDollars', () => {
  it('keeps two prices on a line as text', () => {
    expect(escapeCurrencyDollars('Q2 $2,015K, Q3 $2,436K, +20.9%')).toBe(
      'Q2 \\$2,015K, Q3 \\$2,436K, +20.9%',
    )
    expect(escapeCurrencyDollars('from $5-$10 each')).toBe('from \\$5-\\$10 each')
  })

  it('leaves inline and display math, escapes and code alone', () => {
    const untouched = [
      'Solve $x^2 + 1$ and $y$.',
      '$$\na $5 b $6\n$$',
      'Costs \\$5 and \\$6.',
      'Run `echo $A $B` now.',
      '```sh\necho $HOME $PATH\n```',
    ]
    for (const text of untouched) expect(escapeCurrencyDollars(text)).toBe(text)
  })

  it('renders prices as plain text rather than KaTeX', () => {
    const { container } = render(
      <MarkdownBlock content="Q2 $2,015K, Q3 $2,436K; area $\pi r^2$." />,
    )
    expect(container).toHaveTextContent('Q2 $2,015K, Q3 $2,436K; area')
    expect(container.querySelectorAll('.katex')).toHaveLength(1)
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

// ── MarkdownBlock native chart/mermaid fences (Intelligent UI feature D) ──────

const mermaidMock = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn(
    async (_id: string, code: string): Promise<{ svg: string }> => {
      if (code.includes('BROKEN')) throw new Error('Parse error on line 1')
      return { svg: '<svg data-mermaid-rendered="true"></svg>' }
    },
  ),
}))

vi.mock('mermaid', () => ({ default: mermaidMock }))

const VALID_CHART = [
  '```chart',
  '{"type":"bar","title":"Monthly active users","xKey":"month",',
  '"series":[{"key":"users","label":"Users"}],',
  '"data":[{"month":"Jan","users":1200},{"month":"Feb","users":1800}]}',
  '```',
].join('\n')

describe('MarkdownBlock native chart/mermaid fences', () => {
  beforeEach(() => {
    mermaidMock.initialize.mockClear()
    mermaidMock.render.mockClear()
    // jsdom has no ResizeObserver; recharts' ResponsiveContainer needs it.
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    )
  })

  it('renders a skeleton instead of CodeBlock while a chart fence is still streaming', async () => {
    const { container } = render(
      <MarkdownBlock
        content={'```chart\n{"type":"bar","xKey":"a","series":[]}\n```'}
        isStreaming
      />,
    )

    // The streaming reveal commits on a timer frame, so wait for it.
    await waitFor(
      () =>
        expect(
          container.querySelector('.animate-pulse[aria-hidden="true"]'),
        ).not.toBeNull(),
      { timeout: 5_000 },
    )
    expect(container.querySelector('.hljs')).toBeNull()
    expect(screen.queryByText('Invalid chart spec')).toBeNull()
  })

  it('falls back to CodeBlock with a notice when a settled chart spec is invalid', async () => {
    const { container } = render(
      <MarkdownBlock content={'```chart\n{"type":"bar","xKey":"a","series":[]}\n```'} />,
    )

    // The lazy fence chunk loads first, then it swaps in the fallback.
    await screen.findByText('Invalid chart spec', {}, { timeout: 5_000 })
    expect(container.querySelector('pre > code')).toHaveClass('hljs')
  })

  it('renders a completed valid chart fence natively with its title', async () => {
    const { container } = render(<MarkdownBlock content={VALID_CHART} />)

    await screen.findByText('Monthly active users', {}, { timeout: 5_000 })
    expect(container.querySelector('.hljs')).toBeNull()
  })

  it('renders a completed mermaid fence via the lazily-loaded mermaid runtime', async () => {
    const { container } = render(
      <MarkdownBlock content={'```mermaid\ngraph TD; A-->B\n```'} />,
    )

    await waitFor(
      () => expect(container.querySelector('.evoflux-mermaid svg')).not.toBeNull(),
      { timeout: 5_000 },
    )
    expect(mermaidMock.render).toHaveBeenCalledTimes(1)
    expect(mermaidMock.initialize).toHaveBeenCalledWith({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: expect.stringMatching(/^(default|dark)$/),
    })
    expect(container.querySelector('.hljs')).toBeNull()
  })

  it('falls back to CodeBlock with a notice when mermaid cannot parse the diagram', async () => {
    const { container } = render(
      <MarkdownBlock content={'```mermaid\nBROKEN\n```'} />,
    )

    await screen.findByText(
      'Mermaid diagram failed to render',
      {},
      { timeout: 5_000 },
    )
    expect(container.querySelector('pre > code')).toHaveClass('hljs')
  })

  it('keeps chart fences working when allowHtml routes html fences elsewhere', async () => {
    const { container } = render(<MarkdownBlock content={VALID_CHART} allowHtml />)

    await screen.findByText('Monthly active users', {}, { timeout: 5_000 })
    expect(container.querySelector('.hljs')).toBeNull()
  })
})
