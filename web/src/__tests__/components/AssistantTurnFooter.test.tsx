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

    // 9,000 of the 12,400 input tokens were cache reads, so the volume and
    // the price only agree once the share is stated.
    expect(screen.getByText('13.6k tokens · 73% cached')).toBeVisible()
    expect(screen.getByText('$0.031')).toBeVisible()
  })

  // The headline used to read as spend. `input` is summed over every model
  // call in a turn, so a cached prompt is counted once per call: a measured
  // three-call turn showed 58,798 input tokens of which 38,592 were cache
  // reads, next to a cost of $0.003. Multiplying the two gave three times
  // the truth.
  it('says how much of the volume was cached', () => {
    render(
      <AssistantTurnFooter
        turnBlocks={[textBlock({
          input: 58_798,
          output: 393,
          cache: 38_592,
          calls: 3,
          cost: { estimated_usd: 0.00305 },
        })]}
      />,
    )

    expect(screen.getByText('59.2k tokens · 66% cached')).toBeVisible()
  })

  // Cache writes are part of `input` too, and they bill above the input
  // rate rather than below it, so a write-heavy turn is the same trap
  // pointing the other way: the price is higher than the volume implies.
  it('names a write-heavy prompt as written, not cached', () => {
    render(
      <AssistantTurnFooter
        turnBlocks={[textBlock({
          input: 19_119,
          output: 84,
          cache: 0,
          cache_write: 18_004,
          calls: 1,
          cost: { estimated_usd: 0.0271 },
        })]}
      />,
    )

    expect(screen.getByText('19.2k tokens · 94% written')).toBeVisible()
  })

  // The ordinary shape of a multi-call turn: the first call writes the
  // prompt into the cache and the rest read it back.
  it('states both shares when a turn wrote and then reused a prompt', () => {
    render(
      <AssistantTurnFooter
        turnBlocks={[textBlock({
          input: 58_798,
          output: 393,
          cache: 38_592,
          cache_write: 13_100,
          calls: 3,
          cost: { estimated_usd: 0.0181 },
        })]}
      />,
    )

    expect(screen.getByText('59.2k tokens · 66% cached, 22% written')).toBeVisible()
  })

  it('stays quiet about cache when barely any was reused', () => {
    render(
      <AssistantTurnFooter
        turnBlocks={[textBlock({
          input: 19_119,
          output: 84,
          cache: 0,
          calls: 1,
          cost: { estimated_usd: 0.0027 },
        })]}
      />,
    )

    // A first, uncached call has nothing to explain away.
    expect(screen.getByText('19.2k tokens')).toBeVisible()
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

    expect(
      screen.getByText('13.6k tokens · 73% cached').getAttribute('title'),
    ).toContain('of which cached 9,000')
    expect(screen.getByText('$0.031').getAttribute('title')).toContain('Cache read')
    expect(screen.getByText('$0.031').getAttribute('title')).toContain('models.dev')
  })
})
