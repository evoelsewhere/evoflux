/**
 * Hand-rolled arithmetic evaluator for the `calculator` ui_block.
 *
 * Grammar (mirrors the server-side Pydantic validation in
 * `app/agent/schemas/events.py`): numbers, declared input names,
 * `+ - * / ( )` and whitespace — nothing else. No eval/Function; anything
 * outside the grammar throws `Error` so the output row can show an inline
 * message instead of executing.
 */

export interface FormulaResult {
  ok: boolean
  value?: number
  error?: string
}

const TOKEN_RE = /\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*|[+\-*/()]/y

function tokenize(formula: string): string[] {
  const tokens: string[] = []
  let pos = 0
  while (pos < formula.length) {
    if (formula[pos].match(/\s/)) {
      pos += 1
      continue
    }
    TOKEN_RE.lastIndex = pos
    const match = TOKEN_RE.exec(formula)
    if (!match) {
      throw new Error(
        `Unsupported characters near ${JSON.stringify(formula.slice(pos, pos + 12))} — use numbers, input names, + - * / ( )`,
      )
    }
    tokens.push(match[0])
    pos = TOKEN_RE.lastIndex
  }
  if (tokens.length === 0) throw new Error('Formula is empty')
  return tokens
}

/** Evaluate a validated formula against the current input values. */
export function evaluateFormula(
  formula: string,
  values: Record<string, number>,
): FormulaResult {
  try {
    const tokens = tokenize(formula)
    let index = 0
    const peek = () => tokens[index]

    const parsePrimary = (): number => {
      const token = peek()
      if (token === undefined) throw new Error('Formula ends unexpectedly')
      if (token === '+' || token === '-') {
        index += 1
        const operand = parsePrimary()
        return token === '-' ? -operand : operand
      }
      if (token === '(') {
        index += 1
        const value = parseExpression()
        if (peek() !== ')') throw new Error('Unbalanced parentheses')
        index += 1
        return value
      }
      if (/^\d/.test(token)) {
        index += 1
        return Number(token)
      }
      index += 1
      const value = values[token]
      if (typeof value !== 'number') {
        throw new Error(`Unknown input "${token}"`)
      }
      return value
    }

    const parseTerm = (): number => {
      let value = parsePrimary()
      while (peek() === '*' || peek() === '/') {
        const operator = tokens[index]
        index += 1
        const operand = parsePrimary()
        value = operator === '*' ? value * operand : value / operand
      }
      return value
    }

    function parseExpression(): number {
      let value = parseTerm()
      while (peek() === '+' || peek() === '-') {
        const operator = tokens[index]
        index += 1
        const operand = parseTerm()
        value = operator === '+' ? value + operand : value - operand
      }
      return value
    }

    const result = parseExpression()
    if (index !== tokens.length) throw new Error('Formula has trailing tokens')
    if (!Number.isFinite(result)) throw new Error('Result is not a finite number')
    return { ok: true, value: result }
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : 'Invalid formula',
    }
  }
}
