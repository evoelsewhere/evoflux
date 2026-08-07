import { SettingsRow } from '@/components/settings/SettingsLayout'
import { Switch } from '@/components/ui/switch'

export function SkillRuntimeControls({
  allowImplicitInvocation,
  userInvocable,
  onAllowImplicitInvocationChange,
  onUserInvocableChange,
  disabled = false,
}: {
  allowImplicitInvocation: boolean
  userInvocable: boolean
  onAllowImplicitInvocationChange: (value: boolean) => void
  onUserInvocableChange: (value: boolean) => void
  disabled?: boolean
}) {
  return (
    <>
      <SettingsRow
        label={<span id="skill-agent-discovery-label">Auto-discovery</span>}
        className="flex-col sm:flex-row"
        description={
          <span id="skill-agent-discovery-description">
            Auto-discoverable adds only the skill name and description to the bounded agent
            catalog. Instructions load after the agent selects it. Hidden from catalog removes it
            from automatic discovery without changing manual invocation.
          </span>
        }
        control={
          <RuntimeToggle
            labelId="skill-agent-discovery-label"
            descriptionId="skill-agent-discovery-description"
            checked={allowImplicitInvocation}
            checkedLabel="Auto-discoverable"
            uncheckedLabel="Hidden from catalog"
            onCheckedChange={onAllowImplicitInvocationChange}
            disabled={disabled}
          />
        }
      />
      <SettingsRow
        label={<span id="skill-manual-invocation-label">Manual invocation</span>}
        className="flex-col sm:flex-row"
        description={
          <span id="skill-manual-invocation-description">
            Allow users to activate this skill with <span className="font-mono">/skill:name</span>{' '}
            or <span className="font-mono">$skill-name</span>. Disabling it also hides the skill
            from the slash menu; configured agents may still load it.
          </span>
        }
        control={
          <RuntimeToggle
            labelId="skill-manual-invocation-label"
            descriptionId="skill-manual-invocation-description"
            checked={userInvocable}
            checkedLabel="Available"
            uncheckedLabel="Disabled"
            onCheckedChange={onUserInvocableChange}
            disabled={disabled}
          />
        }
      />
    </>
  )
}

function RuntimeToggle({
  labelId,
  descriptionId,
  checked,
  checkedLabel,
  uncheckedLabel,
  onCheckedChange,
  disabled,
}: {
  labelId: string
  descriptionId: string
  checked: boolean
  checkedLabel: string
  uncheckedLabel: string
  onCheckedChange: (value: boolean) => void
  disabled: boolean
}) {
  return (
    <div className="flex min-w-36 items-center justify-end gap-2.5">
      <span className="text-xs font-medium text-(--color-text)" aria-hidden="true">
        {checked ? checkedLabel : uncheckedLabel}
      </span>
      <Switch
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        aria-labelledby={labelId}
        aria-describedby={descriptionId}
      />
    </div>
  )
}
