import { describe, expect, it } from 'vitest'
import { advanceBreakout, createBreakoutState, moveBreakoutPaddle, startBreakout } from '@/components/waiting-arcade/games/breakout-logic'

describe('Mini Breakout rules', () => {
  it('starts ready and clamps paddle movement to the board', () => {
    const ready = createBreakoutState()
    expect(ready.status).toBe('ready')
    expect(moveBreakoutPaddle(ready, -1000).paddleX).toBeGreaterThanOrEqual(0)
    expect(moveBreakoutPaddle(ready, 1000).paddleX).toBeLessThanOrEqual(100)
  })

  it('launches and advances the ball while playing', () => {
    const playing = startBreakout(createBreakoutState())
    const next = advanceBreakout(playing)
    expect(next.status).toBe('playing')
    expect(next.ballY).not.toBe(playing.ballY)
  })

  it('removes hit bricks and awards points', () => {
    const state = { ...startBreakout(createBreakoutState()), ballX: 8, ballY: 20, velocityX: 0, velocityY: -2 }
    const next = advanceBreakout(state)
    expect(next.bricks.length).toBeLessThan(state.bricks.length)
    expect(next.score).toBeGreaterThan(0)
  })
})
