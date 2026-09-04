import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AssistantTurnFooter } from '@/components/AssistantTurnFooter'
import type { ContentBlock, TurnUsage } from '@/api/types'

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

function textBlock(turnUsage?: TurnUsage): ContentBlock {
  return {
    id: 'text-1',
    type: 'text',
    content: 'Done.',
    responseDurationMs: 383_000,
    turnUsage,
    timestamp: new Date('2026-09-04T08:57:00Z'),
  }
}

describe('AssistantTurnFooter spend', () => {
  it('reports what the turn cost next to what it took', () => {
    render(
      <AssistantTurnFooter
        turnBlocks={[textBlock({
          input: 12_400,
          output: 1_200,
          cache: 9_000,
          calls: 3,
          cost: { estimated_usd: 0.0312, input_usd: 0.0102, output_usd: 0.021 },
        })]}
      />,
    )

    expect(screen.getByText('13.6k tokens')).toBeVisible()
    expect(screen.getByText('$0.031')).toBeVisible()
  })

  // A turn that spends a twentieth of a cent is the common case. Two
  // decimals would print `$0.00` and read as a broken number.
  it('does not round a sub-cent turn away to zero', () => {
    render(
      <AssistantTurnFooter
        turnBlocks={[textBlock({
          input: 900,
          output: 40,
          cost: { estimated_usd: 0.0004 },
        })]}
      />,
    )

    expect(screen.getByText('<$0.001')).toBeVisible()
  })

  // Copilot and Codex bill a seat. Tokens are real; a dollar figure is not.
  it('shows tokens without a price when the provider does not bill by token', () => {
    render(<AssistantTurnFooter turnBlocks={[textBlock({ input: 5_000, output: 500 })]} />)

    expect(screen.getByText('5.5k tokens')).toBeVisible()
    expect(screen.queryByText(/^\$/)).not.toBeInTheDocument()
  })

  it('says nothing at all when the turn reported no usage', () => {
    render(<AssistantTurnFooter turnBlocks={[textBlock()]} />)

    expect(screen.queryByText(/tokens$/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^\$/)).not.toBeInTheDocument()
  })

  it('breaks the spend down on hover', () => {
    render(
      <AssistantTurnFooter
        turnBlocks={[textBlock({
          input: 12_400,
          output: 1_200,
          cache: 9_000,
          thoughts: 400,
          calls: 3,
          cost: { estimated_usd: 0.0312, cache_read_usd: 0.0027, output_usd: 0.021 },
        })]}
      />,
    )

    expect(screen.getByText('13.6k tokens').getAttribute('title')).toContain(
      'of which cached 9,000',
    )
    expect(screen.getByText('$0.031').getAttribute('title')).toContain('Cache read')
    expect(screen.getByText('$0.031').getAttribute('title')).toContain('models.dev')
  })
})
