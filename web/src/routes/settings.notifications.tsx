import { useState } from 'react'
import { Bell, BellRing } from 'lucide-react'

import {
  areDesktopNotificationSoundsEnabled,
  areDesktopNotificationsEnabled,
  sendDesktopNotification,
  setDesktopNotificationSoundsEnabled,
  setDesktopNotificationsEnabled,
} from '@/lib/desktop-notifications'
import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'

export function NotificationSettingsPage() {
  const [enabled, setEnabled] = useState(() => areDesktopNotificationsEnabled())
  const [soundEnabled, setSoundEnabled] = useState(() => areDesktopNotificationSoundsEnabled())
  const [testing, setTesting] = useState(false)
  const [testMessage, setTestMessage] = useState<string | null>(null)

  const handleEnabledChange = (checked: boolean) => {
    setEnabled(checked)
    setDesktopNotificationsEnabled(checked)
  }

  const handleSoundEnabledChange = (checked: boolean) => {
    setSoundEnabled(checked)
    setDesktopNotificationSoundsEnabled(checked)
  }

  const handleTest = async () => {
    setTesting(true)
    setTestMessage(null)
    try {
      const result = await sendDesktopNotification(
        {
          kind: 'assistant_done',
          title: 'EvoFlux notification test',
          body: 'App notifications are working.',
        },
        { force: true },
      )
      setTestMessage(result.message)
    } finally {
      setTesting(false)
    }
  }

  return (
    <SettingsPage
      icon={Bell}
      title="Notifications"
      lede="Native notifications are delivered when EvoFlux runs as a desktop or mobile app, and are skipped while the window is focused."
    >
      <SettingsGroup title="Delivery">
        <SettingsRow
          label="Enable notifications"
          description="Notify when an assistant finishes responding, a background task completes, or a reminder fires."
          control={
            <Switch
              checked={enabled}
              onCheckedChange={handleEnabledChange}
              aria-label="Enable notifications"
            />
          }
        />
        <SettingsRow
          label="Play sound"
          description="Add a short in-app sound alongside the native notification."
          control={
            <Switch
              checked={soundEnabled}
              onCheckedChange={handleSoundEnabledChange}
              disabled={!enabled}
              aria-label="Play sound"
            />
          }
        />
      </SettingsGroup>

      <SettingsGroup
        title="Check your setup"
        description="Send one notification now to confirm OS permissions and the native integration are working."
      >
        <SettingsRow
          stacked
          control={
            <div className="space-y-2.5">
              <Button size="sm" className="min-h-11 md:min-h-0" onClick={handleTest} disabled={!enabled || testing}>
                <BellRing size={12} aria-hidden="true" />
                {testing ? 'Sending…' : 'Send test notification'}
              </Button>
              {testMessage && (
                <SettingsCallout tone="info">
                  <span role="status">{testMessage}</span>
                </SettingsCallout>
              )}
            </div>
          }
        />
      </SettingsGroup>
    </SettingsPage>
  )
}
