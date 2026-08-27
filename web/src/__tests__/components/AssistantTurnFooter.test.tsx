import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AssistantTurnFooter } from '@/components/AssistantTurnFooter'
import type { ContentBlock } from '@/api/types'

function submitBlock(result: string): ContentBlock {
  return {
    id: 'submit-spec',
    type: 'tool',
    content: '',
    toolName: 'easd_submit_specification',
    toolArgs: JSON.stringify({ run_id: 'run-1' }),
    toolResult: result,
    toolDone: true,
    timestamp: new Date('2026-08-27T00:00:00Z'),
  }
}

describe('AssistantTurnFooter EASD completion', () => {
  it('uses the persisted review action instead of generic Continue after success', () => {
    render(
      <AssistantTurnFooter
        turnBlocks={[submitBlock('Specification draft persisted for user review. revision=rev-1 hash=abc.')]}
        onContinue={vi.fn()}
      />,
    )

    expect(screen.queryByRole('button', { name: 'Continue response' })).not.toBeInTheDocument()
  })

  it('keeps Continue available after a rejected submission', () => {
    render(
      <AssistantTurnFooter
        turnBlocks={[submitBlock('Error: invalid verification command')]}
        onContinue={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: 'Continue response' })).toBeInTheDocument()
  })
})
