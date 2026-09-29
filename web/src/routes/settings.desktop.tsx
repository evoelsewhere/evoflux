import { MonitorCog } from 'lucide-react'

import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { Switch } from '@/components/ui/switch'
import { usePlatform } from '@/hooks/use-platform'
import {
  desktopSettingsSupported,
  useDesktopSettings,
  useUpdateDesktopSettings,
  type DesktopSettingsPatch,
} from '@/hooks/useDesktopSettings'

export function DesktopSettingsPage() {
  const platform = usePlatform()
  const supported = desktopSettingsSupported()
  const settingsQ = useDesktopSettings()
  const update = useUpdateDesktopSettings()
  const settings = settingsQ.data
  const isMac = platform.os === 'macos'
  const disabled = !settings || update.isPending

  const change = (patch: DesktopSettingsPatch) => update.mutate(patch)

  const trayLabel = isMac ? 'Show in menu bar' : 'Show in system tray'
  const trayCopy = isMac
    ? 'Keep the EvoFlux icon in the menu bar for status and quick actions. Closing a window keeps EvoFlux running in the Dock either way.'
    : 'Keep the EvoFlux icon in the notification area. Closing the window leaves EvoFlux running there, so scheduled tasks and Remote Control carry on. When off, closing the last window quits EvoFlux.'
  const startupCopy = isMac
    ? 'Open EvoFlux when you log in to this Mac. It starts without a window; click its Dock or menu bar icon to open it.'
    : settings?.tray_icon === false
      ? 'Open EvoFlux when you sign in to this computer. With the tray icon off, it opens its window.'
      : 'Open EvoFlux when you sign in to this computer. It starts in the system tray without opening a window.'

  return (
    <SettingsPage
      icon={MonitorCog}
      title="Desktop"
      lede="How the EvoFlux app behaves on this computer: when it starts, where it lives while its window is closed, and whether it keeps the computer awake."
    >
      {!supported && (
        <SettingsCallout tone="info">
          These settings are available in the EvoFlux desktop app.
        </SettingsCallout>
      )}
      {supported && settingsQ.isError && (
        <SettingsCallout tone="error">
          Could not read the desktop settings: {String(settingsQ.error)}
        </SettingsCallout>
      )}
      {update.isError && (
        <SettingsCallout tone="error">
          Could not change the setting: {String(update.error)}
        </SettingsCallout>
      )}

      <SettingsGroup title="Startup">
        <SettingsRow
          label="Run on startup"
          description={startupCopy}
          control={
            <Switch
              checked={settings?.run_on_startup ?? false}
              onCheckedChange={(checked) => change({ run_on_startup: checked })}
              disabled={disabled}
              aria-label="Run on startup"
            />
          }
        />
      </SettingsGroup>

      <SettingsGroup title="Background">
        <SettingsRow
          label={trayLabel}
          description={trayCopy}
          control={
            <Switch
              checked={settings?.tray_icon ?? true}
              onCheckedChange={(checked) => change({ tray_icon: checked })}
              disabled={disabled}
              aria-label={trayLabel}
            />
          }
        />
        <SettingsRow
          label="Keep computer awake"
          description="Stop this computer from going to sleep while EvoFlux is running, so scheduled tasks, long agent runs and Remote Control keep going while you are away. The display can still turn off."
          control={
            <Switch
              checked={settings?.keep_awake ?? false}
              onCheckedChange={(checked) => change({ keep_awake: checked })}
              disabled={disabled}
              aria-label="Keep computer awake"
            />
          }
        />
      </SettingsGroup>
    </SettingsPage>
  )
}
