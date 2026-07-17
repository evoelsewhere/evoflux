/**
 * One-shot handoffs between AIM feature surfaces (Overview → Pipelines,
 * Overview → KB). A unit's quick actions pre-fill the target screen's
 * form/selection without threading state through the router — the value
 * is consumed exactly once on the target's next mount.
 *
 * sessionStorage on purpose: these are ephemeral UI intents, not
 * shareable state (deep-linkable state — project/feature/run — already
 * lives in the URL).
 */

const PIPELINE_KEY = 'oa-aim-pipeline-prefill'
const KB_KEY = 'oa-aim-kb-open'

export interface AimPipelinePrefill {
  pipeline: string
  unit?: string
  wave?: number
}

export function setAimPipelinePrefill(prefill: AimPipelinePrefill): void {
  try {
    sessionStorage.setItem(PIPELINE_KEY, JSON.stringify(prefill))
  } catch {
    // ignore storage failures
  }
}

export function takeAimPipelinePrefill(): AimPipelinePrefill | null {
  try {
    const raw = sessionStorage.getItem(PIPELINE_KEY)
    sessionStorage.removeItem(PIPELINE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as AimPipelinePrefill
    return typeof parsed?.pipeline === 'string' ? parsed : null
  } catch {
    return null
  }
}

export function setAimKbOpenPath(path: string): void {
  try {
    sessionStorage.setItem(KB_KEY, path)
  } catch {
    // ignore storage failures
  }
}

export function takeAimKbOpenPath(): string | null {
  try {
    const raw = sessionStorage.getItem(KB_KEY)
    sessionStorage.removeItem(KB_KEY)
    return raw
  } catch {
    return null
  }
}
