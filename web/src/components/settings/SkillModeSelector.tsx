import { SettingsRow } from '@/components/settings/SettingsLayout'
import { SegmentedControl } from '@/components/ui/segmented-control'
import type { SkillAvailability } from '@/lib/skill-modes'

export function SkillModeSelector({
  value,
  onChange,
  disabled = false,
  layoutId,
}: {
  value: SkillAvailability
  onChange: (value: SkillAvailability) => void
  disabled?: boolean
  layoutId: string
}) {
  return (
    <SettingsRow
      label="Available in"
      description="Controls where the skill appears and can be loaded at runtime."
      className="flex-col sm:flex-row"
      control={
        <SegmentedControl
          options={[
            { value: 'work', label: 'Work', disabled },
            { value: 'coding', label: 'Coding', disabled },
            { value: 'both', label: 'Both', disabled },
          ]}
          value={value}
          onChange={onChange}
          layoutId={layoutId}
          ariaLabel="Skill availability"
        />
      }
    />
  )
}
