export type Mark = 'X' | 'O'
export type TicTacToeStatus = 'playing' | 'won' | 'draw'

export interface TicTacToeState {
  board: (Mark | null)[]
  status: TicTacToeStatus
  winner: Mark | null
}

const LINES = [
  [0, 1, 2], [3, 4, 5], [6, 7, 8],
  [0, 3, 6], [1, 4, 7], [2, 5, 8],
  [0, 4, 8], [2, 4, 6],
] as const

export function createTicTacToeState(): TicTacToeState {
  return { board: Array<Mark | null>(9).fill(null), status: 'playing', winner: null }
}

export function playTicTacToeCell(
  state: TicTacToeState,
  index: number,
  mark: Mark,
): TicTacToeState {
  if (state.status !== 'playing' || !Number.isInteger(index) || index < 0 || index > 8 || state.board[index]) return state

  const board = [...state.board]
  board[index] = mark
  const won = LINES.some(([a, b, c]) => board[a] === mark && board[b] === mark && board[c] === mark)
  const winner = won ? mark : null
  const status = won ? 'won' : board.every(Boolean) ? 'draw' : 'playing'
  return { board, status, winner }
}

export function chooseTicTacToeMove(board: readonly (Mark | null)[], botMark: Mark): number | null {
  if (board.length !== 9) return null
  const available = board.flatMap((mark, index) => mark === null ? [index] : [])
  if (available.length === 0) return null

  const winningMove = (mark: Mark) => available.find((index) => {
    const candidate = [...board]
    candidate[index] = mark
    return LINES.some(([a, b, c]) => candidate[a] === mark && candidate[b] === mark && candidate[c] === mark)
  })

  const win = winningMove(botMark)
  if (win !== undefined) return win
  const block = winningMove(botMark === 'X' ? 'O' : 'X')
  if (block !== undefined) return block
  if (board[4] === null) return 4
  const corner = [0, 2, 6, 8].find((index) => board[index] === null)
  if (corner !== undefined) return corner
  return available[0]
}
