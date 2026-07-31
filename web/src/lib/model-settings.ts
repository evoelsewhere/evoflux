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

export type ModelOption = Pick<
  ModelCatalogEntry,
  'id' | 'provider' | 'model' | 'vision'
> &
  Partial<Pick<ModelCatalogEntry, 'thinking_levels'>>

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

export function supportsFastMode(modelId: string): boolean {
  return modelId.startsWith('codex:')
}

export function thinkingColor(level: string | null): string {
  if (!level || level === 'none') return 'var(--thinking-neutral)'
  if (level === 'minimal' || level === 'low') return 'var(--thinking-low)'
  if (level === 'medium') return 'var(--thinking-medium)'
  if (level === 'high') return 'var(--thinking-high)'
  return 'var(--thinking-max)'
}
