export type GameStatus = 'ready' | 'playing' | 'won' | 'lost'

export interface GridPoint {
  x: number
  y: number
}

export interface SnakeState {
  width: number
  height: number
  body: GridPoint[]
  direction: GridPoint
  food: GridPoint
  score: number
  status: GameStatus
}

interface CreateSnakeOptions {
  width?: number
  height?: number
  random?: () => number
}

export function createSnakeState({
  width = 12,
  height = 10,
  random = Math.random,
}: CreateSnakeOptions = {}): SnakeState {
  if (width < 4 || height < 3) {
    throw new RangeError('Snake board must be at least 4 by 3 cells')
  }

  const head = { x: Math.floor(width / 2) - 1, y: Math.floor(height / 2) }
  const body = [head, { x: head.x - 1, y: head.y }, { x: head.x - 2, y: head.y }]
  const occupied = new Set(body.map(({ x, y }) => y * width + x))
  const freeCells = Array.from({ length: width * height }, (_, index) => index)
    .filter((index) => !occupied.has(index))
  const foodIndex = Math.min(freeCells.length - 1, Math.floor(random() * freeCells.length))
  const foodCell = freeCells[foodIndex]

  return {
    width,
    height,
    body,
    direction: { x: 1, y: 0 },
    food: { x: foodCell % width, y: Math.floor(foodCell / width) },
    score: 0,
    status: 'ready',
  }
}

export function setSnakeDirection(state: SnakeState, direction: GridPoint): SnakeState {
  const isCardinal = Math.abs(direction.x) + Math.abs(direction.y) === 1
  const isReverse = direction.x === -state.direction.x && direction.y === -state.direction.y
  if (!isCardinal || (state.body.length > 1 && isReverse)) return state
  return { ...state, direction }
}

export function advanceSnake(state: SnakeState, random: () => number = Math.random): SnakeState {
  if (state.status !== 'playing') return state

  const head = state.body[0]
  const nextHead = {
    x: head.x + state.direction.x,
    y: head.y + state.direction.y,
  }
  const eatsFood = nextHead.x === state.food.x && nextHead.y === state.food.y
  const bodyToCheck = eatsFood ? state.body : state.body.slice(0, -1)
  const hitsSelf = bodyToCheck.some(({ x, y }) => x === nextHead.x && y === nextHead.y)
  const hitsWall = nextHead.x < 0 || nextHead.y < 0 || nextHead.x >= state.width || nextHead.y >= state.height

  if (hitsWall || hitsSelf) return { ...state, status: 'lost' }

  const body = [nextHead, ...state.body.slice(0, eatsFood ? undefined : -1)]
  if (!eatsFood) return { ...state, body }

  const occupied = new Set(body.map(({ x, y }) => y * state.width + x))
  const freeCells = Array.from({ length: state.width * state.height }, (_, index) => index)
    .filter((index) => !occupied.has(index))
  if (freeCells.length === 0) return { ...state, body, score: state.score + 1, status: 'won' }

  const foodIndex = Math.min(freeCells.length - 1, Math.floor(random() * freeCells.length))
  const foodCell = freeCells[foodIndex]
  return {
    ...state,
    body,
    food: { x: foodCell % state.width, y: Math.floor(foodCell / state.width) },
    score: state.score + 1,
  }
}
