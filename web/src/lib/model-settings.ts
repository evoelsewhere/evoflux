import type { ModelCatalogEntry } from '@/api/types'

const THINKING_LEVEL_LABEL: Record<string, string> = {
  none: 'None',
  minimal: 'Minimal',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  xhigh: 'X-High',
  max: 'Max',
  ultra: 'Ultra',
}

const THINKING_MARK: Record<string, string> = {
  none: 'None',
  default: 'Def',
  minimal: 'Min',
  low: 'Low',
  medium: 'Med',
  high: 'High',
  xhigh: 'XH',
  max: 'Max',
  ultra: 'Ult',
}

/**
 * Internal sentinel stored in an agent's `.md` frontmatter meaning "no
 * per-agent model override configured — inherit the provider default".
 * The backend returns this literal string verbatim from every endpoint
 * that surfaces a stored model id (this is correct/intentional backend
 * behavior); it must never be rendered to the user as-is. Single source
 * of truth — do not redefine this constant elsewhere.
 */
export const PROVIDER_MODEL_PLACEHOLDER = '__PROVIDER_MODEL__'

/**
 * Normalizes a stored model id for display: treats the
 * `PROVIDER_MODEL_PLACEHOLDER` sentinel the same as "no model configured"
 * so callers can fall back to their own "Default"/"Model"/etc. copy
 * instead of ever rendering the raw internal token.
 */
export function normalizeModelId(id: string | null | undefined): string | null {
  if (!id || id === PROVIDER_MODEL_PLACEHOLDER) return null
  return id
}

export type ModelOption = Pick<
  ModelCatalogEntry,
  'id' | 'provider' | 'model' | 'vision'
> &
  Partial<
    Pick<
      ModelCatalogEntry,
      | 'thinking_levels'
      | 'display_name'
      | 'status'
      | 'context_length'
      | 'cost'
      | 'modes'
      | 'mode_cost_multiplier'
      | 'attachment'
      | 'tool_call'
      | 'free'
    >
  >

export type ThinkingOption = {
  value: string | null
  label: string
  mark: string
}

export function buildThinkingOptions(levels: readonly string[]): ThinkingOption[] {
  return [
    { value: null, label: 'Default', mark: THINKING_MARK.default },
    ...levels.map((level) => ({
      value: level,
      label: THINKING_LEVEL_LABEL[level] ?? level,
      mark: THINKING_MARK[level] ?? level.slice(0, 3),
    })),
  ]
}

export function reconcileThinkingLevel(
  currentLevel: string | null | undefined,
  nextModel: { thinking_levels?: readonly string[] } | undefined,
): string | null {
  if (!currentLevel) return null
  return nextModel?.thinking_levels?.includes(currentLevel) ? currentLevel : null
}

export function shortModelName(id: string): string {
  const colon = id.indexOf(':')
  return colon === -1 ? id : id.slice(colon + 1)
}

export function providerOf(id: string): string {
  const colon = id.indexOf(':')
  return colon === -1 ? '' : id.slice(0, colon)
}

/**
 * Whether a model offers a fast lane.
 *
 * This used to test for a `codex:` prefix. It is now a catalog fact: the
 * backend unions the alternate service tiers the model catalog publishes
 * with the ones EvoFlux's own provider integrations implement, so a
 * fast-capable model lights the toggle up without a frontend change.
 */
export function supportsFastMode(
  model: { modes?: readonly string[] } | null | undefined,
): boolean {
  return model?.modes?.includes('fast') ?? false
}

/**
 * How much the fast lane costs, as `2.5×`, or `''` when unpublished.
 *
 * A Fast toggle that hides a 2.5-5x price is the wrong toggle. Empty means
 * the catalogue quotes no rate for the tier — which is not the same as
 * "same price", so nothing is implied.
 */
export function fastModePriceHint(
  model: { mode_cost_multiplier?: Record<string, number> } | null | undefined,
): string {
  const factor = model?.mode_cost_multiplier?.fast
  if (!factor || factor <= 1) return ''
  return `${Number(factor.toFixed(2))}×`
}

export function thinkingColor(level: string | null): string {
  if (!level || level === 'none') return 'var(--thinking-neutral)'
  if (level === 'minimal' || level === 'low') return 'var(--thinking-low)'
  if (level === 'medium') return 'var(--thinking-medium)'
  if (level === 'high') return 'var(--thinking-high)'
  return 'var(--thinking-max)'
}

/**
 * Compact token count, e.g. `200K`, `1M`.
 *
 * The picker shows a context window beside a price, so the number has to
 * read at a glance rather than exactly — `1048576` tells a reader far less
 * than `1M` does in a third of the width.
 */
export function formatTokenCount(tokens: number | null | undefined): string {
  if (!tokens || tokens <= 0) return ''
  if (tokens >= 1_000_000) {
    const millions = tokens / 1_000_000
    return `${millions >= 10 ? Math.round(millions) : Number(millions.toFixed(1))}M`
  }
  if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}K`
  return String(tokens)
}

/** One USD-per-million rate, trimmed of trailing zeros. */
function formatRate(rate: number): string {
  if (rate === 0) return '0'
  if (rate < 0.01) return rate.toPrecision(1)
  return String(Number(rate.toFixed(rate < 1 ? 2 : 2)))
}

/**
 * Input/output rates as `$3/$15` per million tokens.
 *
 * Returns an empty string when the catalog has no price — a free, local, or
 * newly listed model. Showing `$0/$0` there would assert something the
 * catalog never said.
 */
export function formatModelPrice(
  cost: { input?: number; output?: number } | null | undefined,
): string {
  const input = cost?.input
  const output = cost?.output
  if (input === undefined && output === undefined) return ''
  if (input === 0 && output === 0) return 'free'
  const parts = [input, output]
    .filter((rate): rate is number => rate !== undefined)
    .map((rate) => `$${formatRate(rate)}`)
  return parts.join('/')
}

/** Text a model matches against in the picker's search box. */
export function modelSearchText(model: ModelOption): string {
  return [model.id, model.display_name].filter(Boolean).join(' ')
}
