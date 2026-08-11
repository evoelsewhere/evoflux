import { SettingsRow } from '@/components/settings/SettingsLayout'
import type { SkillMode } from '@/api/types'
import { ALL_SKILL_MODES, normalizeSkillModes } from '@/lib/skill-modes'
import { cn } from '@/lib/utils'

const MODE_LABELS: Record<SkillMode, string> = {
  work: 'Work',
  coding: 'Coding',
  aim: 'AIM',
}

export function SkillModeSelector({
  value,
  onChange,
  disabled = false,
}: {
  value: readonly SkillMode[]
  onChange: (value: SkillMode[]) => void
  disabled?: boolean
}) {
  const selectedModes = normalizeSkillModes(value)
  const allSelected = selectedModes.length === ALL_SKILL_MODES.length

  const toggleMode = (mode: SkillMode) => {
    if (selectedModes.includes(mode)) {
      if (selectedModes.length === 1) return
      onChange(selectedModes.filter((selected) => selected !== mode))
      return
    }
    onChange(normalizeSkillModes([...selectedModes, mode]))
  }

  return (
    <SettingsRow
      label="Available in"
      description="Select one or more modes where the skill appears and can be loaded at runtime."
      className="flex-col sm:flex-row"
      control={
        <div
          role="group"
          aria-label="Skill availability"
          className="flex max-w-full flex-wrap gap-1 rounded-md border border-(--color-border) bg-(--bg-key)/60 p-1"
        >
          {ALL_SKILL_MODES.map((mode) => {
            const selected = selectedModes.includes(mode)
            const lastSelected = selected && selectedModes.length === 1
            return (
              <button
                key={mode}
                type="button"
                aria-pressed={selected}
                disabled={disabled || lastSelected}
                title={lastSelected ? 'At least one mode is required' : undefined}
                onClick={() => toggleMode(mode)}
                className={cn(
                  'rounded-[7px] px-2.5 py-1 text-xs outline-none transition-[background-color,color,box-shadow,opacity] focus-visible:ring-2 focus-visible:ring-(--focus-ring)/40',
                  selected
                    ? 'bg-(--bg-card) text-(--color-text) shadow-sm'
                    : 'text-(--color-text-muted) hover:text-(--color-text)',
                  (disabled || lastSelected) && 'cursor-not-allowed opacity-45',
                )}
              >
                {MODE_LABELS[mode]}
              </button>
            )
          })}
          <span className="mx-0.5 w-px self-stretch bg-(--color-border)" aria-hidden="true" />
          <button
            type="button"
            aria-pressed={allSelected}
            disabled={disabled}
            onClick={() => onChange([...ALL_SKILL_MODES])}
            className={cn(
              'rounded-[7px] px-2.5 py-1 text-xs outline-none transition-[background-color,color,box-shadow,opacity] focus-visible:ring-2 focus-visible:ring-(--focus-ring)/40',
              allSelected
                ? 'bg-(--bg-card) text-(--color-text) shadow-sm'
                : 'text-(--color-text-muted) hover:text-(--color-text)',
              disabled && 'cursor-not-allowed opacity-45',
            )}
          >
            All modes
          </button>
        </div>
      }
    />
  )
}
