import { useState } from 'react'
import { AlertCircle, Check, ExternalLink, RefreshCw } from 'lucide-react'

import { SettingsCallout, SettingsGroup, SettingsRow } from '@/components/settings/SettingsLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n'
import { useToastStore } from '@/stores/useToastStore'

import {
  restartForPermissions,
  useComputerAppPermissions,
  useRequestComputerAppPermission,
  type ComputerAppPermission,
} from './useComputerAppPermissions'

/**
 * Settings → Computer App Control on macOS: whether EvoFlux has the two
 * permissions the feature needs, with one click to the right System
 * Settings pane for each. macOS keeps the switches there; nothing here can
 * turn them on by itself.
 */
export function MacPermissions() {
  const { t } = useI18n()
  const query = useComputerAppPermissions()
  const request = useRequestComputerAppPermission()
  const push = useToastStore((state) => state.push)
  const [requested, setRequested] = useState<ReadonlySet<ComputerAppPermission>>(new Set())
  const [restarting, setRestarting] = useState(false)
  const permissions = query.data

  const ask = (kind: ComputerAppPermission) => {
    setRequested((previous) => new Set(previous).add(kind))
    request.mutate(kind, {
      onError: (error) =>
        push({
          tone: 'error',
          title: t('Could not open System Settings'),
          description: error instanceof Error ? error.message : String(error),
        }),
    })
  }

  const restart = () => {
    setRestarting(true)
    void restartForPermissions().catch((error: unknown) => {
      setRestarting(false)
      push({
        tone: 'error',
        title: t('Restart failed'),
        description: error instanceof Error ? error.message : String(error),
      })
    })
  }

  const rows: {
    kind: ComputerAppPermission
    label: string
    description: string
  }[] = [
    {
      kind: 'accessibility',
      label: t('Accessibility'),
      description: t('Read and operate the controls of the app an agent attaches to.'),
    },
    {
      kind: 'screen_recording',
      label: t('Screen & System Audio Recording'),
      description: t('Capture the attached app for screenshots and the preview card. macOS applies it after EvoFlux restarts.'),
    },
  ]
  const missing = rows.filter((row) => permissions && !permissions[row.kind])
  const screenPending = Boolean(
    permissions && !permissions.screen_recording && requested.has('screen_recording'),
  )

  return (
    <SettingsGroup
      title={t('macOS permissions')}
      description={t('Computer App Control needs both. Allow opens the right pane in System Settings; turn EvoFlux on there and this page updates by itself.')}
    >
      {rows.map((row) => {
        const granted = permissions?.[row.kind]
        return (
          <SettingsRow
            key={row.kind}
            label={row.label}
            description={row.description}
            control={
              <div className="flex items-center gap-2">
                {permissions && (
                  <Badge variant={granted ? 'secondary' : 'destructive'}>
                    {granted ? <Check aria-hidden="true" /> : <AlertCircle aria-hidden="true" />}
                    {granted ? t('Allowed') : t('Not allowed')}
                  </Badge>
                )}
                {permissions && !granted && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => ask(row.kind)}
                    disabled={request.isPending}
                    aria-label={t('Allow {0} in System Settings', [row.label])}
                  >
                    <ExternalLink size={12} aria-hidden="true" />
                    {t('Allow')}
                  </Button>
                )}
              </div>
            }
          />
        )
      })}
      {screenPending && (
        <SettingsRow
          stacked
          control={
            <SettingsCallout tone="info">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>{t('Turned on Screen & System Audio Recording? Restart EvoFlux so macOS applies it.')}</span>
                <Button size="sm" onClick={restart} disabled={restarting}>
                  <RefreshCw size={12} aria-hidden="true" />
                  {restarting ? t('Restarting…') : t('Restart EvoFlux')}
                </Button>
              </div>
            </SettingsCallout>
          }
        />
      )}
      {permissions && missing.length === 0 && (
        <SettingsRow
          stacked
          control={
            <SettingsCallout tone="success">
              {t('EvoFlux has everything it needs to control apps on this Mac.')}
            </SettingsCallout>
          }
        />
      )}
    </SettingsGroup>
  )
}
