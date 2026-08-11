import { useEffect, useId, useState } from 'react'

import {
  approveConductorResource,
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
import {
  CONDUCTOR_ACTION,
  CONDUCTOR_ENFORCEMENT,
  CONDUCTOR_RESOURCE_KIND,
  CONDUCTOR_RESOURCE_STATE,
  type ConductorAction,
} from '@/lib/conductor-constants'

export function ConductorConnectionSettings() {
  const urlId = useId()
  const enforcementId = useId()
  const syncIntervalId = useId()
  const heartbeatIntervalId = useId()
  const tokenId = useId()
  const [draft, setDraft] = useState<ConductorSettings | null>(null)
  const [status, setStatus] = useState<ConductorStatus | null>(null)
  const [token, setToken] = useState('')
  const [pendingAction, setPendingAction] = useState<ConductorAction | null>(null)
  const [pendingResourceId, setPendingResourceId] = useState<string | null>(null)
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
    actionName: ConductorAction,
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
                enforcement_mode: event.target.value as ConductorSettings['enforcement_mode'],
              })}
              className="h-9 rounded-md border border-(--color-border) bg-(--bg-input) px-2 text-sm"
            >
              <option value={CONDUCTOR_ENFORCEMENT.REPORT}>Report only</option>
              <option value={CONDUCTOR_ENFORCEMENT.ENFORCE}>Enforce</option>
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
                    onClick={() => void run(CONDUCTOR_ACTION.CONNECT, async () => {
                      const saved = await updateConductorSettings(draft)
                      setDraft(saved)
                      setStatus(await connectConductor(token))
                      setToken('')
                    })}
                  >
                    {pendingAction === CONDUCTOR_ACTION.CONNECT ? 'Connecting…' : 'Connect'}
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
            {pendingAction === CONDUCTOR_ACTION.DISCONNECT
              ? 'Disconnecting…'
              : pendingAction === CONDUCTOR_ACTION.SYNC
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
              onClick={() => void run(
                CONDUCTOR_ACTION.SYNC,
                async () => setStatus(await syncConductor()),
              )}
            >
              Sync now
            </Button>
            {status?.enrolled && (
              <Button
                variant="outline"
                size="sm"
                disabled={pending}
                onClick={() => void run(
                  CONDUCTOR_ACTION.DISCONNECT,
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
                CONDUCTOR_ACTION.SAVE,
                async () => setDraft(await updateConductorSettings(draft)),
              )}
            >
              {pendingAction === CONDUCTOR_ACTION.SAVE ? 'Saving…' : 'Save'}
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
      {status?.enrolled && (
        <SettingsGroup
          title="Managed resources"
          description="Project-scoped desired state, local trust and the last observed result."
        >
          {status.resources.length === 0 ? (
            <div className="px-4 py-6 text-sm text-(--color-text-muted)" data-testid="conductor-managed-resources-empty">
              No governed Agents, Skills or Plugins are currently assigned to this member.
            </div>
          ) : (
          <div className="divide-y divide-(--color-border)">
            {status.resources.map((resource) => {
              const resourceId = resource.resource_id
              const state = resource.observed_state || resource.state
              const trustPending = state === CONDUCTOR_RESOURCE_STATE.TRUST_PENDING
                && resource.kind === CONDUCTOR_RESOURCE_KIND.PLUGIN
              return (
                <div
                  key={resourceId || `${resource.kind}/${resource.slug}`}
                  className="flex flex-col gap-3 px-4 py-3 md:flex-row md:items-center md:justify-between"
                  data-testid="conductor-managed-resource"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{resource.slug}</span>
                      <span className="rounded border border-(--color-border) px-1.5 py-0.5 text-[11px] uppercase text-(--color-text-muted)">
                        {resource.kind}
                      </span>
                      {resource.release_channel && (
                        <span className="rounded bg-(--bg-hover) px-1.5 py-0.5 text-[11px] capitalize">
                          {resource.release_channel}
                        </span>
                      )}
                      {resource.version && (
                        <span className="font-mono text-xs text-(--color-text-muted)">
                          v{resource.version}
                        </span>
                      )}
                    </div>
                    <div className="mt-1 text-xs text-(--color-text-muted)">
                      {resource.message || state.replaceAll('_', ' ')}
                    </div>
                    {resource.project_id && (
                      <div className="mt-1 font-mono text-[10px] text-(--color-text-subtle)">
                        project {resource.project_id.slice(0, 8)} · resource {resourceId?.slice(0, 8)}
                      </div>
                    )}
                    {trustPending && resource.trust_review && (
                      <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-(--color-text-muted)">
                        <span className="rounded bg-(--bg-hover) px-1.5 py-1">
                          {resource.trust_review.executable_commands?.length || 0} commands
                        </span>
                        <span className="rounded bg-(--bg-hover) px-1.5 py-1">
                          {resource.trust_review.remote_hosts?.length || 0} remote hosts
                        </span>
                        <span className="rounded bg-(--bg-hover) px-1.5 py-1">
                          {resource.trust_review.environment_fields?.length || 0} environment fields
                        </span>
                        <span className="rounded bg-(--bg-hover) px-1.5 py-1">
                          {resource.trust_review.capabilities?.length || 0} capabilities
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <span
                      className={`size-2 rounded-full ${
                        state === CONDUCTOR_RESOURCE_STATE.IN_SYNC
                          || state === CONDUCTOR_RESOURCE_STATE.APPLIED
                          ? 'bg-emerald-400'
                          : state === CONDUCTOR_RESOURCE_STATE.ERROR
                            || state === CONDUCTOR_RESOURCE_STATE.INCOMPATIBLE
                            || state === CONDUCTOR_RESOURCE_STATE.OWNERSHIP_CONFLICT
                            ? 'bg-red-400'
                            : 'bg-amber-400'
                      }`}
                      aria-hidden="true"
                    />
                    <span className="text-xs capitalize text-(--color-text-muted)">
                      {state.replaceAll('_', ' ')}
                    </span>
                    {trustPending && resourceId && (
                      <Button
                        size="sm"
                        disabled={pending || pendingResourceId === resourceId}
                        onClick={() => {
                          if (!window.confirm(
                            'Enable this Conductor-managed Plugin after reviewing the disclosed commands, hosts, environment fields and capabilities?',
                          )) return
                          setPendingResourceId(resourceId)
                          void run(CONDUCTOR_ACTION.APPROVE, async () => {
                            await approveConductorResource(resourceId)
                            setStatus(await getConductorStatus())
                            setPendingResourceId(null)
                          })
                        }}
                      >
                        {pendingResourceId === resourceId ? 'Approving…' : 'Approve local trust'}
                      </Button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
          )}
        </SettingsGroup>
      )}
      {status?.maintenance_required && (
        <SettingsCallout tone="warning">
          A managed Agent, Skill or Plugin change is waiting for a safe maintenance boundary.
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
