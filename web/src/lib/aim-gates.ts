export interface AimGateQuestionItem {
  question: string
  options: string[]
}

export function emptyAimGateAnswers(items: AimGateQuestionItem[]): string[] {
  return items.map(() => '')
}

export function withAimGateAnswer(answers: string[], index: number, value: string): string[] {
  const next = [...answers]
  next[index] = value
  return next
}

export function aimGateAnswersComplete(items: AimGateQuestionItem[], answers: string[]): boolean {
  return items.length > 0 && items.every((_, index) => Boolean(answers[index]?.trim()))
}

export function normalizeAimGateAnswers(answers: string[]): string[] {
  return answers.map((answer) => answer.trim())
}
