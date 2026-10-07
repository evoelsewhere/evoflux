export type Game2048Direction = 'up' | 'right' | 'down' | 'left'
export type Game2048Status = 'playing' | 'won' | 'over'

export interface Game2048State {
  board: number[]
  score: number
  status: Game2048Status
}

const SIZE = 4

function spawnTile(board: number[], random: () => number): number[] {
  const empty = board.flatMap((value, index) => value === 0 ? [index] : [])
  if (empty.length === 0) return board
  const index = empty[Math.min(empty.length - 1, Math.floor(random() * empty.length))]
  const next = [...board]
  next[index] = random() < 0.9 ? 2 : 4
  return next
}

function lineFor(direction: Game2048Direction, line: number): number[] {
  return Array.from({ length: SIZE }, (_, offset) => {
    const row = direction === 'down' ? SIZE - 1 - offset : direction === 'up' ? offset : line
    const column = direction === 'right' ? SIZE - 1 - offset : direction === 'left' ? offset : line
    return row * SIZE + column
  })
}

export function get2048MergeCells(board: readonly number[], direction: Game2048Direction): number[] {
  const mergedCells: number[] = []
  for (let line = 0; line < SIZE; line += 1) {
    const indices = lineFor(direction, line)
    const sources = indices.filter((index) => board[index] > 0)
    let destination = 0
    for (let source = 0; source < sources.length; source += 1) {
      if (board[sources[source]] === board[sources[source + 1]]) {
        mergedCells.push(indices[destination])
        source += 1
      }
      destination += 1
    }
  }
  return mergedCells
}

function hasMoves(board: readonly number[]): boolean {
  for (let row = 0; row < SIZE; row += 1) {
    for (let column = 0; column < SIZE; column += 1) {
      const index = row * SIZE + column
      if (board[index] === 0) return true
      if (column < SIZE - 1 && board[index] === board[index + 1]) return true
      if (row < SIZE - 1 && board[index] === board[index + SIZE]) return true
    }
  }
  return false
}

export function create2048State(random: () => number = Math.random): Game2048State {
  const empty = Array<number>(SIZE * SIZE).fill(0)
  return {
    board: spawnTile(spawnTile(empty, random), random),
    score: 0,
    status: 'playing',
  }
}

export function move2048(
  state: Game2048State,
  direction: Game2048Direction,
  random: () => number = Math.random,
): Game2048State {
  if (state.status !== 'playing') return state

  const board = [...state.board]
  let score = state.score
  for (let line = 0; line < SIZE; line += 1) {
    const indices = lineFor(direction, line)
    const values = indices.map((index) => state.board[index]).filter(Boolean)
    const merged: number[] = []
    for (let index = 0; index < values.length; index += 1) {
      if (values[index] === values[index + 1]) {
        const value = values[index] * 2
        merged.push(value)
        score += value
        index += 1
      } else {
        merged.push(values[index])
      }
    }
    indices.forEach((index, offset) => { board[index] = merged[offset] ?? 0 })
  }

  const moved = board.some((value, index) => value !== state.board[index])
  if (!moved) return hasMoves(board) ? state : { ...state, status: 'over' }

  const won = board.includes(2048)
  const nextBoard = won ? board : spawnTile(board, random)
  return {
    board: nextBoard,
    score,
    status: won ? 'won' : hasMoves(nextBoard) ? 'playing' : 'over',
  }
}
