import { describe, expect, it } from 'vitest'

import { parseTeamBlocks } from '@/utils/messages'
import type { MessageResponse } from '@/api/types'
import { runtimeTurnMessages } from './runtime-turn.fixture'

// The live demo session delivers every message of the seeded runtime turn with
// one identical created_at, and the history endpoint tie-breaks by message id —
// so call_rt2's replace_id replace (no block_id) arrives BEFORE call_rt1's
// block_id create. History reconstruction must converge on the replace's
// content either way (spec §1.4 rule 3, §1.6 rule 4).
describe('ui_block history reconstruction (real demo payload)', () => {
  const groups = parseTeamBlocks(runtimeTurnMessages).filter((b) => b.type === 'ui_block')

  it('rebuilds a single launch-plan group', () => {
    expect(groups).toHaveLength(1)
    expect(groups[0].uiBlockIdentity).toBe('launch-plan')
    expect(groups[0].title).toBe('Launch plan')
  })

  it('applies the replace_id call even though it arrives before the block_id create', () => {
    const rendered = JSON.stringify(groups[0].uiBlocks)
    // rt2 checklist: "Publish changelog" only exists in the replace payload.
    expect(rendered).toContain('Publish changelog')
    // The replace swept wholesale (§1.4 rule 3): rt1's custom sibling is gone.
    expect((groups[0].uiBlocks ?? []).map((n) => n.type)).toEqual(['layout'])
  })

  it("attaches the replace call's tool result to the converged group", () => {
    expect(groups[0].toolResult).toContain('"replace_id"')
    expect(groups[0].toolDone).toBe(true)
  })

  it('converges identically when the create arrives before the replace', () => {
    // Same messages, reordered so the block_id create precedes the replace —
    // both arrival orders must produce the replace's final content.
    const reordered = [...runtimeTurnMessages].sort((a, b) => {
      const aCall = a.tool_calls?.[0]?.id === 'call_rt1' ? 0 : 1
      const bCall = b.tool_calls?.[0]?.id === 'call_rt1' ? 0 : 1
      return aCall - bCall
    })
    const group = parseTeamBlocks(reordered as MessageResponse[]).find(
      (b) => b.type === 'ui_block',
    )
    expect(JSON.stringify(group?.uiBlocks)).toContain('Publish changelog')
    expect((group?.uiBlocks ?? []).map((n) => n.type)).toEqual(['layout'])
  })
})

describe('ui_block replace-seeded group', () => {
  const call = (id: string, args: Record<string, unknown>, order: number): MessageResponse =>
    ({
      id: `m${order}`,
      role: 'assistant',
      content: '',
      created_at: '2026-01-01T00:00:00Z',
      tool_calls: [{ id, type: 'function', function: { name: 'ui_block', arguments: JSON.stringify(args) } }],
    }) as unknown as MessageResponse
  const text = (blocks: unknown) => JSON.stringify(blocks)
  const node = (label: string) => [{ type: 'text', text: label }]

  it('keeps the replace over the one late original, then lets a later upsert win', () => {
    const group = parseTeamBlocks([
      call('c-replace', { replace_id: 'g', blocks: node('REPLACED') }, 1),
      call('c-original', { block_id: 'g', blocks: node('ORIGINAL') }, 2),
      call('c-restart', { block_id: 'g', blocks: node('RESTARTED') }, 3),
    ]).find((b) => b.type === 'ui_block')
    expect(text(group?.uiBlocks)).toContain('RESTARTED')
  })

  it('ignores only the late original', () => {
    const group = parseTeamBlocks([
      call('c-replace', { replace_id: 'g', blocks: node('REPLACED') }, 1),
      call('c-original', { block_id: 'g', blocks: node('ORIGINAL') }, 2),
    ]).find((b) => b.type === 'ui_block')
    expect(text(group?.uiBlocks)).toContain('REPLACED')
    expect(text(group?.uiBlocks)).not.toContain('ORIGINAL')
  })
})
