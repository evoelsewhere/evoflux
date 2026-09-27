/**
 * /settings/remote-use — "Phone access": Tailscale Serve control.
 *
 * Enable/disable the tailnet HTTPS tunnel, show the stable .ts.net URL
 * (+ QR) for the phone, and surface the one-device lock: who holds it,
 * when it was claimed/last seen, and a Release button. HTTP 409 from
 * enable/release renders as "device X holds the lock".
 */

import { QRCodeSVG } from 'qrcode.react'
import { Check, Copy, Lock, Smartphone } from 'lucide-react'
import { useState } from 'react'

import {
  formatRemoteUseError,
  useDisableRemoteUseMutation,
  useEnableRemoteUseMutation,
  useReleaseRemoteUseLockMutation,
  useRemoteUseStatusQuery,
} from '@/api/client/remoteUse'
import { SettingsCallout, SettingsGroup, SettingsPage, SettingsRow } from '@/components/settings/SettingsLayout'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

function relativeTime(iso: string): string {
  if (!iso) return '—'
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return iso
  const diffMs = Date.now() - then
  const future = diffMs < 0
  const diffMin = Math.round(Math.abs(diffMs) / 60000)
  if (diffMin < 1) return future ? 'in under a minute' : 'just now'
  if (diffMin < 60) return future ? `in ${diffMin}m` : `${diffMin}m ago`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return future ? `in ${diffH}h` : `${diffH}h ago`
  const diffD = Math.floor(diffH / 24)
  return future ? `in ${diffD}d` : `${diffD}d ago`
}

export function RemoteUseSettingsPage() {
  const statusQ = useRemoteUseStatusQuery()
  const enableM = useEnableRemoteUseMutation()
  const disableM = useDisableRemoteUseMutation()
  const releaseM = useReleaseRemoteUseLockMutation()
  const [copied, setCopied] = useState(false)

  const status = statusQ.data
  const tailscale = status?.tailscale
  const serve = status?.serve
  const lock = status?.lock

  // Serve can only be enabled with Tailscale installed, signed in, and
  // HTTPS certificates available (https_certs is null while unknown).
  const tunnelReady =
    !!status && !!tailscale?.installed && tailscale.logged_in && tailscale.https_certs === true && !tailscale.error
  const tunnelBusy = enableM.isPending || disableM.isPending
  const actionError = enableM.error ?? disableM.error

  async function toggleTunnel(next: boolean) {
    try {
      if (next) await enableM.mutateAsync()
      else await disableM.mutateAsync()
    } catch {
      // Surfaced below through the mutation error state (incl. 409 lock).
    }
  }

  async function copyUrl() {
    if (!serve?.url) return
    try {
      await navigator.clipboard.writeText(serve.url)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard denied — the URL stays visible for manual copy.
    }
  }

  let readiness: { tone: 'info' | 'success' | 'warning' | 'error'; text: string } | null = null
  if (statusQ.isError) {
    readiness = { tone: 'error', text: formatRemoteUseError(statusQ.error) }
  } else if (tailscale?.error) {
    readiness = { tone: 'warning', text: `Tailscale reports: ${tailscale.error}` }
  } else if (tailscale && !tailscale.installed) {
    readiness = {
      tone: 'warning',
      text: 'Tailscale is not installed on this computer. Install it and sign in to allow phone access.',
    }
  } else if (tailscale && !tailscale.logged_in) {
    readiness = { tone: 'warning', text: 'Tailscale is installed but not signed in. Run `tailscale up` first.' }
  } else if (tailscale && tailscale.https_certs === false) {
    readiness = {
      tone: 'warning',
      text: 'HTTPS certificates are not enabled. Phone access requires them. To enable: open Tailscale app or admin console, then Settings > HTTPS certificates > turn on.',
    }
  } else if (tunnelReady) {
    readiness = { tone: 'success', text: 'This computer is reachable over your tailnet.' }
  }

  return (
    <SettingsPage
      icon={Smartphone}
      title="Phone access"
      lede="Reach this computer from your phone over your own tailnet — no cloud relay, no pairing codes. Tailscale Serve exposes a stable HTTPS address that only tailnet devices can open."
    >
      <SettingsGroup title="Tailscale">
        {statusQ.isLoading && (
          <SettingsRow label="Status" description="Loading tailnet status…" control={<Skeleton className="size-9" />} />
        )}
        {readiness && (
          <SettingsRow
            label="Status"
            description={readiness.text}
            control={
              statusQ.isError ? (
                <Button variant="outline" size="sm" onClick={() => statusQ.refetch()}>
                  Try again
                </Button>
              ) : undefined
            }
          />
        )}
        {tailscale && (
          <SettingsRow
            label="HTTPS certificates"
            description={
              tailscale.https_certs === null
                ? 'Unknown until Tailscale finishes its first check.'
                : tailscale.https_certs
                  ? 'Issued by your tailnet — *.ts.net addresses use HTTPS.'
                  : 'Off — Serve would only expose plain HTTP.'
            }
            control={<span className="text-xs text-(--color-text-muted)">{tailscale.https_certs ? 'On' : 'Off'}</span>}
          />
        )}
      </SettingsGroup>

      <SettingsGroup title="Tunnel">
        <SettingsRow
          label="Phone access"
          description={
            serve?.enabled && serve.url
              ? `Serve is on — your phone can open ${serve.url}`
              : 'Expose this computer at a stable .ts.net HTTPS address while it is on.'
          }
          control={
            <Switch
              checked={!!serve?.enabled}
              disabled={!tunnelReady || tunnelBusy || statusQ.isLoading}
              onCheckedChange={toggleTunnel}
            />
          }
        />
        {serve?.enabled && serve.url && (
          <SettingsRow
            label="Tunnel address"
            description={serve.url}
            control={
              <Button variant="outline" size="sm" onClick={copyUrl}>
                {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                {copied ? 'Copied' : 'Copy'}
              </Button>
            }
          />
        )}
        {serve?.enabled && serve.url && (
          <SettingsRow
            label="QR code"
            description="Scan from your phone while it is connected to the tailnet."
            control={
              <div className="rounded-lg border border-(--color-border) bg-white p-2">
                <QRCodeSVG value={serve.url} size={112} />
              </div>
            }
          />
        )}
        {actionError && (
          <SettingsCallout tone="warning" icon={Smartphone}>
            {formatRemoteUseError(actionError)}
          </SettingsCallout>
        )}
      </SettingsGroup>

      <SettingsGroup
        title="Device lock"
        description="One device at a time may drive this computer remotely. The lock frees itself after 30 minutes without a request."
      >
        {statusQ.isLoading && <SettingsRow label="Holder" description="Loading…" control={<Skeleton className="size-9" />} />}
        {!statusQ.isLoading && !lock && (
          <SettingsRow label="Holder" description="No device holds the lock." />
        )}
        {lock && (
          <>
            <SettingsRow
              label="Held by"
              description={
                [lock.user_login, lock.device_label].filter(Boolean).join(' · ') || 'Unknown device'
              }
            />
            <SettingsRow label="Claimed" description={relativeTime(lock.claimed_at)} />
            <SettingsRow
              label="Last seen"
              description={relativeTime(lock.last_seen_at)}
              control={
                <Button
                  variant="outline"
                  size="sm"
                  disabled={releaseM.isPending}
                  onClick={() => releaseM.mutate()}
                >
                  <Lock className="size-3.5" />
                  Release
                </Button>
              }
            />
          </>
        )}
        {releaseM.error && (
          <SettingsCallout tone="warning" icon={Lock}>
            {formatRemoteUseError(releaseM.error)}
          </SettingsCallout>
        )}
      </SettingsGroup>

      <SettingsCallout tone="info" icon={Smartphone}>
        EvoFlux must stay running on this computer for phone access to work, and the phone must be signed in to the
        same tailnet. Provider and bot credentials stay desktop-only regardless of where you connect from.
      </SettingsCallout>
    </SettingsPage>
  )
}
