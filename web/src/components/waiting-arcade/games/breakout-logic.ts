export type BreakoutStatus = 'ready' | 'playing' | 'paused' | 'won' | 'lost'
export interface BreakoutBrick { id: number; x: number; y: number }
export interface BreakoutState {
  status: BreakoutStatus; ballX: number; ballY: number; velocityX: number; velocityY: number
  paddleX: number; bricks: BreakoutBrick[]; score: number; lives: number
}
const PADDLE_WIDTH = 18
const BRICK_ROWS = 3
const BRICK_COLUMNS = 8

export function createBreakoutState(): BreakoutState {
  const bricks = Array.from({ length: BRICK_ROWS * BRICK_COLUMNS }, (_, id) => ({ id, x: 7 + (id % BRICK_COLUMNS) * 12, y: 17 + Math.floor(id / BRICK_COLUMNS) * 8 }))
  return { status: 'ready', ballX: 50, ballY: 83, velocityX: 0, velocityY: 0, paddleX: 50, bricks, score: 0, lives: 3 }
}
export function startBreakout(state: BreakoutState): BreakoutState {
  if (state.status === 'paused') return { ...state, status: 'playing' }
  if (state.status !== 'ready') return state
  return { ...state, status: 'playing', velocityX: 0.68, velocityY: -0.78 }
}
export function moveBreakoutPaddle(state: BreakoutState, delta: number): BreakoutState {
  return { ...state, paddleX: Math.max(PADDLE_WIDTH / 2, Math.min(100 - PADDLE_WIDTH / 2, state.paddleX + delta)) }
}
export function advanceBreakout(state: BreakoutState): BreakoutState {
  if (state.status !== 'playing') return state
  let { ballX, ballY, velocityX, velocityY } = state
  let bricks = state.bricks
  let score = state.score
  ballX += velocityX
  ballY += velocityY
  if (ballX < 1.5 || ballX > 98.5) { ballX = Math.max(1.5, Math.min(98.5, ballX)); velocityX *= -1 }
  if (ballY < 5) { ballY = 5; velocityY = Math.abs(velocityY) }
  const hit = bricks.find((brick) => ballY >= brick.y - 1.5 && ballY <= brick.y + 4 && ballX >= brick.x - 5 && ballX <= brick.x + 5)
  if (hit) { bricks = bricks.filter((brick) => brick.id !== hit.id); score += 10; velocityY = Math.abs(velocityY) }
  if (ballY >= 88 && ballY <= 93 && velocityY > 0 && Math.abs(ballX - state.paddleX) <= PADDLE_WIDTH / 2 + 1) {
    ballY = 88; velocityY = -Math.abs(velocityY); velocityX += (ballX - state.paddleX) * 0.035
  }
  if (bricks.length === 0) return { ...state, bricks, score, ballX, ballY, velocityX, velocityY, status: 'won' }
  if (ballY > 101) {
    const lives = state.lives - 1
    return { ...state, lives, ballX: 50, ballY: 83, velocityX: 0, velocityY: 0, status: lives ? 'ready' : 'lost' }
  }
  return { ...state, bricks, score, ballX, ballY, velocityX, velocityY }
}
