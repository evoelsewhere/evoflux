/**
 * /settings/remote-use — "Remote Control": embedded/external Tailscale control.
 *
 * Connect the bundled node, enable/disable its tailnet listener, show the URL
 * (+ QR) for the phone, and surface the one-device lock: who holds it,
 * when it was claimed/last seen, and a Release button. HTTP 409 from
 * enable/release renders as "device X holds the lock".
 */

import { QRCodeSVG } from 'qrcode.react'
import {
  BookOpen,
  Check,
  Clock3,
  Copy,
  Link2,
  Lock,
  LogIn,
  MonitorSmartphone,
  QrCode,
  ShieldCheck,
  Smartphone,
  Wifi,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'

import {
  formatRemoteUseError,
  useConnectRemoteUseMutation,
  useDisableRemoteUseMutation,
  useEnableRemoteUseMutation,
  useReleaseRemoteUseLockMutation,
  useRemoteUseStatusQuery,
} from '@/api/client/remoteUse'
import { RemoteControlPolicyDialog } from '@/components/settings/RemoteControlPolicyDialog'
import { SettingsCallout, SettingsGroup, SettingsPage } from '@/components/settings/SettingsLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { openExternalUrl } from '@/lib/open-external'
import { isRemoteControlPolicyAcknowledged } from '@/lib/remote-control-policy'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/useUIStore'

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

function ConnectionMetric({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon
  label: string
  value: string
}) {
  return (
    <div className="flex min-w-0 items-center gap-3 px-4 py-3.5 sm:px-5">
      <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-(--bg-key) text-(--color-text-muted)">
        <Icon className="size-3.5" aria-hidden="true" />
      </div>
      <div className="min-w-0">
        <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-(--color-text-subtle)">{label}</p>
        <p className="mt-0.5 truncate text-xs font-medium text-(--color-text)">{value}</p>
      </div>
    </div>
  )
}

interface GuideStep {
  title: string
  text: string
  done: boolean
}

/**
 * The page's own setup walkthrough: four steps from signing in to opening
 * EvoFlux on the phone, ticked off from live status so the next thing to do
 * is always the highlighted one. The Guidelines topic holds the long form.
 */
function SetupGuide({ steps }: { steps: GuideStep[] }) {
  const current = steps.findIndex((step) => !step.done)
  return (
    <SettingsGroup
      title="How to set up"
      description="Four steps, once. After that, Remote Control reconnects on its own whenever EvoFlux starts."
      actions={(
        <Button
          variant="outline"
          size="sm"
          onClick={() => useUIStore.getState().openGuidelines('phone-access')}
        >
          <BookOpen className="size-3.5" />
          Full guide
        </Button>
      )}
      bare
    >
      <ol className="grid gap-2 sm:grid-cols-2">
        {steps.map((step, index) => {
          const isCurrent = index === current
          return (
            <li
              key={step.title}
              aria-current={isCurrent ? 'step' : undefined}
              className={cn(
                'flex gap-3 rounded-xl border p-3.5 transition-colors',
                isCurrent
                  ? 'border-(--color-accent)/35 bg-(--color-accent-soft)'
                  : 'border-(--color-border-subtle) bg-(--bg-card)',
              )}
            >
              <span
                className={cn(
                  'flex size-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold tabular-nums',
                  step.done
                    ? 'bg-(--color-success)/12 text-(--color-success)'
                    : isCurrent
                      ? 'bg-(--color-accent) text-(--color-text-on-accent)'
                      : 'bg-(--bg-key) text-(--color-text-muted)',
                )}
              >
                {step.done ? <Check className="size-3.5" aria-label="Done" /> : index + 1}
              </span>
              <div className="min-w-0">
                <p className={cn('text-xs font-medium', step.done ? 'text-(--color-text-muted)' : 'text-(--color-text)')}>
                  {step.title}
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-(--color-text-muted)">{step.text}</p>
              </div>
            </li>
          )
        })}
      </ol>
    </SettingsGroup>
  )
}

export function RemoteUseSettingsPage() {
  const navigate = useSettingsNavigate()
  const [policyAccepted, setPolicyAccepted] = useState(isRemoteControlPolicyAcknowledged)
  const statusQ = useRemoteUseStatusQuery()
  const connectM = useConnectRemoteUseMutation()
  const enableM = useEnableRemoteUseMutation()
  const disableM = useDisableRemoteUseMutation()
  const releaseM = useReleaseRemoteUseLockMutation()
  const [copied, setCopied] = useState(false)

  const status = statusQ.data
  const tailscale = status?.tailscale
  const serve = status?.serve
  const lock = status?.lock
  const embedded = tailscale?.provider === 'embedded'

  // Embedded tsnet can fall back to HTTP inside the encrypted tailnet. The
  // external Serve provider still requires tailnet HTTPS certificates.
  const tunnelReady = !!status && !!tailscale?.installed && tailscale.logged_in && !tailscale.error
    && (embedded || tailscale.https_certs === true)
  const tunnelBusy = connectM.isPending || enableM.isPending || disableM.isPending
  const actionError = connectM.error ?? enableM.error ?? disableM.error

  async function connectTailnet() {
    try {
      const next = await connectM.mutateAsync()
      const authUrl = next.tailscale.auth_url
      if (authUrl) await openExternalUrl(authUrl)
    } catch {
      // Surfaced below through the mutation error state.
    }
  }

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

  let stateTone: 'live' | 'ready' | 'setup' | 'warning' = 'setup'
  let stateEyebrow = 'Setup required'
  let stateTitle = 'Connect your tailnet'
  let stateDescription = 'Sign in once to make this computer available to your phone.'
  if (statusQ.isError) {
    stateTone = 'warning'
    stateEyebrow = 'Connection error'
    stateTitle = 'Could not read Remote Control status'
    stateDescription = formatRemoteUseError(statusQ.error)
  } else if (tailscale?.error && !(embedded && tailscale.auth_url)) {
    stateTone = 'warning'
    stateEyebrow = 'Needs attention'
    stateTitle = 'Tailscale is not ready'
    stateDescription = tailscale.error
  } else if (tailscale && !tailscale.installed) {
    stateTone = 'warning'
    stateEyebrow = 'External provider'
    stateTitle = 'Install Tailscale to continue'
    stateDescription = 'This source build uses the external Tailscale service. Install it, sign in, then try again.'
  } else if (tailscale && !tailscale.logged_in) {
    stateEyebrow = embedded ? 'Built into EvoFlux' : 'Sign-in required'
    stateTitle = 'Connect your tailnet'
    stateDescription = embedded
      ? 'No separate app or command line setup. Sign in once and EvoFlux remembers this computer.'
      : 'Open the Tailscale app or run `tailscale up`, then return here.'
  } else if (tailscale && tailscale.https_certs === false && !embedded) {
    stateTone = 'warning'
    stateEyebrow = 'HTTPS required'
    stateTitle = 'Enable tailnet certificates'
    stateDescription = 'Turn on HTTPS certificates in the Tailscale admin console before enabling Remote Control.'
  } else if (serve?.enabled && serve.url) {
    stateTone = 'live'
    stateEyebrow = 'Live on your tailnet'
    stateTitle = 'Remote Control is ready'
    stateDescription = 'Your phone can securely reach this EvoFlux desktop while the app stays open.'
  } else if (tunnelReady) {
    stateTone = 'ready'
    stateEyebrow = 'Tailnet connected'
    stateTitle = 'Ready to enable Remote Control'
    stateDescription = 'Turn it on when you want this computer to accept connections from your phone.'
  }

  const guideSteps: GuideStep[] = [
    {
      title: embedded ? 'Connect this computer' : 'Sign in to Tailscale',
      text: embedded
        ? 'Click Connect Tailscale and finish the sign-in in your browser. EvoFlux remembers this computer.'
        : 'Open the Tailscale app, or run tailscale up, on this computer.',
      done: !!tailscale?.logged_in,
    },
    {
      title: 'Get Tailscale on your phone',
      text: 'Install the Tailscale app and sign in to the same tailnet as this computer.',
      done: !!lock,
    },
    {
      title: 'Turn on Remote Control',
      text: 'Use the switch above. A private address and a QR code appear on this page.',
      done: !!serve?.enabled,
    },
    {
      title: 'Open it from your phone',
      text: 'Scan the QR code or open the address. One device can connect at a time.',
      done: !!lock,
    },
  ]

  const live = stateTone === 'live'
  const stateAccent = live
    ? 'border-(--color-success)/30 bg-(--color-success)/10 text-(--color-success)'
    : stateTone === 'warning'
      ? 'border-(--color-warning)/30 bg-(--color-warning)/10 text-(--color-warning)'
      : 'border-(--color-accent)/25 bg-(--color-accent-soft) text-(--color-accent)'

  return (
    <SettingsPage
      icon={MonitorSmartphone}
      title="Remote Control"
      size="wide"
      lede="Reach this computer from your phone over your own tailnet — no cloud relay or pairing code. Desktop builds include their own Tailscale node, so no separate CLI or daemon setup is required."
    >
      <RemoteControlPolicyDialog
        open={!policyAccepted}
        onAccept={() => setPolicyAccepted(true)}
        onLeave={() => navigate('/settings')}
      />

      <SettingsGroup bare>
        <div className="relative overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card) shadow-[0_18px_50px_rgba(0,0,0,0.06)]">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -right-16 -top-20 size-56 rounded-full bg-(--color-accent)/8 blur-3xl"
          />
          {statusQ.isLoading ? (
            <div className="space-y-4 p-5 sm:p-6">
              <Skeleton className="h-5 w-32 rounded-full" />
              <Skeleton className="h-8 w-72 max-w-full" />
              <Skeleton className="h-4 w-full max-w-xl" />
            </div>
          ) : (
            <>
              <div className="relative flex flex-col gap-5 p-5 sm:flex-row sm:items-start sm:justify-between sm:p-6">
                <div className="flex min-w-0 gap-4">
                  <div className={`flex size-11 shrink-0 items-center justify-center rounded-xl border ${stateAccent}`}>
                    {live ? <Wifi className="size-5" aria-hidden="true" /> : <MonitorSmartphone className="size-5" aria-hidden="true" />}
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-(--color-text-subtle)">
                        <span className={`size-1.5 rounded-full ${live ? 'bg-(--color-success) shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-success)_14%,transparent)]' : 'bg-(--color-text-subtle)'}`} />
                        {stateEyebrow}
                      </span>
                      <Badge variant="outline">{embedded ? 'Built in' : 'External'}</Badge>
                    </div>
                    <h2 className="mt-2 font-heading text-xl font-semibold tracking-[-0.025em] text-(--color-text) sm:text-2xl">
                      {stateTitle}
                    </h2>
                    <p className="mt-1.5 max-w-[58ch] text-sm leading-relaxed text-(--color-text-muted)">
                      {stateDescription}
                    </p>
                  </div>
                </div>

                <div className="flex shrink-0 items-center sm:pt-1">
                  {statusQ.isError ? (
                    <Button variant="outline" onClick={() => statusQ.refetch()}>
                      Try again
                    </Button>
                  ) : embedded && !tailscale?.logged_in ? (
                    <Button
                      disabled={connectM.isPending}
                      onClick={() => {
                        if (tailscale?.auth_url) void openExternalUrl(tailscale.auth_url)
                        else void connectTailnet()
                      }}
                    >
                      <LogIn className="size-4" />
                      {connectM.isPending ? 'Connecting…' : tailscale?.auth_url ? 'Open login' : 'Connect Tailscale'}
                    </Button>
                  ) : (
                    <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-(--color-border) bg-(--bg-page)/70 px-3.5 py-2.5 shadow-sm">
                      <span>
                        <span className="block text-xs font-semibold text-(--color-text)">Remote Control</span>
                        <span className="mt-0.5 block text-[11px] text-(--color-text-muted)">
                          {serve?.enabled ? 'On' : 'Off'}
                        </span>
                      </span>
                      <Switch
                        aria-label="Enable Remote Control"
                        checked={!!serve?.enabled}
                        disabled={!tunnelReady || tunnelBusy || statusQ.isLoading}
                        onCheckedChange={toggleTunnel}
                      />
                    </label>
                  )}
                </div>
              </div>

              <div className="relative grid divide-y divide-(--color-border-subtle) border-t border-(--color-border-subtle) bg-(--bg-page)/35 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
                <ConnectionMetric
                  icon={ShieldCheck}
                  label="Provider"
                  value={embedded ? 'Embedded tsnet' : 'Tailscale Serve'}
                />
                <ConnectionMetric
                  icon={Wifi}
                  label="Network"
                  value={tailscale?.logged_in ? 'Tailnet connected' : 'Not connected'}
                />
                <ConnectionMetric
                  icon={Lock}
                  label="Transport"
                  value={tailscale?.https_certs ? 'HTTPS' : embedded ? 'Encrypted tailnet' : 'HTTPS unavailable'}
                />
              </div>
            </>
          )}
        </div>
      </SettingsGroup>

      {!statusQ.isLoading && !statusQ.isError && <SetupGuide steps={guideSteps} />}

      {serve?.enabled && serve.url && (
        <SettingsGroup
          title="Open on your phone"
          description="Your private address only works for devices signed in to the same tailnet."
          bare
        >
          <div className="grid overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card) shadow-[0_10px_32px_rgba(0,0,0,0.04)] lg:grid-cols-[minmax(0,1fr)_12.5rem]">
            <div className="p-5 sm:p-6">
              <div className="grid gap-3 sm:grid-cols-3">
                {[
                  ['1', 'Open Tailscale', 'Make sure the phone is connected.'],
                  ['2', 'Scan the code', 'Use the camera or Tailscale browser.'],
                  ['3', 'Keep EvoFlux open', 'Access ends when the desktop exits.'],
                ].map(([number, title, description]) => (
                  <div key={number} className="flex gap-2.5 rounded-xl bg-(--bg-key)/55 p-3">
                    <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-(--color-accent) text-[10px] font-bold text-(--color-text-on-accent)">
                      {number}
                    </span>
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-(--color-text)">{title}</p>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-(--color-text-muted)">{description}</p>
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-5 flex flex-col gap-3 rounded-xl border border-(--color-border) bg-(--bg-page)/65 p-3.5 sm:flex-row sm:items-center">
                <div className="flex min-w-0 flex-1 items-center gap-3">
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-(--color-accent-soft) text-(--color-accent)">
                    <Link2 className="size-3.5" aria-hidden="true" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-[11px] font-medium text-(--color-text-subtle)">Private address</p>
                    <p className="mt-0.5 truncate font-mono text-xs text-(--color-text)" title={serve.url}>
                      {serve.url}
                    </p>
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={copyUrl}>
                  {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                  {copied ? 'Copied' : 'Copy address'}
                </Button>
              </div>
            </div>

            <div className="flex flex-col items-center justify-center border-t border-(--color-border-subtle) bg-(--bg-key)/35 p-5 lg:border-l lg:border-t-0">
              <div className="rounded-2xl border border-black/10 bg-white p-3 shadow-[0_10px_28px_rgba(0,0,0,0.12)]">
                <QRCodeSVG value={serve.url} size={136} aria-label="Remote Control QR code" />
              </div>
              <span className="mt-3 inline-flex items-center gap-1.5 text-[11px] font-medium text-(--color-text-muted)">
                <QrCode className="size-3.5" aria-hidden="true" />
                Scan to open
              </span>
            </div>
          </div>
        </SettingsGroup>
      )}

      {actionError && (
        <SettingsCallout tone="warning" icon={Smartphone}>
          {formatRemoteUseError(actionError)}
        </SettingsCallout>
      )}

      <SettingsGroup
        title="Remote session"
        description="Only one device can control this computer at a time. Inactive sessions release automatically after 30 minutes."
        bare
      >
        <div className="rounded-2xl border border-(--color-border) bg-(--bg-card) p-4 shadow-[0_10px_32px_rgba(0,0,0,0.035)] sm:p-5">
          {statusQ.isLoading ? (
            <div className="flex items-center gap-3">
              <Skeleton className="size-10 rounded-xl" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-36" />
                <Skeleton className="h-3 w-56 max-w-full" />
              </div>
            </div>
          ) : lock ? (
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
              <div className="relative flex size-11 shrink-0 items-center justify-center rounded-xl bg-(--color-success)/10 text-(--color-success)">
                <Smartphone className="size-5" aria-hidden="true" />
                <span className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full border-2 border-(--bg-card) bg-(--color-success)" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="truncate font-heading text-base font-semibold text-(--color-text)">
                    {lock.device_label || 'Remote device'}
                  </p>
                  <Badge variant="secondary">Connected</Badge>
                </div>
                <p className="mt-1 truncate text-xs text-(--color-text-muted)">{lock.user_login}</p>
              </div>
              <div className="grid grid-cols-2 gap-4 sm:shrink-0 sm:gap-6">
                <div>
                  <p className="text-[10px] font-medium uppercase tracking-[0.08em] text-(--color-text-subtle)">Connected</p>
                  <p className="mt-1 text-xs font-medium text-(--color-text)">{relativeTime(lock.claimed_at)}</p>
                </div>
                <div>
                  <p className="text-[10px] font-medium uppercase tracking-[0.08em] text-(--color-text-subtle)">Last active</p>
                  <p className="mt-1 text-xs font-medium text-(--color-text)">{relativeTime(lock.last_seen_at)}</p>
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={releaseM.isPending}
                onClick={() => releaseM.mutate()}
              >
                <Lock className="size-3.5" />
                {releaseM.isPending ? 'Releasing…' : 'Release'}
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-3.5">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-(--bg-key) text-(--color-text-muted)">
                <ShieldCheck className="size-4.5" aria-hidden="true" />
              </div>
              <div>
                <p className="text-sm font-medium text-(--color-text)">No phone connected</p>
                <p className="mt-1 text-xs text-(--color-text-muted)">The next verified device will claim this session automatically.</p>
              </div>
            </div>
          )}
        </div>
        {releaseM.error && (
          <SettingsCallout tone="warning" icon={Lock} className="mt-3">
            {formatRemoteUseError(releaseM.error)}
          </SettingsCallout>
        )}
      </SettingsGroup>

      <SettingsCallout tone="info" icon={Clock3}>
        Remote Control only works while EvoFlux is open. Your provider, bot, and plugin credentials remain on this
        computer and are never copied to the phone.
      </SettingsCallout>
    </SettingsPage>
  )
}
