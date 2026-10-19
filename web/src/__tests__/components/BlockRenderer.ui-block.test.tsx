import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { BlockRenderer } from '@/components/BlockRenderer'
import type { ContentBlock } from '@/api/types'

describe('BlockRenderer ui_block case (spec §5.5 wiring)', () => {
  it('renders a ui_block block through the catalog renderer', () => {
    const block: ContentBlock = {
      id: 'b1',
      type: 'ui_block',
      content: '',
      toolCallId: 'call-1',
      title: 'metrics',
      uiBlocks: [
        { type: 'stat_cards', cards: [{ label: 'CPU', value: 42 }] },
        { type: 'progress', label: 'Upload', value: 1, max: 4 },
      ],
    }
    render(<BlockRenderer block={block} isStreaming={false} />)
    expect(screen.getByText('metrics')).toBeInTheDocument()
    expect(screen.getByText('CPU')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '1')
  })

  it('renders an unsupported card for a block with unknown nodes', () => {
    const block: ContentBlock = {
      id: 'b2',
      type: 'ui_block',
      content: '',
      toolCallId: 'call-2',
      uiBlocks: [{ type: 'hologram' } as never],
    }
    render(<BlockRenderer block={block} isStreaming={false} />)
    expect(screen.getByText(/Unsupported block/)).toBeInTheDocument()
  })
})
