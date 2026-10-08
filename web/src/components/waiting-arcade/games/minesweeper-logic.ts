export type MinefieldStatus = 'ready' | 'playing' | 'won' | 'lost'

export interface MineCell {
  mine: boolean
  adjacent: number
  revealed: boolean
  flagged: boolean
}

export interface MinefieldState {
  cells: MineCell[]
  status: MinefieldStatus
}

const SIZE = 6
const CELL_COUNT = SIZE * SIZE

function neighborsOf(index: number): number[] {
  const row = Math.floor(index / SIZE)
  const column = index % SIZE
  const neighbors: number[] = []
  for (let y = Math.max(0, row - 1); y <= Math.min(SIZE - 1, row + 1); y += 1) {
    for (let x = Math.max(0, column - 1); x <= Math.min(SIZE - 1, column + 1); x += 1) {
      const neighbor = y * SIZE + x
      if (neighbor !== index) neighbors.push(neighbor)
    }
  }
  return neighbors
}

export function createMinefield(mineIndices: readonly number[]): MinefieldState {
  const mines = new Set(mineIndices)
  if (mines.size !== mineIndices.length || [...mines].some((index) => !Number.isInteger(index) || index < 0 || index >= CELL_COUNT)) {
    throw new RangeError('Mine indices must be unique cells from 0 to 35')
  }

  return {
    cells: Array.from({ length: CELL_COUNT }, (_, index) => ({
      mine: mines.has(index),
      adjacent: neighborsOf(index).filter((neighbor) => mines.has(neighbor)).length,
      revealed: false,
      flagged: false,
    })),
    status: 'ready',
  }
}

export function revealMineCell(state: MinefieldState, index: number): MinefieldState {
  if (state.status === 'won' || state.status === 'lost' || !Number.isInteger(index) || index < 0 || index >= CELL_COUNT) return state
  const selected = state.cells[index]
  if (selected.revealed || selected.flagged) return state

  const cells = state.cells.map((cell) => ({ ...cell }))
  if (selected.mine) {
    cells[index].revealed = true
    return { cells, status: 'lost' }
  }

  const pending = [index]
  const queued = new Set<number>()
  while (pending.length > 0) {
    const current = pending.shift()!
    if (queued.has(current)) continue
    queued.add(current)
    const cell = cells[current]
    if (cell.revealed || cell.flagged || cell.mine) continue
    cell.revealed = true
    if (cell.adjacent === 0) pending.push(...neighborsOf(current))
  }

  const won = cells.every((cell) => cell.mine || cell.revealed)
  return { cells, status: won ? 'won' : 'playing' }
}

export function toggleMineFlag(state: MinefieldState, index: number): MinefieldState {
  if (state.status === 'won' || state.status === 'lost' || !Number.isInteger(index) || index < 0 || index >= CELL_COUNT) return state
  const cell = state.cells[index]
  if (cell.revealed) return state
  const cells = state.cells.map((current) => ({ ...current }))
  cells[index].flagged = !cell.flagged
  return { ...state, cells, status: state.status === 'ready' ? 'playing' : state.status }
}
