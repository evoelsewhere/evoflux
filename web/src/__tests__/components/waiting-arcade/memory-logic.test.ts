import { describe, expect, it } from 'vitest'
import { createMemoryState, flipMemoryCard, resolveMemoryMismatch } from '@/components/waiting-arcade/games/memory-logic'

describe('Memory Pairs rules', () => {
  it('creates a 4 by 4 board with eight pairs', () => {
    const state = createMemoryState(() => 0.5)
    expect(state.cards).toHaveLength(16)
    expect(new Set(state.cards.map((card) => card.pair)).size).toBe(8)
  })

  it('matches pairs, rejects extra flips during a mismatch, then clears the mismatch', () => {
    const state = createMemoryState(() => 0)
    const first = flipMemoryCard(state, 0)
    const secondIndex = state.cards.findIndex((card, index) => index !== 0 && card.pair !== state.cards[0].pair)
    const second = flipMemoryCard(first, secondIndex)
    expect(second.openCards).toHaveLength(2)
    expect(flipMemoryCard(second, 4)).toBe(second)
    expect(resolveMemoryMismatch(second).openCards).toHaveLength(0)
  })

  it('marks a matching pair and ends after all eight pairs are found', () => {
    let state = createMemoryState(() => 0)
    const pairs = new Map<number, number[]>()
    state.cards.forEach((card, index) => pairs.set(card.pair, [...(pairs.get(card.pair) ?? []), index]))
    for (const indices of pairs.values()) {
      state = flipMemoryCard(state, indices[0])
      state = flipMemoryCard(state, indices[1])
    }
    expect(state.pairsFound).toBe(8)
    expect(state.status).toBe('won')
  })
})
