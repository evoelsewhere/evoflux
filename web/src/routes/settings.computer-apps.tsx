import { useState } from 'react'
import { AppWindow, Save } from 'lucide-react'

import type { ComputerAppSettings } from '@/api/client'
import { AppPicker } from '@/components/ComputerAppViewer/AppPicker'
import { computerAppSupported } from '@/components/ComputerAppViewer/computerAppBridge'
import { MacPermissions } from '@/components/ComputerAppViewer/MacPermissions'
import { computerAppNeedsPermissions } from '@/components/ComputerAppViewer/useComputerAppPermissions'
import { appList, useInstalledApps } from '@/components/ComputerAppViewer/useInstalledApps'
import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SelectControl } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { useI18n } from '@/i18n'
import { useRegisterSettingsDirty } from '@/lib/settings-dirty'
import {
  useComputerAppSettingsQuery,
  useUpdateComputerAppSettingsMutation,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'

/**
 * The typed list keeps the text as typed: rebuilding it from the parsed list
 * on every key ate the separator just typed, so a second name could not be
 * started. It follows the saved list only when that changes from elsewhere.
 */
function TypedAppList({
  value,
  onChange,
  disabled,
  placeholder,
  ariaLabel,
}: {
  value: string[]
  onChange: (next: string[]) => void
  disabled: boolean
  placeholder: string
  ariaLabel: string
}) {
  const [text, setText] = useState(() => value.join(', '))
  const joined = value.join('\u0000')
  const [seen, setSeen] = useState(joined)
  if (joined !== seen && joined !== appList(text).join('\u0000')) {
    setSeen(joined)
    setText(value.join(', '))
  }
  return (
    <Input
      value={text}
      disabled={disabled}
      onChange={(event) => {
        setText(event.target.value)
        const next = appList(event.target.value)
        setSeen(next.join('\u0000'))
        onChange(next)
      }}
      placeholder={placeholder}
      aria-label={ariaLabel}
    />
  )
}

/**
 * The apps on this computer to pick from, with their icons — or, where the
 * desktop cannot list them (a browser, another OS), typed executable names.
 */
function AppListControl({
  value,
  onChange,
  disabled,
  placeholder,
  fallbackPlaceholder,
  ariaLabel,
}: {
  value: string[]
  onChange: (next: string[]) => void
  disabled: boolean
  placeholder: string
  fallbackPlaceholder: string
  ariaLabel: string
}) {
  const apps = useInstalledApps()
  if (!computerAppSupported()) {
    return (
      <TypedAppList
        value={value}
        onChange={onChange}
        disabled={disabled}
        placeholder={fallbackPlaceholder}
        ariaLabel={ariaLabel}
      />
    )
  }
  return (
    <AppPicker
      value={value}
      onChange={onChange}
      apps={apps.data ?? []}
      loading={apps.isLoading}
      disabled={disabled}
      placeholder={placeholder}
      ariaLabel={ariaLabel}
    />
  )
}

export function ComputerAppsSettingsPage() {
  const { t } = useI18n()
  const query = useComputerAppSettingsQuery()
  const update = useUpdateComputerAppSettingsMutation()
  const push = useToastStore((state) => state.push)
  const [editedDraft, setEditedDraft] = useState<ComputerAppSettings | null>(null)
  const draft = editedDraft ?? query.data ?? null
  const dirty = Boolean(
    editedDraft && query.data && JSON.stringify(editedDraft) !== JSON.stringify(query.data),
  )
  useRegisterSettingsDirty(dirty)

  const patch = <K extends keyof ComputerAppSettings>(key: K, value: ComputerAppSettings[K]) =>
    setEditedDraft((current) => {
      const source = current ?? query.data
      return source ? { ...source, [key]: value } : current
    })

  const save = async () => {
    if (!draft) return
    try {
      await update.mutateAsync(draft)
      setEditedDraft(null)
      push({
        tone: 'success',
        title: t('Computer app settings saved'),
        description: t('Agent actions use this policy immediately.'),
      })
    } catch (error) {
      push({
        tone: 'error',
        title: t('Save failed'),
        description: error instanceof Error ? error.message : String(error),
      })
    }
  }

  return (
    <SettingsPage
      icon={AppWindow}
      title={t('Computer App Control')}
      lede={t('Let an agent control one desktop app at a time in the background, while you watch it in a preview card with a virtual cursor.')}
      actions={
        <div className="flex items-center gap-2">
          {dirty && <span className="text-xs text-(--color-text-muted)">{t('Unsaved')}</span>}
          <Button size="sm" onClick={() => void save()} disabled={!dirty || update.isPending}>
            <Save size={12} aria-hidden="true" />
            {update.isPending ? t('Saving…') : t('Save')}
          </Button>
        </div>
      }
    >
      <SettingsGroup
        title={t('Control one app at a time')}
        description={t('The agent attaches to a single window. Clicks and keys go to that app only: your mouse, keyboard and active window stay yours.')}
      >
        {!computerAppSupported() && (
          <SettingsRow
            stacked
            control={
              <SettingsCallout tone="warning">
                {t('Computer App Control works in EvoFlux Desktop on Windows and macOS. This policy is saved but has no effect here.')}
              </SettingsCallout>
            }
          />
        )}
        <SettingsAsyncBoundary
          loading={query.isLoading}
          hasData={Boolean(query.data)}
          error={query.error}
          variant="detail"
          loadingLabel={t('Loading computer app settings')}
          errorTitle={t('Failed to load computer app settings')}
          onRetry={() => void query.refetch()}
        >
          {draft && (
            <>
              <SettingsRow
                label={t('Enable Computer App Control')}
                description={t('Off by default. Nothing can attach to an app until this is on.')}
                control={
                  <Switch
                    checked={draft.enabled}
                    onCheckedChange={(checked) => patch('enabled', checked)}
                    aria-label={t('Enable Computer App Control')}
                  />
                }
              />
              <SettingsRow
                label={t('Keep the app off-screen')}
                description={t('While an agent controls an app, move it out of sight so it keeps running from the taskbar or the Dock without covering your work. It returns to where it was when control ends.')}
                control={
                  <Switch
                    checked={draft.keep_hidden}
                    disabled={!draft.enabled}
                    onCheckedChange={(checked) => patch('keep_hidden', checked)}
                    aria-label={t('Keep the app off-screen')}
                  />
                }
              />
              <SettingsRow
                label={t('Permission')}
                description={t('Ask before each action, even when the chat runs in Auto mode, or let agents act in allowed apps without asking. Only Bypass mode skips the question. Stop in the preview card works either way.')}
                control={
                  <SelectControl
                    value={draft.permission}
                    disabled={!draft.enabled}
                    onValueChange={(value) => patch('permission', value as ComputerAppSettings['permission'])}
                    size="sm"
                    className="min-w-44 bg-(--bg-key) text-xs"
                    ariaLabel={t('Computer App Control permission')}
                    options={[
                      { value: 'ask', label: t('Ask every time') },
                      { value: 'allow', label: t('Allow without asking') },
                    ]}
                  />
                }
              />
              {draft.enabled && draft.permission === 'allow' && (
                <SettingsRow
                  stacked
                  control={
                    <SettingsCallout tone="warning">
                      {t('Agents will click and type in apps without asking. Limit them with the allowed apps below, and keep the preview card in view.')}
                    </SettingsCallout>
                  }
                />
              )}
              <SettingsRow
                stacked
                label={t('Allowed apps')}
                description={t('Only these apps can be controlled. Leave empty to allow any app.')}
                control={
                  <AppListControl
                    value={draft.allowed_apps}
                    onChange={(next) => patch('allowed_apps', next)}
                    disabled={!draft.enabled}
                    placeholder={t('Any app')}
                    fallbackPlaceholder="notepad.exe, excel.exe"
                    ariaLabel={t('Allowed apps')}
                  />
                }
              />
              <SettingsRow
                stacked
                label={t('Blocked apps')}
                description={t('Never controlled, even when also allowed above.')}
                control={
                  <AppListControl
                    value={draft.blocked_apps}
                    onChange={(next) => patch('blocked_apps', next)}
                    disabled={!draft.enabled}
                    placeholder={t('No apps blocked')}
                    fallbackPlaceholder="keepass.exe, mstsc.exe"
                    ariaLabel={t('Blocked apps')}
                  />
                }
              />
              <SettingsRow
                stacked
                control={
                  <SettingsCallout tone="info">
                    {t('System shell and security processes (including macOS System Settings), EvoFlux itself, and apps running as administrator can never be controlled. Stop in the preview card revokes control and interrupts the agent.')}
                  </SettingsCallout>
                }
              />
            </>
          )}
        </SettingsAsyncBoundary>
      </SettingsGroup>
      {computerAppNeedsPermissions() && <MacPermissions />}
    </SettingsPage>
  )
}
