import { describe, expect, it } from 'vitest'
import { parseGoalCommand } from '@/lib/parseGoalCommand'

describe('parseGoalCommand', () => {
  it('distinguishes status from starting a goal', () => {
    expect(parseGoalCommand('/goal')).toEqual({ kind: 'status' })
    expect(parseGoalCommand('/goal:status')).toEqual({ kind: 'status' })
    expect(parseGoalCommand('/goal ship the release')).toEqual({
      kind: 'start',
      objective: 'ship the release',
    })
  })

  it('accepts positive and unlimited token budgets', () => {
    expect(parseGoalCommand('/goal:budget 12000')).toEqual({
      kind: 'budget',
      tokenBudget: 12000,
    })
    expect(parseGoalCommand('/goal:budget none')).toEqual({
      kind: 'budget',
      tokenBudget: null,
    })
    expect(parseGoalCommand('/goal:budget 0')).toEqual({ kind: 'budget_invalid' })
  })

  it('rejects malformed controls without claiming unrelated input', () => {
    expect(parseGoalCommand('/goal:pause now')).toEqual({ kind: 'invalid' })
    expect(parseGoalCommand('/goal:set 10')).toEqual({ kind: 'invalid' })
    expect(parseGoalCommand('/goals')).toEqual({ kind: 'none' })
  })
})
