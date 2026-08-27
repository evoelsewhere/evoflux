export interface EasdToolReviewTarget {
  runId: string
  label: 'Review specification' | 'Review plan'
}

export function easdToolReviewTarget(
  toolName: string | undefined,
  rawArgs: string | undefined,
  result: string | undefined,
): EasdToolReviewTarget | null {
  const label = toolName === 'easd_submit_specification'
    ? 'Review specification'
    : toolName === 'easd_submit_plan'
      ? 'Review plan'
      : null
  if (!label || !rawArgs || !result) return null
  const successPrefix = toolName === 'easd_submit_specification'
    ? 'Specification draft persisted for user review.'
    : 'Plan draft persisted for user review.'
  if (!result.startsWith(successPrefix)) return null
  try {
    const parsed = JSON.parse(rawArgs) as { run_id?: unknown }
    return typeof parsed.run_id === 'string' && parsed.run_id.trim()
      ? { runId: parsed.run_id, label }
      : null
  } catch {
    return null
  }
}
