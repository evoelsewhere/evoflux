/**
 * /settings/connection — Backend connection settings page.
 *
 * Displays the same backend connection UI that was previously in AppBackendDialog,
 * but rendered inline as a settings sub-page.
 */
import { useEffect, useState } from 'react'
import { AlertCircle, Pencil, Server, Trash2 } from 'lucide-react'

import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { apiBaseUrl, setApiBaseUrl } from '@/api/base-url'
import { queryClient } from '@/lib/query-client'
import { queryKeys } from '@/queries/keys'
import { getAccessKey, setAccessKey } from '@/api/auth'
import {
  getAppBackendStatus,
  removeAppBackendServer,
  saveAppBackendServer,
  switchToExternalAppBackend,
  switchToBundledAppBackend,
  type SavedAppServer,
  type AppBackendStatus,
} from '@/lib/app-backend'

const DEFAULT_SERVERS: SavedAppServer[] = [{ base_url: 'http://127.0.0.1:4082', name: 'Local CLI server' }]

export function BackendConnectionPage() {
  const [status, setStatus] = useState<AppBackendStatus | null>(null)
  const [baseUrl, setBaseUrl] = useState('')
  const [serverName, setServerName] = useState('')
  const [accessKey, setAccessKeyInput] = useState('')
  const [rememberServer, setRememberServer] = useState(true)
  const [serverHealth, setServerHealth] = useState<Record<string, 'checking' | 'online' | 'offline'>>({})
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void getAppBackendStatus().then((next) => {
      if (cancelled) return
      setStatus(next)
      setBaseUrl('')
      setServerName('')
      setAccessKeyInput('')
      setRememberServer(true)
      const servers = next?.servers ?? DEFAULT_SERVERS
      setServerHealth(Object.fromEntries(servers.map((server) => [normalizeServerBaseUrl(server.base_url), 'checking'])))
      for (const server of servers) {
        const normalized = normalizeServerBaseUrl(server.base_url)
        void pingServer(normalized).then((online) => {
          if (cancelled) return
          setServerHealth((prev) => ({ ...prev, [normalized]: online ? 'online' : 'offline' }))
        })
      }
    })
    return () => { cancelled = true }
  }, [])

  async function checkExternal(nextBaseUrl = baseUrl, nextName = serverName, persist = rememberServer) {
    const target = normalizeServerBaseUrl(nextBaseUrl)
    const validationError = validateServerUrl(target)
    if (validationError) {
      setError(validationError)
      return
    }
    setPending(true)
    setError(null)
    try {
      const online = await pingServer(target)
      setServerHealth((prev) => ({ ...prev, [target]: online ? 'online' : 'offline' }))
      if (!online) {
        setError(connectionFailureMessage(target))
        return
      }
      const keyForConnect = accessKey.trim() || getAccessKey() || ''
      const authorized = await checkServerAuth(target, keyForConnect)
      if (!authorized) {
        setError('Server is reachable, but the access key is invalid or missing.')
        return
      }
      if (accessKey.trim()) setAccessKey(accessKey)
      const next = await switchToExternalAppBackend(target, nextName, persist)
      setApiBaseUrl(next.base_url)
      await refreshBackendQueries()
      setStatus(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setPending(false)
    }
  }

  async function connectBundled() {
    await runConnectionSwitch(() => switchToBundledAppBackend())
  }

  async function saveServer() {
    const target = normalizeServerBaseUrl(baseUrl)
    const validationError = validateServerUrl(target)
    if (validationError) {
      setError(validationError)
      return
    }
    setPending(true)
    setError(null)
    try {
      const next = await saveAppBackendServer(target, serverName)
      setStatus(next)
      setBaseUrl('')
      setServerName('')
      setServerHealth((prev) => ({ ...prev, [target]: 'checking' }))
      const online = await pingServer(target)
      setServerHealth((prev) => ({ ...prev, [target]: online ? 'online' : 'offline' }))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setPending(false)
    }
  }

  async function removeServer(url: string) {
    setPending(true)
    setError(null)
    try {
      const next = await removeAppBackendServer(url)
      if (next.base_url) setApiBaseUrl(next.base_url)
      await refreshBackendQueries()
      setStatus(next)
      setServerHealth((prev) => {
        const { [url]: _removed, ...rest } = prev
        return rest
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setPending(false)
    }
  }

  async function runConnectionSwitch(action: () => Promise<void>) {
    setPending(true)
    setError(null)
    try {
      await action()
      const next = await getAppBackendStatus()
      if (next?.base_url) {
        setApiBaseUrl(next.base_url)
      }
      await refreshBackendQueries()
      setStatus(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setPending(false)
    }
  }

  const connectedUrl = status?.base_url || apiBaseUrl().replace(/\/api$/, '')
  const usingExternal = status?.mode === 'external' || status?.external

  return (
    <SettingsPage
      icon={Server}
      title="Connection"
      lede="Run against the sidecar bundled with this app, or point it at an EvoFlux server you host. Saved servers reconnect automatically after a reload."
    >
      <SettingsGroup title="Current backend">
        <SettingsRow
          label={<span className="font-mono text-sm break-all">{connectedUrl}</span>}
          description={usingExternal ? 'Connected to a saved server.' : 'Connected to the builtin sidecar.'}
          control={
            <span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-[11px] text-(--color-text-muted)">
              {usingExternal ? 'saved server' : 'builtin'}
            </span>
          }
        />
      </SettingsGroup>

      <SettingsGroup
        title="Available backends"
        description="Connect switches this app over after verifying the server responds."
      >
        {status?.supports_bundled !== false && (
          <div className="flex items-center gap-3 px-4 py-3">
            <ServerStatusDot status={status?.sidecar_running ? 'online' : undefined} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-(--color-text)">Builtin sidecar</p>
              <p className="text-xs text-(--color-text-muted)">Ships with the desktop app.</p>
            </div>
            {!status?.external ? (
              <span className="shrink-0 rounded-full bg-(--bg-key) px-2 py-0.5 text-[11px] text-(--color-text-muted)">
                active
              </span>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  void connectBundled()
                }}
                disabled={pending}
              >
                Use builtin
              </Button>
            )}
          </div>
        )}

        {(status?.servers ?? DEFAULT_SERVERS).map((server) => {
          const normalizedServerUrl = normalizeServerBaseUrl(server.base_url)
          const active =
            status?.mode === 'external' && normalizeServerBaseUrl(status.base_url) === normalizedServerUrl
          const loadIntoForm = () => {
            setBaseUrl(normalizedServerUrl)
            setServerName(server.name ?? '')
          }
          return (
            <div key={server.base_url} className="flex items-center gap-3 px-4 py-3">
              <ServerStatusDot status={serverHealth[normalizedServerUrl] ?? serverHealth[server.base_url]} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-(--color-text)">{server.name || server.base_url}</p>
                {server.name && (
                  <p className="truncate font-mono text-xs text-(--color-text-muted)">{server.base_url}</p>
                )}
              </div>
              {active && (
                <span className="shrink-0 rounded-full bg-(--bg-key) px-2 py-0.5 text-[11px] text-(--color-text-muted)">
                  active
                </span>
              )}
              <div className="flex shrink-0 items-center gap-1">
                {!active && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      void checkExternal(normalizedServerUrl, server.name ?? '', true)
                    }}
                    disabled={pending}
                  >
                    Connect
                  </Button>
                )}
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={loadIntoForm}
                  disabled={pending}
                  aria-label={`Edit ${server.name || server.base_url}`}
                >
                  <Pencil size={13} />
                </Button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => {
                    void removeServer(server.base_url)
                  }}
                  disabled={pending}
                  aria-label={`Remove ${server.name || server.base_url}`}
                  className="text-(--color-error) hover:bg-(--color-error)/10"
                >
                  <Trash2 size={13} />
                </Button>
              </div>
            </div>
          )
        })}
      </SettingsGroup>

      <SettingsGroup
        title="Add or edit a server"
        description="Save stores or renames an entry without switching to it."
      >
        <SettingsRow
          label="Server URL"
          description="Include the scheme and port, for example http://192.168.1.20:4082."
          htmlFor="settings-backend-url"
          stacked
          control={
            <div className="flex gap-2">
              <Input
                id="settings-backend-url"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="http://<backend-host>:4082"
                className="min-w-0 flex-1 font-mono text-sm"
              />
              <Button
                size="sm"
                className="shrink-0"
                onClick={() => void checkExternal()}
                disabled={pending}
              >
                {pending ? 'Connecting…' : 'Connect'}
              </Button>
            </div>
          }
        />

        <SettingsRow
          label="Remember this server"
          description="Keep it in the list above and reconnect after a reload."
          control={
            <Switch
              checked={rememberServer}
              onCheckedChange={setRememberServer}
              disabled={pending}
              aria-label="Remember this server"
            />
          }
        />

        <SettingsRow
          label="Access key"
          description="Required when the server was started with --key."
          htmlFor="settings-backend-key"
          stacked
          control={
            <Input
              id="settings-backend-key"
              value={accessKey}
              onChange={(event) => setAccessKeyInput(event.target.value)}
              placeholder="Paste the server access key"
              type="password"
              className="w-full text-sm"
            />
          }
        />

        <SettingsRow
          label="Display name"
          description="Only used to label the entry in the list."
          htmlFor="settings-backend-name"
          stacked
          control={
            <div className="flex gap-2">
              <Input
                id="settings-backend-name"
                value={serverName}
                onChange={(event) => setServerName(event.target.value)}
                placeholder="Work laptop, Home server, Local CLI"
                className="min-w-0 flex-1 text-sm"
              />
              <Button
                size="sm"
                variant="outline"
                className="shrink-0"
                onClick={() => void saveServer()}
                disabled={pending}
              >
                Save server
              </Button>
            </div>
          }
        />
      </SettingsGroup>

      {error && (
        <SettingsCallout tone="error" icon={AlertCircle}>
          {error}
        </SettingsCallout>
      )}

      <p className="text-xs leading-relaxed text-(--color-text-muted)">
        If a server on your network refuses to connect, check that the backend is not bound to localhost
        only, and that the firewall and local-network permissions allow access.
      </p>
    </SettingsPage>
  )
}

async function refreshBackendQueries(): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: queryKeys.health() })
  await queryClient.invalidateQueries({ queryKey: queryKeys.team.status() })
}

function normalizeServerBaseUrl(value: string): string {
  const trimmed = value.trim().replace(/\/+$/, '')
  return trimmed.endsWith('/api') ? trimmed.slice(0, -4) : trimmed
}

function validateServerUrl(value: string): string | null {
  if (!value) return 'Enter a server URL first.'
  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    return 'Enter a full server URL, including http:// or https://.'
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return `Unsupported URL scheme: ${parsed.protocol.replace(/:$/, '')}`
  }
  return null
}

function connectionFailureMessage(baseUrl: string): string {
  try {
    const host = new URL(baseUrl).hostname
    if (host === 'localhost' || host === '127.0.0.1' || host === '::1' || host === '[::1]') {
      return 'Server did not respond to /api/health/live. Make sure EvoFlux is running locally and the port is correct.'
    }
  } catch {
    // validateServerUrl already handles malformed URLs.
  }
  return 'Server did not respond to /api/health/live. Check that EvoFlux is running with --host 0.0.0.0, this device is on the same network, and the URL uses the backend machine LAN IP.'
}

async function checkServerAuth(baseUrl: string, accessKey: string): Promise<boolean> {
  const base = baseUrl.replace(/\/+$/, '')
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 1500)
  try {
    const headers = accessKey ? { Authorization: `Bearer ${accessKey}` } : undefined
    const res = await fetch(`${base}/api/auth/check`, { cache: 'no-store', headers, signal: controller.signal })
    return res.ok || res.status === 404
  } catch {
    return false
  } finally {
    window.clearTimeout(timeout)
  }
}

async function pingServer(baseUrl: string): Promise<boolean> {
  const base = baseUrl.replace(/\/+$/, '')
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 1500)
  try {
    const res = await fetch(`${base}/api/health/live`, { cache: 'no-store', signal: controller.signal })
    return res.ok
  } catch {
    return false
  } finally {
    window.clearTimeout(timeout)
  }
}

function ServerStatusDot({ status }: { status: 'checking' | 'online' | 'offline' | undefined }) {
  const className = status === 'online'
    ? 'bg-(--color-success)'
    : status === 'offline'
      ? 'bg-(--color-error)'
      : 'animate-pulse bg-(--color-text-muted)'
  const label = status === 'online' ? 'Online' : status === 'offline' ? 'Offline' : 'Checking'
  return (
    <span
      role="img"
      className={`size-2 shrink-0 rounded-full ${className}`}
      title={label}
      aria-label={label}
    />
  )
}
