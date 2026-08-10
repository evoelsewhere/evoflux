import { useEffect, useId, useState } from 'react'

import {
  connectConductor,
  disconnectConductor,
  getConductorSettings,
  getConductorStatus,
  syncConductor,
  updateConductorSettings,
  type ConductorSettings,
  type ConductorStatus,
} from '@/api/client'
import { SettingsCallout, SettingsGroup, SettingsRow } from '@/components/settings/SettingsLayout'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'

export function ConductorConnectionSettings() {
  const urlId = useId()
  const enforcementId = useId()
  const syncIntervalId = useId()
  const heartbeatIntervalId = useId()
  const tokenId = useId()
  const [draft, setDraft] = useState<ConductorSettings | null>(null)
  const [status, setStatus] = useState<ConductorStatus | null>(null)
  const [token, setToken] = useState('')
  const [pendingAction, setPendingAction] = useState<
    'connect' | 'disconnect' | 'sync' | 'save' | null
  >(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void Promise.all([getConductorSettings(), getConductorStatus()])
      .then(([config, current]) => {
        if (!cancelled) {
          setDraft(config)
          setStatus(current)
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason))
      })
    return () => { cancelled = true }
  }, [])

  const run = async (
    actionName: 'connect' | 'disconnect' | 'sync' | 'save',
    action: () => Promise<void>,
  ) => {
    setPendingAction(actionName)
    setError(null)
    try {
      await action()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setPendingAction(null)
    }
  }

  if (!draft) return null

  const projectLabel = status?.project_display_name || status?.project_name
  const pending = pendingAction !== null
  const tokenValid = token.trim().startsWith('evc_')
  const urlValid = isValidConductorUrl(draft.url)
  const connectionLabel: Record<string, string> = {
    connected: 'Connected',
    in_sync: 'Connected · in sync',
    applied: 'Connected · changes applied',
    drifted: 'Connected · drift detected',
    offline: 'Offline · using last known state',
    authorization_required: 'Authorization required',
    forbidden: 'Token scope is not allowed',
    registration_required: 'Registration required',
    disconnected: 'Disconnected',
    disabled: 'Sync disabled',
    syncing: 'Syncing',
  }

  return (
    <>
      <SettingsGroup
        title="Organization control plane"
        description="Connect to Evo Conductor V1 and reconcile organization-managed resources."
      >
        <SettingsRow
          label="Enable Conductor sync"
          description="Disabled by default. Existing local behavior is unchanged while off."
          control={
            <Switch
              checked={draft.enabled}
              onCheckedChange={(enabled) => setDraft({ ...draft, enabled })}
              aria-label="Enable Conductor sync"
            />
          }
        />
        {!status?.enrolled && (
          <SettingsRow
            label="Conductor URL"
            description="The authoritative organization control-plane endpoint."
            htmlFor={urlId}
            stacked
            control={
              <div className="space-y-1.5">
                <Input
                  type="url"
                  id={urlId}
                  value={draft.url}
                  onChange={(event) => setDraft({ ...draft, url: event.target.value })}
                  placeholder="https://conductor.example.com"
                  className="font-mono text-sm"
                  aria-invalid={draft.url.length > 0 && !urlValid}
                />
                {draft.url.length > 0 && !urlValid && (
                  <p className="text-xs text-(--color-danger)" role="alert">
                    Enter an http:// or https:// URL.
                  </p>
                )}
              </div>
            }
          />
        )}
        <SettingsRow
          label="Enforcement"
          description="Report only detects drift. Enforce remediates managed resources at safe turn boundaries."
          htmlFor={enforcementId}
          control={
            <select
              id={enforcementId}
              value={draft.enforcement_mode}
              onChange={(event) => setDraft({
                ...draft,
                enforcement_mode: event.target.value as 'report' | 'enforce',
              })}
              className="h-9 rounded-md border border-(--color-border) bg-(--bg-input) px-2 text-sm"
            >
              <option value="report">Report only</option>
              <option value="enforce">Enforce</option>
            </select>
          }
        />
        <SettingsRow
          label="Sync interval"
          description="Seconds between manifest checks (minimum 5)."
          htmlFor={syncIntervalId}
          control={
            <Input
              id={syncIntervalId}
              type="number"
              min={5}
              value={draft.sync_interval_seconds}
              onChange={(event) => setDraft({
                ...draft,
                sync_interval_seconds: Number(event.target.value),
              })}
              className="w-28"
            />
          }
        />
        <SettingsRow
          label="Heartbeat interval"
          description="Seconds between installation presence checks (30–300; default 60)."
          htmlFor={heartbeatIntervalId}
          control={
            <Input
              id={heartbeatIntervalId}
              type="number"
              min={30}
              max={300}
              value={draft.heartbeat_interval_seconds}
              onChange={(event) => setDraft({
                ...draft,
                heartbeat_interval_seconds: Number(event.target.value),
              })}
              className="w-28"
            />
          }
        />
        {!status?.enrolled && (
          <SettingsRow
            label="V1 connection token"
            description="A scoped evc_ token. After validation it is stored only in your operating system credential vault."
            htmlFor={tokenId}
            stacked
            control={
              <div className="space-y-1.5">
                <div className="flex gap-2">
                  <Input
                    type="password"
                    id={tokenId}
                    value={token}
                    onChange={(event) => setToken(event.target.value)}
                    placeholder="Paste evc_ connection token"
                    aria-invalid={token.length > 0 && !tokenValid}
                  />
                  <Button
                    variant="outline"
                    disabled={pending || !tokenValid || !urlValid}
                    onClick={() => void run('connect', async () => {
                      const saved = await updateConductorSettings(draft)
                      setDraft(saved)
                      setStatus(await connectConductor(token))
                      setToken('')
                    })}
                  >
                    {pendingAction === 'connect' ? 'Connecting…' : 'Connect'}
                  </Button>
                </div>
                {token.length > 0 && !tokenValid && (
                  <p className="text-xs text-(--color-danger)" role="alert">
                    Connection tokens must start with evc_.
                  </p>
                )}
              </div>
            }
          />
        )}
        <div className="flex items-center justify-between px-4 py-3">
          <div className="text-xs text-(--color-text-muted)" role="status" aria-live="polite">
            {pendingAction === 'disconnect'
              ? 'Disconnecting…'
              : pendingAction === 'sync'
                ? 'Syncing…'
                : status?.enrolled
              ? connectionLabel[status.state] || `Connected · ${status.state}`
              : connectionLabel[status?.state || 'disconnected'] || 'Conductor is not connected.'}
            {status?.manifest_revision ? ` · Manifest ${status.manifest_revision}` : ''}
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={pending || !status?.enrolled}
              onClick={() => void run('sync', async () => setStatus(await syncConductor()))}
            >
              Sync now
            </Button>
            {status?.enrolled && (
              <Button
                variant="outline"
                size="sm"
                disabled={pending}
                onClick={() => void run(
                  'disconnect',
                  async () => setStatus(await disconnectConductor()),
                )}
              >
                Disconnect
              </Button>
            )}
            <Button
              size="sm"
              disabled={pending}
              onClick={() => void run(
                'save',
                async () => setDraft(await updateConductorSettings(draft)),
              )}
            >
              {pendingAction === 'save' ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </div>
      </SettingsGroup>
      {status?.enrolled && projectLabel && (
        <SettingsCallout tone="success">
          <div className="flex items-center gap-3">
            {status.project_logo_url ? (
              <img
                src={status.project_logo_url}
                alt={`${projectLabel} logo`}
                className="size-9 rounded-md border border-(--color-border) object-cover"
              />
            ) : (
              <div
                className="flex size-9 items-center justify-center rounded-md border border-(--color-border) font-semibold"
                aria-hidden="true"
              >
                {projectLabel.slice(0, 1).toUpperCase()}
              </div>
            )}
            <div className="min-w-0">
              <div className="font-medium">{projectLabel}</div>
              <div className="text-xs opacity-80">
                {status.member_display_name || 'Project member'}
                {status.member_primary_role ? ` · ${status.member_primary_role}` : ''}
                {status.collection_level ? ` · Privacy ${status.collection_level}` : ''}
              </div>
            </div>
          </div>
        </SettingsCallout>
      )}
      {status?.maintenance_required && (
        <SettingsCallout tone="warning">
          A managed team or MCP change is waiting for a safe maintenance boundary.
        </SettingsCallout>
      )}
      {(error || status?.error) && (
        <SettingsCallout tone="error">{error || status?.error}</SettingsCallout>
      )}
    </>
  )
}

function isValidConductorUrl(value: string) {
  try {
    const parsed = new URL(value.trim())
    return (
      (parsed.protocol === 'http:' || parsed.protocol === 'https:')
      && Boolean(parsed.hostname)
      && !parsed.username
      && !parsed.password
      && parsed.pathname === '/'
      && !parsed.search
      && !parsed.hash
    )
  } catch {
    return false
  }
}
