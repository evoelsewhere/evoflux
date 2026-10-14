import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MarkdownBlock } from '@/utils/markdown'

// ── MarkdownBlock interactive tables (Intelligent UI tier-3 upgrade) ──────────
//
// Gate: interactive only when the table is settled (non-streaming) and clears
// 6 body rows / 3 columns. Below that — or while streaming — the plain
// react-markdown <table> renders unwrapped so the streaming cursor CSS keeps
// matching.

function table(headers: string[], rows: string[][]): string {
  return [
    `| ${headers.join(' | ')} |`,
    `| ${headers.map(() => '---').join(' | ')} |`,
    ...rows.map((row) => `| ${row.join(' | ')} |`),
  ].join('\n')
}

const THREE_HEADERS = ['Name', 'Count', 'Note']

const SIX_ROWS = [
  ['alpha', '10', 'first'],
  ['bravo', '9', 'second'],
  ['charlie', '6', 'third'],
  ['delta', '7', 'fourth'],
  ['echo', '8', 'fifth'],
  ['foxtrot', '11', 'sixth'],
]

function headerButtons(): HTMLElement[] {
  return screen.queryAllByRole('button')
}

describe('MarkdownBlock interactive tables', () => {
  it('keeps small tables plain — below the 6 body row gate', () => {
    const { container } = render(
      <MarkdownBlock
        content={table(THREE_HEADERS, SIX_ROWS.slice(0, 5))}
      />,
    )

    expect(container.querySelectorAll('tbody tr')).toHaveLength(5)
    expect(headerButtons()).toHaveLength(0)
    expect(container.querySelector('[aria-sort]')).toBeNull()
  })

  it('keeps narrow tables plain — below the 3 column gate', () => {
    const { container } = render(
      <MarkdownBlock content={table(['Name', 'Count'], SIX_ROWS.map((r) => r.slice(0, 2)))} />,
    )

    expect(container.querySelectorAll('tbody tr')).toHaveLength(6)
    expect(headerButtons()).toHaveLength(0)
  })

  it('renders a 6-row 3-column table as sortable headers in a contained scroll wrapper', () => {
    const { container } = render(
      <MarkdownBlock content={table(THREE_HEADERS, SIX_ROWS)} />,
    )

    const buttons = headerButtons()
    expect(buttons).toHaveLength(3)
    expect(buttons.map((b) => b.textContent)).toEqual(['Name', 'Count', 'Note'])
    // Every header announces its sort state (initially "none").
    const headers = container.querySelectorAll('th')
    expect([...headers].map((th) => th.getAttribute('aria-sort'))).toEqual([
      'none',
      'none',
      'none',
    ])
    // Horizontal scroll is contained by the wrapper div, not the page.
    expect(container.querySelector('table')?.parentElement).toHaveClass(
      'overflow-x-auto',
    )
  })

  it('sorts numeric columns numerically — 9 lands before 10 — and toggles aria-sort', () => {
    const { container } = render(
      <MarkdownBlock content={table(THREE_HEADERS, SIX_ROWS)} />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Count' }))

    const counts = () =>
      [...container.querySelectorAll('tbody tr')].map(
        (row) => row.children[1].textContent,
      )
    expect(counts()).toEqual(['6', '7', '8', '9', '10', '11'])
    expect(
      container.querySelector('th:nth-child(2)'),
    ).toHaveAttribute('aria-sort', 'ascending')

    fireEvent.click(screen.getByRole('button', { name: 'Count' }))
    expect(counts()).toEqual(['11', '10', '9', '8', '7', '6'])
    expect(
      container.querySelector('th:nth-child(2)'),
    ).toHaveAttribute('aria-sort', 'descending')

    // Toggling is two-state: a third click goes back to ascending.
    fireEvent.click(screen.getByRole('button', { name: 'Count' }))
    expect(counts()).toEqual(['6', '7', '8', '9', '10', '11'])
  })

  it('sorts non-numeric columns case-insensitively', () => {
    const { container } = render(
      <MarkdownBlock
        content={table(THREE_HEADERS, [
          ['Zulu', '1', 'x'],
          ['alpha', '2', 'x'],
          ['Bravo', '3', 'x'],
          ['charlie', '4', 'x'],
          ['Delta', '5', 'x'],
          ['echo', '6', 'x'],
        ])}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Name' }))
    const names = () =>
      [...container.querySelectorAll('tbody tr')].map(
        (row) => row.children[0].textContent,
      )
    expect(names()).toEqual(['alpha', 'Bravo', 'charlie', 'Delta', 'echo', 'Zulu'])
  })

  it('shows a quick filter at 10 body rows with an accessible label', () => {
    const rows = Array.from({ length: 12 }, (_, index) => [
      `row-${index}`,
      String(index),
      index === 7 ? 'needle-haystack' : 'filler',
    ])
    const { container } = render(
      <MarkdownBlock content={table(THREE_HEADERS, rows)} />,
    )

    const filter = screen.getByLabelText('Filter table rows')
    expect(filter).toBeInTheDocument()
    expect(container.querySelectorAll('tbody tr')).toHaveLength(12)

    fireEvent.change(filter, { target: { value: 'needle' } })
    expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
    expect(container.querySelector('tbody')).toHaveTextContent('needle-haystack')

    fireEvent.change(filter, { target: { value: 'zzzz' } })
    expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
    expect(screen.getByText('No matches')).toBeInTheDocument()

    fireEvent.change(filter, { target: { value: '' } })
    expect(container.querySelectorAll('tbody tr')).toHaveLength(12)
  })

  it('hides the filter below 10 body rows even when the table is sortable', () => {
    render(<MarkdownBlock content={table(THREE_HEADERS, SIX_ROWS)} />)

    expect(screen.queryByLabelText('Filter table rows')).toBeNull()
  })

  it('keeps a streaming table plain so the cursor selector still matches', async () => {
    const { container } = render(
      <MarkdownBlock
        content={table(THREE_HEADERS, SIX_ROWS)}
        isStreaming
      />,
    )

    // The streaming reveal commits on a timer frame, so wait for it.
    await waitFor(
      () => expect(container.querySelector('tbody tr')).not.toBeNull(),
      { timeout: 5_000 },
    )
    expect(headerButtons()).toHaveLength(0)
    expect(screen.queryByLabelText('Filter table rows')).toBeNull()
    // Plain path stays unwrapped: `.oa-streaming-prose > table:last-child`
    // (the streaming cursor) requires the table as a direct child.
    expect(
      container.querySelector('.oa-streaming-prose > table'),
    ).not.toBeNull()
  })
})
