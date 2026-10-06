import { describe, expect, it } from 'vitest'
import { create2048State, move2048, type Game2048State } from '@/components/waiting-arcade/games/2048-logic'

const state = (board: number[], score = 0): Game2048State => ({ board, score, status: 'playing' })

describe('2048 rules', () => {
  it('starts a fresh board with two tiles and no score', () => {
    const game = create2048State(() => 0)

    expect(game.board.filter(Boolean)).toHaveLength(2)
    expect(game.score).toBe(0)
    expect(game.status).toBe('playing')
  })

  it('compresses and merges each tile only once, then spawns one tile', () => {
    const game = state([
      2, 2, 2, 2,
      0, 0, 0, 0,
      0, 0, 0, 0,
      0, 0, 0, 0,
    ])

    const next = move2048(game, 'left', () => 0)

    expect(next.board.slice(0, 4)).toEqual([4, 4, 2, 0])
    expect(next.board[4]).toBe(0)
    expect(next.score).toBe(8)
    expect(next.status).toBe('playing')
  })

  it('does not change or spawn a tile when a move has no effect', () => {
    const game = state([
      2, 4, 8, 16,
      0, 0, 0, 0,
      0, 0, 0, 0,
      0, 0, 0, 0,
    ])

    expect(move2048(game, 'left', () => 0)).toBe(game)
  })

  it('moves and merges tiles in the requested column direction', () => {
    const game = state([
      2, 0, 0, 0,
      2, 0, 0, 0,
      0, 0, 0, 0,
      0, 0, 0, 0,
    ])

    const next = move2048(game, 'down', () => 0.99)

    expect([next.board[0], next.board[4], next.board[8], next.board[12]]).toEqual([0, 0, 0, 4])
    expect(next.score).toBe(4)
  })

  it('marks the game won when a merge reaches 2048', () => {
    const game = state([
      1024, 1024, 0, 0,
      0, 0, 0, 0,
      0, 0, 0, 0,
      0, 0, 0, 0,
    ])

    const next = move2048(game, 'left', () => 0)

    expect(next.board[0]).toBe(2048)
    expect(next.score).toBe(2048)
    expect(next.status).toBe('won')
  })

  it('detects a full board with no possible merge', () => {
    const game = state([
      2, 4, 2, 4,
      4, 2, 4, 2,
      2, 4, 2, 4,
      4, 2, 4, 2,
    ])

    expect(move2048(game, 'left', () => 0).status).toBe('over')
  })
})
