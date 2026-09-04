/**
 * The label for an agent's current turn phase.
 *
 * Three call sites derived this independently and a fourth rendered the
 * default, so the main transcript said "Preparing" for the whole model call
 * — through the thinking and the answer — even though the store knew the
 * phase the moment the request went out.
 *
 * `ingress` is EvoFlux still assembling the turn; `model_calling` is the
 * provider having it. Those are the only two phases worth naming, and the
 * distinction matters because the second is usually the long one.
 */
export function activityLabelForPhase(
  phase: string | null | undefined,
): 'Thinking' | 'Preparing' {
  return phase === 'model_calling' ? 'Thinking' : 'Preparing'
}
