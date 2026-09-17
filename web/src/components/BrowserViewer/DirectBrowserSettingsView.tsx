import { ArrowLeft, Database, Globe2, Printer, ShieldAlert, ZoomIn } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { SelectControl } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import type { BrowserPreferences } from './browserPreferences'

interface DirectBrowserSettingsViewProps {
  active: boolean
  supported: boolean
  preferences: BrowserPreferences
  onBack: () => void
  onToggleBrowser: (enabled: boolean) => void
  onPreferencesChange: (value: BrowserPreferences) => void
  onZoomChange: (value: number) => void
  onPrint: () => void
  onClearData: () => void
  onOpenDevTools: () => void
}

export function DirectBrowserSettingsView({
  active,
  supported,
  preferences,
  onBack,
  onToggleBrowser,
  onPreferencesChange,
  onZoomChange,
  onPrint,
  onClearData,
  onOpenDevTools,
}: DirectBrowserSettingsViewProps) {
  return (
    <div className="h-full overflow-y-auto bg-(--bg-page)">
      <div className="mx-auto w-full max-w-3xl px-5 py-5 sm:px-8 sm:py-7">
        <div className="mb-7 flex items-start gap-3">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={onBack}
            aria-label="Back to browser"
            title="Back to browser"
          >
            <ArrowLeft />
          </Button>
          <div>
            <h2 className="text-xl font-semibold text-(--color-text)">Browser</h2>
            <p className="mt-1 text-sm text-(--color-text-muted)">
              Native browser views embedded directly in the EvoFlux workspace.
            </p>
          </div>
        </div>

        <section className="mb-8 overflow-hidden rounded-lg border border-(--color-border)">
          <SettingsRow
            Icon={Globe2}
            title="Browser"
            description="Keep a native browser tab open in this panel"
            action={(
              <Switch
                checked={active}
                disabled={!supported}
                onCheckedChange={onToggleBrowser}
                aria-label="Enable built-in browser"
              />
            )}
          />
        </section>

        <SettingsSection title="General">
          <SettingsRow
            Icon={ZoomIn}
            title="Default zoom"
            description="Applied directly by the operating system WebView"
            action={(
              <div className="flex items-center gap-1 rounded-md border border-(--color-border) bg-(--bg-key) p-0.5">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  disabled={!active || preferences.defaultZoom <= 50}
                  onClick={() => onZoomChange(preferences.defaultZoom - 10)}
                  aria-label="Zoom out"
                >
                  −
                </Button>
                <span className="w-12 text-center text-xs tabular-nums text-(--color-text)">
                  {preferences.defaultZoom}%
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  disabled={!active || preferences.defaultZoom >= 200}
                  onClick={() => onZoomChange(preferences.defaultZoom + 10)}
                  aria-label="Zoom in"
                >
                  +
                </Button>
              </div>
            )}
          />
          <SettingsRow
            Icon={Printer}
            title="Print"
            description="Open the native print dialog for the active tab"
            action={(
              <Button type="button" variant="secondary" size="sm" disabled={!active} onClick={onPrint}>
                Print
              </Button>
            )}
          />
          <SettingsRow
            Icon={Database}
            title="Browser profile"
            description="Applies to newly created tabs"
            action={(
              <SelectControl
                value={preferences.profileMode}
                disabled={!active}
                onValueChange={(value) => onPreferencesChange({
                  ...preferences,
                  profileMode: value as BrowserPreferences['profileMode'],
                })}
                size="sm"
                className="min-w-32 bg-(--bg-key) text-xs"
                ariaLabel="Browser profile mode"
                options={[
                  { value: 'shared', label: 'Shared' },
                  { value: 'session', label: 'Per session' },
                  { value: 'incognito', label: 'Incognito' },
                ]}
              />
            )}
          />
          <SettingsRow
            Icon={Database}
            title="Browsing data"
            description="Clear cookies, cache, history, and local site storage"
            action={(
              <Button type="button" variant="secondary" size="sm" disabled={!active} onClick={onClearData}>
                Clear
              </Button>
            )}
          />
        </SettingsSection>

        <SettingsSection title="Developer mode">
          <SettingsRow
            Icon={ShieldAlert}
            iconClassName="text-(--color-warning)"
            title="Enable WebView inspector"
            description="Allow native developer tools for newly created tabs"
            action={(
              <Switch
                checked={preferences.developerTools}
                onCheckedChange={(checked) => onPreferencesChange({
                  ...preferences,
                  developerTools: checked,
                })}
                aria-label="Enable WebView inspector"
              />
            )}
          />
          {preferences.developerTools && (
            <SettingsRow
              Icon={ShieldAlert}
              title="Developer tools"
              description="Inspect the active native WebView"
              action={(
                <Button type="button" variant="secondary" size="sm" disabled={!active} onClick={onOpenDevTools}>
                  Open
                </Button>
              )}
            />
          )}
        </SettingsSection>
      </div>
    </div>
  )
}

function SettingsSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h3 className="mb-2 text-sm font-medium text-(--color-text)">{title}</h3>
      <div className="overflow-hidden rounded-lg border border-(--color-border)">{children}</div>
    </section>
  )
}

function SettingsRow({
  Icon,
  title,
  description,
  action,
  iconClassName,
}: {
  Icon: React.ComponentType<{ size?: number; className?: string; 'aria-hidden'?: boolean }>
  title: string
  description: string
  action: React.ReactNode
  iconClassName?: string
}) {
  return (
    <div className="flex min-h-16 items-center gap-3 border-b border-(--color-border) px-4 py-3 last:border-b-0">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-(--bg-key)">
        <Icon size={16} className={iconClassName ?? 'text-(--color-text-muted)'} aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-(--color-text)">{title}</span>
        <span className="mt-0.5 block text-xs leading-4 text-(--color-text-muted)">{description}</span>
      </span>
      {action}
    </div>
  )
}
