import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { UiLayout } from '@/components/ui/UiLayout'
import type { UiBlockNode, UiLayoutBlock } from '@/components/ui/ui-block-types'

const callout = (body: string): UiBlockNode => ({ type: 'callout', body })

const layout = (overrides: Partial<UiLayoutBlock> = {}): UiLayoutBlock => ({
  type: 'layout',
  orientation: 'columns',
  sections: [{ children: [callout('child a')] }],
  ...overrides,
})

describe('UiLayout', () => {
  it('renders a columns layout as an auto-fit grid', () => {
    const { container } = render(
      <UiLayout block={layout({ orientation: 'columns' })} depth={0} renderChild={() => null} />,
    )
    const root = container.firstElementChild
    expect(root?.className).toContain('grid')
    expect(root?.className).not.toContain('flex-col')
  })

  it('renders a stack layout as a vertical flex column', () => {
    const { container } = render(
      <UiLayout block={layout({ orientation: 'stack' })} depth={0} renderChild={() => null} />,
    )
    const root = container.firstElementChild
    expect(root?.className).toContain('flex-col')
    expect(root?.className).not.toContain('grid')
  })

  it('renders the section title when present', () => {
    render(
      <UiLayout
        block={layout({ sections: [{ title: 'CPU', children: [callout('x')] }] })}
        depth={0}
        renderChild={() => null}
      />,
    )
    expect(screen.getByText('CPU')).toBeInTheDocument()
  })

  it('omits the title element when the section has no title', () => {
    const { container } = render(
      <UiLayout block={layout()} depth={0} renderChild={() => null} />,
    )
    expect(container.querySelectorAll('p')).toHaveLength(0)
  })

  it('renders every section child through renderChild with depth + 1', () => {
    const renderChild = vi.fn().mockReturnValue(<span data-testid="stub" />)
    const block = layout({
      sections: [
        { title: 'One', children: [callout('a'), callout('b')] },
        { title: 'Two', children: [callout('c')] },
      ],
    })
    render(<UiLayout block={block} depth={1} renderChild={renderChild} />)
    expect(renderChild).toHaveBeenCalledTimes(3)
    expect(renderChild.mock.calls.map(([child]) => (child as { body: string }).body)).toEqual([
      'a',
      'b',
      'c',
    ])
    // Depth mirror: children render one level deeper than their layout.
    expect(renderChild.mock.calls.every(([, depth]) => depth === 2)).toBe(true)
    expect(screen.getAllByTestId('stub')).toHaveLength(3)
  })

  it('renders no nested UiBlockRenderer chrome with a stub renderChild', () => {
    // UiLayout must stay cycle-free (spec §2.2): it renders children only
    // through the renderChild prop, so no nested renderer status paragraph
    // appears when the stub returns nothing.
    const { container } = render(
      <UiLayout block={layout()} depth={0} renderChild={() => null} />,
    )
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(container.firstElementChild).not.toHaveAttribute('aria-live')
  })
})
