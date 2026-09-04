/**
 * Formatters for a turn's meta run — duration, tokens, cost.
 *
 * The live status line and the completed turn's footer print the same three
 * facts a second apart. Sharing the formatters is what stops the numbers from
 * reformatting themselves the moment a turn ends.
 */

export function formatTurnDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`

  const totalSeconds = Math.round(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}m ${seconds}s`
}

/**
 * Token counts, at one decimal through the range turns actually land in.
 *
 * Most turns are between a few thousand and a couple of hundred thousand
 * tokens, and rounding those to whole thousands makes neighbouring turns
 * look identical. Past 100k the decimal stops earning its width.
 */
export function formatTurnTokens(count: number): string {
  if (count < 1000) return String(count)
  if (count < 1_000_000) {
    const thousands = count / 1000
    return `${thousands < 100 ? thousands.toFixed(1) : Math.round(thousands)}k`
  }
  return `${(count / 1_000_000).toFixed(1)}M`
}

/**
 * A turn's cost, at a precision that stays honest.
 *
 * Sub-cent turns are the common case, so rounding to two decimals would
 * print `$0.00` for most of them and make the number look broken. Anything
 * below a tenth of a cent is not worth four decimals either — it reads as
 * free, and saying so is clearer than `$0.0004`.
 */
export function formatTurnCost(usd: number): string {
  if (usd <= 0) return '$0'
  if (usd < 0.001) return '<$0.001'
  if (usd < 1) return `$${usd.toFixed(3)}`
  if (usd < 100) return `$${usd.toFixed(2)}`
  return `$${Math.round(usd)}`
}

/** Provider/vendor prefixes trimmed off a model id for display. */
export function shortModelName(modelId: string | null | undefined): string | null {
  if (!modelId) return null
  return modelId.split(':').at(-1)?.split('/').at(-1) || modelId
}
