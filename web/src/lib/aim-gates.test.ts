import { describe, expect, it } from 'vitest'
import {
  aimGateAnswersComplete,
  emptyAimGateAnswers,
  normalizeAimGateAnswers,
  withAimGateAnswer,
  type AimGateQuestionItem,
} from './aim-gates'

const ITEMS: AimGateQuestionItem[] = [
  { question: 'Choose a strategy', options: ['approve', 'hold'] },
  { question: 'Explain the decision', options: [] },
]

describe('AIM batched gate answers', () => {
  it('keeps one ordered answer slot per question', () => {
    const empty = emptyAimGateAnswers(ITEMS)
    const selected = withAimGateAnswer(empty, 0, 'approve')
    const completed = withAimGateAnswer(selected, 1, 'because evidence passed')

    expect(empty).toEqual(['', ''])
    expect(selected).toEqual(['approve', ''])
    expect(completed).toEqual(['approve', 'because evidence passed'])
    expect(aimGateAnswersComplete(ITEMS, completed)).toBe(true)
  })

  it('does not submit a partial or whitespace-only batch', () => {
    expect(aimGateAnswersComplete(ITEMS, ['approve', '   '])).toBe(false)
    expect(aimGateAnswersComplete([], [])).toBe(false)
  })

  it('normalizes free text without changing answer order', () => {
    expect(normalizeAimGateAnswers([' approve ', '  reviewed by release lead  '])).toEqual([
      'approve',
      'reviewed by release lead',
    ])
  })
})
