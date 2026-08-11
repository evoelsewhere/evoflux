import { useState } from 'react'
import { AlertTriangle, Download, Info, Loader2 } from 'lucide-react'

import {
  pullConductorResource,
  type ConductorManagedResource,
} from '@/api/client'
import type {
  ManagedResourceProvider,
  ManagedResourceVersionNotice,
} from '@/api/types'
import { SettingsCallout } from '@/components/settings/SettingsLayout'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  CONDUCTOR_RESOURCE_STATE,
  CONDUCTOR_VERSION_GAP_LABEL,
} from '@/lib/conductor-constants'
import { cn } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'

export function ManagedResourceUpdateBanner({
  provider,
  resourceName,
  className,
  onPulled,
}: {
  provider: ManagedResourceProvider
  resourceName: string
  className?: string
  onPulled?: (resource: ConductorManagedResource) => void | Promise<void>
}) {
  const push = useToastStore((state) => state.push)
  const [open, setOpen] = useState(false)
  const [pulling, setPulling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const updateAvailable = Boolean(
    provider.update_available
      ?? (
        provider.applied_version_id
        && provider.version_id
        && provider.applied_version_id !== provider.version_id
      ),
  )
  if (
    !updateAvailable
    || provider.observed_state === CONDUCTOR_RESOURCE_STATE.TRUST_PENDING
  ) return null

  const required = Boolean(provider.update_required)
  const gapLabel = provider.version_gap
    ? CONDUCTOR_VERSION_GAP_LABEL[provider.version_gap]
    : CONDUCTOR_VERSION_GAP_LABEL.unknown
  const installed = provider.applied_version ? `v${provider.applied_version}` : 'Not installed'
  const available = provider.version ? `v${provider.version}` : 'Latest version'
  const changes = changesAfterInstalled(provider)

  const pull = async () => {
    setPulling(true)
    setError(null)
    try {
      const resource = await pullConductorResource(provider.resource_id)
      if (resource.observed_state === CONDUCTOR_RESOURCE_STATE.INCOMPATIBLE) {
        setError(resource.message || 'This update requires a newer EvoFlux version.')
        return
      }
      await onPulled?.(resource)
      setOpen(false)
      push({
        tone: 'success',
        title: resource.observed_state === CONDUCTOR_RESOURCE_STATE.TRUST_PENDING
          ? `${resourceName} downloaded for trust review`
          : `${resourceName} updated to ${available}`,
        description: resource.observed_state === CONDUCTOR_RESOURCE_STATE.TRUST_PENDING
          ? 'Review the Plugin trust boundary before enabling the new version.'
          : 'The managed version is active locally.',
      })
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason)
      setError(message)
      push({ tone: 'error', title: `Could not update ${resourceName}`, description: message })
    } finally {
      setPulling(false)
    }
  }

  return (
    <>
      <SettingsCallout
        tone={required ? 'error' : 'warning'}
        icon={required ? AlertTriangle : Download}
        className={cn('items-center', className)}
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="font-medium text-(--color-text)">
              {required ? 'Update required' : 'Update available'} · {installed} → {available}
            </p>
            <p className="mt-0.5 text-(--color-text-muted)">
              {required
                ? provider.current_version_deprecation_reason
                  ? `The installed version was deprecated: ${provider.current_version_deprecation_reason}`
                  : 'The installed version was deprecated by your project. Pull the supported release.'
                : `${gapLabel} from ${provider.project_name}. Review the changes, then pull when ready.`}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={`Review changes for ${resourceName}`}
              title="Review version changes"
              onClick={() => setOpen(true)}
            >
              <Info size={14} aria-hidden="true" />
            </Button>
            <Button type="button" size="sm" onClick={() => setOpen(true)}>
              Review &amp; pull
            </Button>
          </div>
        </div>
      </SettingsCallout>

      <Dialog open={open} onOpenChange={(next) => !pulling && setOpen(next)}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{required ? 'Required resource update' : 'Review resource update'}</DialogTitle>
            <DialogDescription>
              {resourceName} is managed by {provider.project_name}. EvoFlux keeps {installed}
              {' '}active until you explicitly pull {available}.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 p-4">
            <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 rounded-lg border border-(--color-border) bg-(--bg-key)/45 p-3 text-center">
              <VersionValue label="Installed" value={installed} />
              <span className="text-(--color-text-subtle)" aria-hidden="true">→</span>
              <VersionValue label={gapLabel} value={available} />
            </div>

            {provider.description && (
              <section>
                <h3 className="text-xs font-medium uppercase tracking-wide text-(--color-text-subtle)">
                  Resource description
                </h3>
                <p className="mt-1 text-sm leading-relaxed text-(--color-text-muted)">
                  {provider.description}
                </p>
              </section>
            )}

            <section>
              <h3 className="text-xs font-medium uppercase tracking-wide text-(--color-text-subtle)">
                Changes included
              </h3>
              <div className="mt-2 max-h-64 space-y-2 overflow-y-auto pr-1">
                {changes.length > 0 ? changes.map((notice) => (
                  <VersionChange key={notice.version_id} notice={notice} />
                )) : (
                  <div className="rounded-lg border border-(--color-border) p-3 text-sm text-(--color-text-muted)">
                    {provider.changelog || 'No release notes were provided for this version.'}
                  </div>
                )}
              </div>
            </section>

            {required && (
              <SettingsCallout tone="error" icon={AlertTriangle}>
                This notice cannot be dismissed permanently because the installed version is
                deprecated. The current version stays active only until you pull the supported release.
              </SettingsCallout>
            )}
            {error && <SettingsCallout tone="error">{error}</SettingsCallout>}
          </div>

          <DialogFooter className="p-3">
            <Button type="button" variant="outline" disabled={pulling} onClick={() => setOpen(false)}>
              Not now
            </Button>
            <Button type="button" disabled={pulling} onClick={() => void pull()}>
              {pulling ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Download aria-hidden="true" />}
              {pulling ? 'Pulling…' : `Pull ${available}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function changesAfterInstalled(
  provider: ManagedResourceProvider,
): ManagedResourceVersionNotice[] {
  const history = provider.version_history ?? []
  const desiredIndex = history.findIndex((item) => item.version_id === provider.version_id)
  const installedIndex = history.findIndex(
    (item) => item.version_id === provider.applied_version_id,
  )
  if (desiredIndex === -1) return []
  if (installedIndex >= 0 && installedIndex < desiredIndex) {
    return history.slice(installedIndex + 1, desiredIndex + 1)
  }
  return [history[desiredIndex]]
}

function VersionValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] uppercase tracking-wide text-(--color-text-subtle)">{label}</p>
      <p className="mt-1 truncate font-mono text-sm font-medium text-(--color-text)">{value}</p>
    </div>
  )
}

function VersionChange({ notice }: { notice: ManagedResourceVersionNotice }) {
  return (
    <article className="rounded-lg border border-(--color-border) bg-(--bg-card) p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs font-medium text-(--color-text)">v{notice.version}</span>
        <span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-[10px] capitalize text-(--color-text-muted)">
          {notice.release_channel}
        </span>
        {notice.status === 'deprecated' && (
          <span className="rounded-full bg-(--color-error-subtle) px-2 py-0.5 text-[10px] text-(--color-error)">
            Deprecated
          </span>
        )}
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-(--color-text-muted)">
        {notice.changelog || 'No release notes were provided.'}
      </p>
      {notice.deprecation_reason && (
        <p className="mt-1 text-xs text-(--color-error)">{notice.deprecation_reason}</p>
      )}
    </article>
  )
}
