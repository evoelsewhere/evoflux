import { describe, expect, it } from 'vitest'
import {
  advanceSnake,
  createSnakeState,
  setSnakeDirection,
} from '@/components/waiting-arcade/games/snake-logic'
import {
  createMinefield,
  revealMineCell,
  toggleMineFlag,
} from '@/components/waiting-arcade/games/minesweeper-logic'
import {
  chooseTicTacToeMove,
  createTicTacToeState,
  playTicTacToeCell,
} from '@/components/waiting-arcade/games/tic-tac-toe-logic'

describe('snake rules', () => {
  it('moves one cell in the current direction', () => {
    const state = createSnakeState({ width: 8, height: 6, random: () => 0 })
    const moved = advanceSnake({ ...state, status: 'playing' })

    expect(moved.body[0]).toEqual({ x: 4, y: 3 })
    expect(moved.body).toHaveLength(state.body.length)
  })

  it('grows and scores when the head reaches food', () => {
    const state = createSnakeState({ width: 8, height: 6, random: () => 0 })
    const eating = {
      ...state,
      status: 'playing' as const,
      food: { x: state.body[0].x + 1, y: state.body[0].y },
    }

    const moved = advanceSnake(eating, () => 0.99)

    expect(moved.body).toHaveLength(state.body.length + 1)
    expect(moved.score).toBe(1)
    expect(moved.food).not.toEqual(eating.food)
  })

  it('ends when the head reaches a wall', () => {
    const state = createSnakeState({ width: 8, height: 6, random: () => 0 })
    const atWall = {
      ...state,
      status: 'playing' as const,
      body: [{ x: 7, y: 2 }, { x: 6, y: 2 }],
      direction: { x: 1, y: 0 },
    }

    expect(advanceSnake(atWall).status).toBe('lost')
  })

  it('rejects an immediate reverse direction', () => {
    const state = createSnakeState({ width: 8, height: 6, random: () => 0 })

    expect(setSnakeDirection(state, { x: -1, y: 0 }).direction).toEqual(state.direction)
  })
})

describe('Minesweeper rules', () => {
  it('counts adjacent mines and expands empty cells', () => {
    const field = createMinefield([0, 35])

    expect(field.cells[1].adjacent).toBe(1)
    expect(field.cells[7].adjacent).toBe(1)
    expect(field.cells[14].adjacent).toBe(0)
    const revealed = revealMineCell(field, 14)
    expect(revealed.cells[14].revealed).toBe(true)
    expect(revealed.cells[14 + 1].revealed).toBe(true)
    expect(revealed.cells[0].revealed).toBe(false)
    expect(revealed.cells[35].revealed).toBe(false)
  })

  it('flags and unflags a covered cell without revealing it', () => {
    const field = createMinefield([0, 35])
    const flagged = toggleMineFlag(field, 1)

    expect(flagged.cells[1]).toMatchObject({ flagged: true, revealed: false })
    expect(toggleMineFlag(flagged, 1).cells[1].flagged).toBe(false)
  })

  it('loses on a mine and rejects another reveal after a terminal state', () => {
    const field = createMinefield([0, 35])
    const lost = revealMineCell(field, 0)

    expect(lost.status).toBe('lost')
    expect(revealMineCell(lost, 1)).toBe(lost)
  })

  it('wins after revealing every safe cell', () => {
    const field = createMinefield([0, 35])
    const won = field.cells.reduce(
      (current, cell, index) => cell.mine ? current : revealMineCell(current, index),
      field,
    )

    expect(won.status).toBe('won')
  })
})

describe('Tic-tac-toe rules', () => {
  it('rejects occupied cells and recognizes wins and draws', () => {
    const initial = createTicTacToeState()
    const first = playTicTacToeCell(initial, 0, 'X')
    expect(playTicTacToeCell(first, 0, 'O')).toBe(first)

    const win = ['X', 'X', null, 'O', 'O', null, null, null, null] as const
    expect(playTicTacToeCell({ board: [...win], status: 'playing', winner: null }, 2, 'X').status).toBe('won')

    const draw = ['X', 'O', 'X', 'X', 'O', 'O', 'O', 'X', null] as const
    expect(playTicTacToeCell({ board: [...draw], status: 'playing', winner: null }, 8, 'X').status).toBe('draw')
  })

  it('takes a win, blocks a loss, then prefers center and corners', () => {
    expect(chooseTicTacToeMove(['O', 'O', null, 'X', 'X', null, null, null, null], 'O')).toBe(2)
    expect(chooseTicTacToeMove(['X', 'X', null, 'O', null, null, null, null, null], 'O')).toBe(2)
    expect(chooseTicTacToeMove(['X', null, null, null, null, null, null, null, null], 'O')).toBe(4)
    expect(chooseTicTacToeMove(['X', null, null, null, 'O', null, null, null, null], 'O')).toBe(2)
  })
})
