import { useEffect, useState } from 'react'
import { Globe2, Save } from 'lucide-react'

import type { WebBridgeSettings } from '@/api/client'
import {
  areWebBridgeDefaultsEnabled,
  loadBrowserPreferences,
  saveBrowserPreferences,
  setWebBridgeDefaultsEnabled,
  subscribeBrowserPreferences,
  type BrowserPreferences,
} from '@/components/BrowserViewer/browserPreferences'
import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { useI18n } from '@/i18n'
import { useRegisterSettingsDirty } from '@/lib/settings-dirty'
import {
  useUpdateWebBridgeSettingsMutation,
  useWebBridgeSettingsQuery,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'

export function BrowserSettingsPage() {
  const { t } = useI18n()
  const query = useWebBridgeSettingsQuery()
  const update = useUpdateWebBridgeSettingsMutation()
  const push = useToastStore((state) => state.push)

  const [preferences, setPreferences] = useState<BrowserPreferences>(loadBrowserPreferences)
  const [webBridgeDefault, setWebBridgeDefault] = useState(areWebBridgeDefaultsEnabled)
  const [editedDraft, setEditedDraft] = useState<WebBridgeSettings | null>(null)
  const draft = editedDraft ?? query.data ?? null
  const dirty = Boolean(
    editedDraft
    && query.data
    && JSON.stringify(editedDraft) !== JSON.stringify(query.data),
  )
  useRegisterSettingsDirty(dirty)

  useEffect(() => subscribeBrowserPreferences((value) => {
    setPreferences(value)
    setWebBridgeDefault(areWebBridgeDefaultsEnabled())
  }), [])

  const patchBuiltIn = <K extends keyof BrowserPreferences>(
    key: K,
    value: BrowserPreferences[K],
  ) => {
    setPreferences((current) => {
      const next = { ...current, [key]: value }
      saveBrowserPreferences(next)
      return next
    })
  }

  const patchWebBridge = <K extends keyof WebBridgeSettings>(
    key: K,
    value: WebBridgeSettings[K],
  ) => setEditedDraft((current) => {
    const source = current ?? query.data
    return source ? { ...source, [key]: value } : current
  })

  const handleWebBridgeDefaultChange = (checked: boolean) => {
    setWebBridgeDefault(checked)
    setWebBridgeDefaultsEnabled(checked)
  }

  const save = async () => {
    if (!draft) return
    try {
      await update.mutateAsync(draft)
      setEditedDraft(null)
      push({
        tone: 'success',
        title: t('WebBridge settings saved'),
        description: t('New chats and agent actions use this policy immediately.'),
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
      icon={Globe2}
      title={t('Browser')}
      lede={t('Choose how the agent browses the web: the built-in workspace browser, or your real Chrome/Edge through WebBridge.')}
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
        title={t('Built-in browser')}
        description={t('Native browser views embedded directly in the EvoFlux workspace.')}
      >
        <SettingsRow
          label={t('Enable built-in browser')}
          description={t('Show the Browser workbench tool and let the agent drive the in-app WebView.')}
          control={
            <Switch
              checked={preferences.enabled}
              onCheckedChange={(checked) => patchBuiltIn('enabled', checked)}
              aria-label={t('Enable built-in browser')}
            />
          }
        />
        <SettingsRow
          label={t('Default zoom')}
          description={t('Applied directly by the operating system WebView')}
          control={
            <div className="flex items-center gap-1 rounded-md border border-(--color-border) bg-(--bg-key) p-0.5">
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                disabled={!preferences.enabled || preferences.defaultZoom <= 50}
                onClick={() => patchBuiltIn('defaultZoom', preferences.defaultZoom - 10)}
                aria-label={t('Zoom out')}
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
                disabled={!preferences.enabled || preferences.defaultZoom >= 200}
                onClick={() => patchBuiltIn('defaultZoom', preferences.defaultZoom + 10)}
                aria-label={t('Zoom in')}
              >
                +
              </Button>
            </div>
          }
        />
        <SettingsRow
          label={t('Enable WebView inspector')}
          description={t('Allow native developer tools for newly created tabs')}
          control={
            <Switch
              checked={preferences.developerTools}
              disabled={!preferences.enabled}
              onCheckedChange={(checked) => patchBuiltIn('developerTools', checked)}
              aria-label={t('Enable WebView inspector')}
            />
          }
        />
      </SettingsGroup>

      <SettingsGroup
        title={t('WebBridge')}
        description={t('Lets the agent drive your real Chrome/Edge browser through the WebBridge extension.')}
      >
        <SettingsAsyncBoundary
          loading={query.isLoading}
          hasData={Boolean(query.data)}
          error={query.error}
          variant="detail"
          loadingLabel={t('Loading WebBridge settings')}
          errorTitle={t('Failed to load WebBridge settings')}
          onRetry={() => void query.refetch()}
        >
          {draft && (
            <>
              <SettingsRow
                label={t('Enable WebBridge')}
                description={t('Master switch for the WebBridge tool. When off, agents cannot drive your real browser.')}
                control={
                  <Switch
                    checked={draft.enabled}
                    onCheckedChange={(checked) => patchWebBridge('enabled', checked)}
                    aria-label={t('Enable WebBridge')}
                  />
                }
              />
              <SettingsRow
                label={t('Allow JavaScript evaluate')}
                description={t('Permit arbitrary JavaScript in the real browser. Safer selector and snapshot actions stay available either way.')}
                control={
                  <Switch
                    checked={draft.allow_evaluate}
                    disabled={!draft.enabled}
                    onCheckedChange={(checked) => patchWebBridge('allow_evaluate', checked)}
                    aria-label={t('Allow JavaScript evaluate')}
                  />
                }
              />
              <SettingsRow
                label={t('Enable for new chats')}
                description={t('Turn WebBridge on by default when you start a new chat. You can still toggle it per chat from the workbench bar.')}
                control={
                  <Switch
                    checked={webBridgeDefault}
                    disabled={!draft.enabled}
                    onCheckedChange={handleWebBridgeDefaultChange}
                    aria-label={t('Enable for new chats')}
                  />
                }
              />
              {!draft.enabled && (
                <SettingsRow
                  stacked
                  control={
                    <SettingsCallout tone="warning">
                      {t('WebBridge is disabled by policy. Per-chat controls in the workbench bar stay inactive until you turn it back on.')}
                    </SettingsCallout>
                  }
                />
              )}
            </>
          )}
        </SettingsAsyncBoundary>
      </SettingsGroup>
    </SettingsPage>
  )
}
