/**
 * /settings/remote-access — Remote access (phone/Telegram) settings page.
 *
 * One-tap, outbound-only phone access through a user-owned Telegram bot.
 * States: unconfigured → validating → configured-disabled → connecting →
 * paired → removal confirmation.
 */
import { useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Copy,
  ExternalLink,
  Link2,
  Loader2,
  QrCode,
  Smartphone,
  Trash2,
  Wifi,
  WifiOff,
  XCircle,
} from 'lucide-react'

import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useConfirm } from '@/hooks/use-confirm'

import {
  useConnectionsQuery,
  useCreateConnectionMutation,
  useIssuePairingLinkMutation,
  usePairingQuery,
  usePatchConnectionMutation,
  useRemoveConnectionMutation,
  useRevokePairingMutation,
} from '@/queries/useRemoteQuery'
import type { RemoteConnection, RemoteConnectionState } from '@/api/client/remote'

export function RemoteAccessSettingsPage() {
  const connQ = useConnectionsQuery()
  const connection = connQ.data?.[0] ?? null

  return (
    <SettingsPage
      icon={Smartphone}
      title="Remote access"
      lede="Connect your phone to chat with EvoFlux when you are away from your desk. EvoFlux must stay running on this computer."
    >
      {connection ? (
        <ConfiguredState connection={connection} />
      ) : (
        <UnconfiguredState />
      )}
    </SettingsPage>
  )
}

// ── Unconfigured state ───────────────────────────────────────────────────────

function UnconfiguredState() {
  const [token, setToken] = useState('')
  const [label, setLabel] = useState('My phone')
  const createMut = useCreateConnectionMutation()
  const [error, setError] = useState<string | null>(null)

  async function handleConnect() {
    setError(null)
    if (!token.trim()) {
      setError('Paste a bot token from @BotFather.')
      return
    }
    try {
      await createMut.mutateAsync({ label: label.trim() || 'My phone', token: token.trim() })
      setToken('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <>
      <SettingsGroup
        title="Set up a Telegram bot"
        description="Create a personal bot with @BotFather on Telegram, then paste its token here. Each computer needs its own bot."
      >
        <SettingsRow
          label="Bot token"
          description="The token from @BotFather. Write-only — stored in your OS credential vault, never returned by the API."
          stacked
          control={
            <div className="flex flex-col gap-2">
              <Input
                type="password"
                placeholder="123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                autoComplete="off"
                aria-label="Bot token"
              />
            </div>
          }
        />
        <SettingsRow
          label="Label"
          description="A short name to identify this connection."
          control={
            <Input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="My phone"
              maxLength={120}
              aria-label="Connection label"
            />
          }
        />
      </SettingsGroup>

      {error && (
        <SettingsCallout tone="error" icon={AlertCircle}>
          {error}
        </SettingsCallout>
      )}

      <div className="flex items-center gap-3">
        <Button
          onClick={() => void handleConnect()}
          disabled={createMut.isPending || !token.trim()}
        >
          {createMut.isPending ? (
            <Loader2 className="mr-2 size-4 animate-spin" />
          ) : (
            <Link2 className="mr-2 size-4" />
          )}
          Connect phone
        </Button>
      </div>

      <SettingsCallout tone="info" icon={Smartphone}>
        EvoFlux must stay running on this computer for remote access to work.
        Messages sent while EvoFlux is stopped will not run later.
      </SettingsCallout>
    </>
  )
}

// ── Configured state ─────────────────────────────────────────────────────────

function ConfiguredState({ connection }: { connection: RemoteConnection }) {
  const patchMut = usePatchConnectionMutation()
  const removeMut = useRemoveConnectionMutation()
  const { request: confirmRequest, confirm, close } = useConfirm()

  const state = connection.status.state
  const enabled = connection.enabled

  async function handleToggleEnabled(next: boolean) {
    try {
      await patchMut.mutateAsync({ id: connection.id, body: { enabled: next } })
    } catch {
      // Toast is handled by mutation onError if needed.
    }
  }

  function requestRemove() {
    confirm({
      title: 'Remove remote access?',
      description:
        'This will unpair your phone and delete the bot connection. You can reconnect later with the same or a different bot.',
      confirmLabel: 'Remove',
      destructive: true,
      onConfirm: () => void handleRemove(),
    })
  }

  async function handleRemove() {
    try {
      await removeMut.mutateAsync(connection.id)
      close()
    } catch {
      // keep dialog open
    }
  }

  return (
    <>
      <SettingsGroup title="Connection">
        <SettingsRow
          label="Bot"
          description={`@${connection.adapter_username || 'unknown'} (${connection.adapter})`}
          control={
            <span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-[11px] text-(--color-text-muted)">
              {connection.adapter}
            </span>
          }
        />
        <SettingsRow
          label="Label"
          description={connection.label}
          control={<ConnectionStateBadge state={state} />}
        />
        <SettingsRow
          label="Enabled"
          description={enabled ? 'Adapter is running and polling.' : 'Adapter is stopped.'}
          control={
            <Switch
              checked={enabled}
              onCheckedChange={(next) => void handleToggleEnabled(next)}
              disabled={patchMut.isPending}
              aria-label="Enable remote access"
            />
          }
        />
      </SettingsGroup>

      {enabled && (
        <PairingSection connectionId={connection.id} state={state} />
      )}

      <SettingsGroup title="Danger zone">
        <SettingsRow
          label="Remove connection"
          description="Deletes the connection, vault credential, and pairing. The bot token is not reused."
          control={
            <Button
              variant="destructive"
              size="sm"
              onClick={requestRemove}
            >
              <Trash2 className="mr-1.5 size-3.5" />
              Remove
            </Button>
          }
        />
      </SettingsGroup>

      <ConfirmDialog
        request={confirmRequest}
        busy={removeMut.isPending}
        onClose={close}
      />
    </>
  )
}

// ── Pairing section ──────────────────────────────────────────────────────────

function PairingSection({
  connectionId,
  state,
}: {
  connectionId: string
  state: RemoteConnectionState
}) {
  const pairingQ = usePairingQuery(connectionId)
  const linkMut = useIssuePairingLinkMutation()
  const revokeMut = useRevokePairingMutation()
  const [linkCopied, setLinkCopied] = useState(false)

  const paired = pairingQ.data != null

  async function handleGetLink() {
    setLinkCopied(false)
    await linkMut.mutateAsync(connectionId)
  }

  async function handleCopyLink() {
    if (linkMut.data?.url) {
      await navigator.clipboard.writeText(linkMut.data.url)
      setLinkCopied(true)
    }
  }

  async function handleRevoke() {
    await revokeMut.mutateAsync(connectionId)
  }

  return (
    <SettingsGroup title="Pairing">
      {paired ? (
        <>
          <SettingsRow
            label="Paired device"
            description={`${pairingQ.data?.display || pairingQ.data?.label || 'Unknown'} — last seen ${pairingQ.data ? formatRelativeTime(pairingQ.data.last_seen_at) : 'never'}`}
            control={
              <span className="flex items-center gap-1.5 text-xs text-(--color-success)">
                <CheckCircle2 size={14} />
                Paired
              </span>
            }
          />
          <SettingsRow
            label="Unpair"
            description="Remove this phone's access. You can pair again later."
            control={
              <Button
                variant="outline"
                size="sm"
                onClick={() => void handleRevoke()}
                disabled={revokeMut.isPending}
              >
                Unpair
              </Button>
            }
          />
        </>
      ) : (
        <>
          <SettingsRow
            label="Connect phone"
            description={
              state === 'polling'
                ? 'Generate a one-tap link or QR code to pair your phone.'
                : `Waiting for adapter to connect (current state: ${state}).`
            }
            stacked
            control={
              <div className="flex flex-col gap-3">
                <Button
                  onClick={() => void handleGetLink()}
                  disabled={linkMut.isPending || state !== 'polling'}
                >
                  {linkMut.isPending ? (
                    <Loader2 className="mr-2 size-4 animate-spin" />
                  ) : (
                    <QrCode className="mr-2 size-4" />
                  )}
                  Generate pairing link
                </Button>

                {linkMut.data && (
                  <div className="flex flex-col gap-2 rounded-lg border border-(--color-border) bg-(--bg-key) p-3">
                    <div className="flex items-center gap-2">
                      <a
                        href={linkMut.data.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="min-w-0 flex-1 truncate text-sm text-(--color-accent) underline underline-offset-2"
                      >
                        {linkMut.data.url}
                      </a>
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        onClick={() => void handleCopyLink()}
                        aria-label="Copy link"
                      >
                        {linkCopied ? (
                          <CheckCircle2 size={14} className="text-(--color-success)" />
                        ) : (
                          <Copy size={14} />
                        )}
                      </Button>
                      <Button
                        size="icon-xs"
                        variant="ghost"
                        onClick={() => window.open(linkMut.data.url, '_blank')}
                        aria-label="Open link"
                      >
                        <ExternalLink size={14} />
                      </Button>
                    </div>
                    <p className="text-xs text-(--color-text-muted)">
                      Link expires {formatRelativeTime(linkMut.data.expires_at)}.
                      Open it on your phone or scan the QR code in the Telegram app.
                    </p>
                  </div>
                )}
              </div>
            }
          />
        </>
      )}
    </SettingsGroup>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function ConnectionStateBadge({ state }: { state: RemoteConnectionState }) {
  const { color, icon: Icon, label } = STATE_CONFIG[state] ?? STATE_CONFIG.error
  return (
    <span className={`flex items-center gap-1.5 text-xs ${color}`}>
      <Icon size={14} />
      {label}
    </span>
  )
}

const STATE_CONFIG: Record<
  RemoteConnectionState,
  { color: string; icon: typeof Wifi; label: string }
> = {
  disabled: { color: 'text-(--color-text-muted)', icon: WifiOff, label: 'Disabled' },
  starting: { color: 'text-(--color-text-muted)', icon: Loader2, label: 'Starting' },
  pairing: { color: 'text-(--color-accent)', icon: Link2, label: 'Pairing' },
  polling: { color: 'text-(--color-success)', icon: Wifi, label: 'Connected' },
  backoff: { color: 'text-(--color-warning)', icon: WifiOff, label: 'Reconnecting' },
  rate_limited: { color: 'text-(--color-warning)', icon: WifiOff, label: 'Rate limited' },
  used_elsewhere: { color: 'text-(--color-error)', icon: XCircle, label: 'Used elsewhere' },
  invalid_token: { color: 'text-(--color-error)', icon: XCircle, label: 'Invalid token' },
  phone_unreachable: { color: 'text-(--color-warning)', icon: WifiOff, label: 'Phone unreachable' },
  credential_missing: { color: 'text-(--color-error)', icon: XCircle, label: 'Credential missing' },
  error: { color: 'text-(--color-error)', icon: XCircle, label: 'Error' },
}

function formatRelativeTime(iso: string): string {
  try {
    const date = new Date(iso)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    if (diffMs < 0) return 'just now'
    const diffMin = Math.floor(diffMs / 60_000)
    if (diffMin < 1) return 'just now'
    if (diffMin < 60) return `${diffMin}m ago`
    const diffH = Math.floor(diffMin / 60)
    if (diffH < 24) return `${diffH}h ago`
    const diffD = Math.floor(diffH / 24)
    return `${diffD}d ago`
  } catch {
    return iso
  }
}
