import { useEffect, useState } from 'react'

import {
  enrollConductor,
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
  const [draft, setDraft] = useState<ConductorSettings | null>(null)
  const [status, setStatus] = useState<ConductorStatus | null>(null)
  const [token, setToken] = useState('')
  const [pending, setPending] = useState(false)
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

  const run = async (action: () => Promise<void>) => {
    setPending(true)
    setError(null)
    try {
      await action()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setPending(false)
    }
  }

  if (!draft) return null

  return (
    <>
      <SettingsGroup
        title="Organization control plane"
        description="Enroll this machine with Evo Conductor and reconcile organization-managed resources."
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
        <SettingsRow
          label="Conductor URL"
          description="The authoritative organization control-plane endpoint."
          stacked
          control={
            <Input
              value={draft.url}
              onChange={(event) => setDraft({ ...draft, url: event.target.value })}
              placeholder="https://conductor.example.com"
              className="font-mono text-sm"
            />
          }
        />
        <SettingsRow
          label="Enforcement"
          description="Report only detects drift. Enforce remediates managed resources at safe turn boundaries."
          control={
            <select
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
          control={
            <Input
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
          label="Enrollment token"
          description="Used once to mint a machine credential. The token is never returned or stored."
          stacked
          control={
            <div className="flex gap-2">
              <Input
                type="password"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder="Paste enrollment token"
              />
              <Button
                variant="outline"
                disabled={pending || !token.trim() || !draft.url}
                onClick={() => void run(async () => {
                  const saved = await updateConductorSettings(draft)
                  setDraft(saved)
                  setStatus(await enrollConductor(token))
                  setToken('')
                })}
              >
                Enroll
              </Button>
            </div>
          }
        />
        <div className="flex items-center justify-between px-4 py-3">
          <div className="text-xs text-(--color-text-muted)">
            {status?.enrolled ? `State: ${status.state}` : 'This machine is not enrolled.'}
            {status?.manifest_revision ? ` · Manifest ${status.manifest_revision}` : ''}
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={pending || !status?.enrolled}
              onClick={() => void run(async () => setStatus(await syncConductor()))}
            >
              Sync now
            </Button>
            <Button
              size="sm"
              disabled={pending}
              onClick={() => void run(async () => setDraft(await updateConductorSettings(draft)))}
            >
              Save
            </Button>
          </div>
        </div>
      </SettingsGroup>
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
