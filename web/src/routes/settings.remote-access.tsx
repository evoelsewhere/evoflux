/**
 * /settings/remote-access — Remote access (phone/Telegram) settings page.
 *
 * One-tap, outbound-only phone access through a user-owned Telegram bot.
 * States: unconfigured → validating → configured-disabled → connecting →
 * paired → removal confirmation.
 */
import { useEffect, useRef, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import {
  AlertCircle,
  CheckCircle2,
  Copy,
  ExternalLink,
  Link2,
  Loader2,
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
import { SelectControl } from '@/components/ui/select'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useConfirm } from '@/hooks/use-confirm'

import {
  useConnectionsQuery,
  useCreateConnectionMutation,
  useIssuePairingLinkMutation,
  usePairingCodeQuery,
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
  const [adapter, setAdapter] = useState<'telegram' | 'imessage'>('telegram')
  const [provider, setProvider] = useState<'imsg' | 'bluebubbles'>('imsg')
  const [endpointUrl, setEndpointUrl] = useState('')
  const [label, setLabel] = useState('My phone')
  const createMut = useCreateConnectionMutation()
  const [error, setError] = useState<string | null>(null)
  const [botFatherCopied, setBotFatherCopied] = useState(false)

  async function handleOpenBotFather() {
    try {
      await navigator.clipboard.writeText('/newbot')
      setBotFatherCopied(true)
    } catch {
      // Clipboard may be blocked — user can type manually.
    }
    window.open('https://t.me/BotFather', '_blank', 'noopener,noreferrer')
  }

  async function handleConnect() {
    setError(null)
    if (!token.trim()) {
      setError(adapter === 'telegram' ? 'Paste a bot token from @BotFather.' : 'Enter the iMessage credential.')
      return
    }
    if (adapter === 'imessage' && provider === 'bluebubbles' && !endpointUrl.trim()) {
      setError('Enter the BlueBubbles server URL.')
      return
    }
    try {
      await createMut.mutateAsync({
        label: label.trim() || 'My phone',
        token: token.trim(),
        adapter,
        provider: adapter === 'imessage' ? provider : undefined,
        endpoint_url: adapter === 'imessage' ? endpointUrl.trim() || null : null,
      })
      setToken('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <>
      <SettingsGroup
        title="Set up remote access"
        description="Create a Telegram bot, then paste its token here to connect."
      >
        {/* ── Bot-creation helper (collapsible) ── */}
        <details className="group/bot rounded-lg border border-(--color-border) bg-(--color-surface)">
          <summary className="flex cursor-pointer items-center gap-2 px-4 py-3 text-sm font-medium text-(--color-text) select-none">
            <Smartphone className="size-4 shrink-0 text-(--color-text-muted)" />
            Need a bot? Create one with @BotFather
          </summary>
          <div className="flex flex-col gap-3 border-t border-(--color-border) px-4 py-3">
            <ol className="flex list-decimal flex-col gap-1.5 pl-4 text-sm text-(--color-text-muted)">
              <li>
                Open{' '}
                <a
                  href="https://t.me/BotFather"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-(--color-accent) underline"
                >
                  @BotFather
                </a>{' '}
                in Telegram.
              </li>
              <li>
                Send{' '}
                <code className="rounded bg-(--color-surface-raised) px-1 py-0.5 font-mono text-xs">
                  /newbot
                </code>
                , choose a name and username.
              </li>
              <li>Copy the token BotFather gives you.</li>
            </ol>
            <div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void handleOpenBotFather()}
              >
                <ExternalLink className="mr-1.5 size-3.5" />
                {botFatherCopied ? 'Copied! Open BotFather' : 'Open BotFather'}
              </Button>
            </div>
          </div>
        </details>

        <SettingsRow
          label="Channel"
          description="Choose the remote messaging transport."
          control={
            <SelectControl
              value={adapter}
              onValueChange={(value) => setAdapter(value as 'telegram' | 'imessage')}
              ariaLabel="Remote channel"
              options={[
                { value: 'telegram', label: 'Telegram' },
                { value: 'imessage', label: 'iMessage' },
              ]}
            />
          }
        />
        {adapter === 'imessage' && (
          <>
            <SettingsRow
              label="iMessage provider"
              description="Use native imsg on macOS or the BlueBubbles fallback."
              control={
                <SelectControl
                  value={provider}
                  onValueChange={(value) => setProvider(value as 'imsg' | 'bluebubbles')}
                  ariaLabel="iMessage provider"
                  options={[
                    { value: 'imsg', label: 'imsg (native)' },
                    { value: 'bluebubbles', label: 'BlueBubbles' },
                  ]}
                />
              }
            />
            {provider === 'bluebubbles' && (
              <SettingsRow
                label="BlueBubbles endpoint"
                description="The BlueBubbles server URL."
                control={
                  <Input
                    value={endpointUrl}
                    onChange={(e) => setEndpointUrl(e.target.value)}
                    placeholder="https://bluebubbles.example"
                    aria-label="BlueBubbles endpoint"
                  />
                }
              />
            )}
          </>
        )}

        {/* ── Token input ── */}
        <SettingsRow
          label={adapter === 'telegram' ? 'Bot token' : 'iMessage credential'}
          description={adapter === 'telegram' ? 'The token from @BotFather. Write-only — stored in your OS credential vault, never returned by the API.' : 'Write-only provider credential. Stored in your OS credential vault, never returned by the API.'}
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
            Connect
          </Button>
        </div>
      </SettingsGroup>

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
          label={connection.adapter === 'telegram' ? 'Bot' : 'Provider'}
          description={
            connection.adapter === 'telegram'
              ? `@${connection.adapter_username || 'unknown'} (${connection.adapter})`
              : `${connection.provider ?? 'imsg'} (${connection.adapter})`
          }
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
          label="Capabilities"
          description={
            connection.status.capabilities.length > 0
              ? connection.status.capabilities.join(', ')
              : 'Provider capabilities are not available yet.'
          }
          control={<span className="text-xs text-muted-foreground">{connection.provider ?? connection.adapter}</span>}
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
        <PairingSection
          connectionId={connection.id}
          adapter={connection.adapter}
          state={state}
        />
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

/**
 * Per-adapter "ready to pair" state.
 *
 * Telegram's bot reaches `polling` (long-poll `getUpdates` healthy)
 * independently of pairing — its `/start <token>` deep link is authorized
 * by anyone holding the token, not by sender identity, so the channel can
 * poll before anyone has linked. iMessage's channel is bound to one fixed
 * contact and cannot resolve who that is until pairing happens, so it
 * reports the distinct `pairing` state instead: the poller is already
 * running in discovery mode (see `app/remote/imessage/inbound.py`), ready
 * to recognize a `/pair <code>` attempt from any sender, but not yet
 * `polling` a specific contact.
 */
function readyStateFor(adapter: string): RemoteConnectionState {
  return adapter === 'imessage' ? 'pairing' : 'polling'
}

function PairingSection({
  connectionId,
  adapter,
  state,
}: {
  connectionId: string
  adapter: string
  state: RemoteConnectionState
}) {
  const pairingQ = usePairingQuery(connectionId)
  const readyState = readyStateFor(adapter)
  const isReady = state === readyState

  return (
    <SettingsGroup title="Pairing">
      {pairingQ.data ? (
        <PairedRow connectionId={connectionId} pairing={pairingQ.data} />
      ) : adapter === 'imessage' ? (
        <ImessagePairingRow connectionId={connectionId} isReady={isReady} state={state} />
      ) : (
        <TelegramPairingRow connectionId={connectionId} isReady={isReady} state={state} />
      )}
    </SettingsGroup>
  )
}

function PairedRow({
  connectionId,
  pairing,
}: {
  connectionId: string
  pairing: NonNullable<ReturnType<typeof usePairingQuery>['data']>
}) {
  const revokeMut = useRevokePairingMutation()

  async function handleRevoke() {
    await revokeMut.mutateAsync(connectionId)
  }

  return (
    <>
      <SettingsRow
        label="Paired device"
        description={`${pairing?.display || pairing?.label || 'Unknown'} — last seen ${pairing ? formatRelativeTime(pairing.last_seen_at) : 'never'}`}
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
  )
}

// ── Telegram: QR code / deep-link pairing ───────────────────────────────────

function TelegramPairingRow({
  connectionId,
  isReady,
  state,
}: {
  connectionId: string
  isReady: boolean
  state: RemoteConnectionState
}) {
  const linkMut = useIssuePairingLinkMutation()
  const [linkCopied, setLinkCopied] = useState(false)

  // Auto-issue a pairing link once the adapter reaches "pairing" or "polling" and no
  // pairing exists yet.  Uses a ref guard so the effect fires at most once
  // per connection session — avoids re-triggering on every render.
  const autoIssuedRef = useRef(false)
  useEffect(() => {
    if (isReady && !autoIssuedRef.current && !linkMut.isPending && !linkMut.data) {
      autoIssuedRef.current = true
      linkMut.mutate(connectionId)
    }
  }, [isReady, connectionId, linkMut])

  async function handleGetLink() {
    setLinkCopied(false)
    linkMut.reset()
    await linkMut.mutateAsync(connectionId)
  }

  async function handleCopyLink() {
    if (linkMut.data?.url) {
      await navigator.clipboard.writeText(linkMut.data.url)
      setLinkCopied(true)
    }
  }

  return (
    <SettingsRow
      label="Connect phone"
      description={
        isReady
          ? 'Scan the QR code with your phone camera to link Telegram — no typing needed.'
          : `Waiting for adapter to connect (current state: ${state}).`
      }
      stacked
      control={
        <div className="flex flex-col gap-4">
          {linkMut.data && (
            <div className="flex flex-col items-center gap-3 rounded-lg border border-(--color-border) bg-(--bg-key) p-4">
              <QRCodeSVG
                value={linkMut.data.url}
                size={180}
                bgColor="transparent"
                fgColor="var(--color-text)"
                level="M"
              />
              <p className="text-center text-sm text-(--color-text-muted)">
                Scan with your phone camera, or tap the link below.
              </p>
              <div className="flex w-full items-center gap-2">
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
              </p>
            </div>
          )}

          {!linkMut.data && linkMut.isPending && (
            <div className="flex items-center gap-2 rounded-lg border border-(--color-border) bg-(--bg-key) p-4 text-sm text-(--color-text-muted)">
              <Loader2 className="size-4 animate-spin" />
              Generating QR code...
            </div>
          )}

          {!linkMut.data && !linkMut.isPending && (
            <div className="flex flex-col gap-2">
              <Button
                variant="outline"
                onClick={() => void handleGetLink()}
                disabled={!isReady}
              >
                <Link2 className="mr-2 size-4" />
                Generate pairing link
              </Button>
              {linkMut.isError && (
                <p className="text-xs text-(--color-error)">
                  {linkMut.error?.message ?? 'Could not generate link.'}
                </p>
              )}
            </div>
          )}
        </div>
      }
    />
  )
}

// ── iMessage: phone-first pairing code ───────────────────────────────────────

function ImessagePairingRow({
  connectionId,
  isReady,
  state,
}: {
  connectionId: string
  isReady: boolean
  state: RemoteConnectionState
}) {
  const codeQ = usePairingCodeQuery(connectionId, isReady)
  const [codeCopied, setCodeCopied] = useState(false)

  async function handleRegenerate() {
    setCodeCopied(false)
    await codeQ.refetch()
  }

  async function handleCopyCode() {
    if (codeQ.data?.code_display) {
      await navigator.clipboard.writeText(codeQ.data.code_display.replace(/\s/g, ''))
      setCodeCopied(true)
    }
  }

  return (
    <SettingsRow
      label="Connect phone"
      description={
        isReady
          ? 'From the phone you want to pair, send this code as an iMessage to this Mac: "/pair <code>".'
          : `Waiting for the iMessage adapter to be ready (current state: ${state}).`
      }
      stacked
      control={
        <div className="flex flex-col gap-4">
          {codeQ.data && (
            <div className="flex flex-col items-center gap-3 rounded-lg border border-(--color-border) bg-(--bg-key) p-4">
              <div className="flex items-center gap-2">
                <span className="font-mono text-2xl tracking-widest text-(--color-text)">
                  {codeQ.data.code_display}
                </span>
                <Button
                  size="icon-xs"
                  variant="ghost"
                  onClick={() => void handleCopyCode()}
                  aria-label="Copy code"
                >
                  {codeCopied ? (
                    <CheckCircle2 size={14} className="text-(--color-success)" />
                  ) : (
                    <Copy size={14} />
                  )}
                </Button>
              </div>
              <p className="text-center text-sm text-(--color-text-muted)">
                From your phone, send an iMessage to this Mac's iMessage
                address:{' '}
                <code className="rounded bg-(--color-surface-raised) px-1 py-0.5 font-mono text-xs">
                  /pair {codeQ.data.code_display}
                </code>
              </p>
              <div className="flex items-center gap-3">
                <p className="text-xs text-(--color-text-muted)">
                  Code expires {formatRelativeTime(codeQ.data.expires_at)}.
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void handleRegenerate()}
                  disabled={codeQ.isFetching}
                >
                  {codeQ.isFetching ? (
                    <Loader2 className="mr-1.5 size-3.5 animate-spin" />
                  ) : (
                    <Link2 className="mr-1.5 size-3.5" />
                  )}
                  New code
                </Button>
              </div>
            </div>
          )}

          {!codeQ.data && codeQ.isFetching && (
            <div className="flex items-center gap-2 rounded-lg border border-(--color-border) bg-(--bg-key) p-4 text-sm text-(--color-text-muted)">
              <Loader2 className="size-4 animate-spin" />
              Generating pairing code...
            </div>
          )}

          {!codeQ.data && !codeQ.isFetching && (
            <div className="flex flex-col gap-2">
              <Button
                variant="outline"
                onClick={() => void handleRegenerate()}
                disabled={!isReady}
              >
                <Link2 className="mr-2 size-4" />
                Generate pairing code
              </Button>
              {codeQ.isError && (
                <p className="text-xs text-(--color-error)">
                  {codeQ.error instanceof Error
                    ? codeQ.error.message
                    : 'Could not generate code.'}
                </p>
              )}
            </div>
          )}
        </div>
      }
    />
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
    const absDiffMs = Math.abs(diffMs)
    const future = diffMs < 0

    if (absDiffMs < 60_000) return future ? 'in <1m' : 'just now'

    const diffMin = Math.floor(absDiffMs / 60_000)
    if (diffMin < 60) return future ? `in ${diffMin}m` : `${diffMin}m ago`
    const diffH = Math.floor(diffMin / 60)
    if (diffH < 24) return future ? `in ${diffH}h` : `${diffH}h ago`
    const diffD = Math.floor(diffH / 24)
    return future ? `in ${diffD}d` : `${diffD}d ago`
  } catch {
    return iso
  }
}
