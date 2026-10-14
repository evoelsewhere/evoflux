import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { BlockRenderer } from '@/components/BlockRenderer'
import type { ContentBlock } from '@/api/types'
import type { UiBlockNode } from '@/components/ui/ui-block-types'
import { runtimeTurnMessages } from '../utils/runtime-turn.fixture'

// History-delivered node shape: call_rt1's blocks as the /team/{sid}/history
// endpoint returns them ({type:'custom', title, html, height} next to a layout
// sibling at the root of uiBlocks). The root-level dispatch in UiBlockRenderer
// must mount UiCustom -> WidgetRenderer with the widget's srcdoc.
function callRt1Blocks(): UiBlockNode[] {
  const call = runtimeTurnMessages
    .flatMap((m) => m.tool_calls ?? [])
    .find((t) => t.id === 'call_rt1')
  const args = JSON.parse(call?.function?.arguments ?? '{}')
  return (args.blocks ?? []) as UiBlockNode[]
}

describe('root-level custom node in a history ui_block group', () => {
  it('renders the WidgetRenderer iframe with the custom html', () => {
    const block: ContentBlock = {
      id: '08d54c20:ui_block:launch-plan',
      type: 'ui_block',
      content: '',
      toolCallId: 'call_rt1',
      uiBlockIdentity: 'launch-plan',
      title: 'Launch plan',
      isStreaming: false,
      uiBlocks: callRt1Blocks(),
    }

    render(<BlockRenderer block={block} isStreaming={false} />)

    // layout sibling still renders alongside it
    expect(screen.getByText('Milestones')).toBeInTheDocument()

    const iframe = document.querySelector('iframe')
    expect(iframe).not.toBeNull()
    expect(iframe?.getAttribute('srcdoc') ?? '').toContain('Week 1-4 burn-up')
  })
})
