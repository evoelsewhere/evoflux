import { useMemo, useState } from 'react'
import { AlertCircle, Plug, RotateCw, Trash2 } from 'lucide-react'

import {
  useConnectMcpOAuthMutation,
  useDeleteMcpServerMutation,
  useMcpServerQuery,
  useRestartMcpServerMutation,
  useUpdateMcpServerMutation,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { ApiValidationError } from '@/api/client'
import { EditorHeaderActions } from '@/components/settings/EditorHeaderActions'
import { McpServerForm } from '@/components/settings/McpServerForm'
import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import {
  draftEquals,
  draftFromServerBody,
  draftToServerBody,
  validateDraft,
  type McpServerDraft,
} from '@/components/settings/McpServerDraft'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useSettingsParams, useSettingsNavigate } from '@/contexts/SettingsContext'
import { useRegisterSettingsDirty } from '@/lib/settings-dirty'
import { getIntlLocale } from '@/i18n'

/**
 * MCP server detail / editor page.
 *
 * Layout mirrors the agent / skill editors:
 *   • `SettingsPage` frame with `EditorHeaderActions` (Save + dirty/invalid status)
 *   • grouped body using the shared settings primitives
 *
 * The body shows:
 *   1. live status (state, started_at, tools, error) — read-only
 *   2. the editable `McpServerForm` for the saved configuration
 *   3. a Restart action at the bottom (it's a runtime concern, not a save)
 */
export function McpServerDetailPage() {
  const { name } = useSettingsParams()
  const navigate = useSettingsNavigate()
  const push = useToastStore((s) => s.push)
  const serverQ = useMcpServerQuery(name)
  const updateMut = useUpdateMcpServerMutation()
  const deleteMut = useDeleteMcpServerMutation()
  const restartMut = useRestartMcpServerMutation()
  const connectOAuthMut = useConnectMcpOAuthMutation()

  // Seed the editable draft from the saved config payload. We re-seed
  // exactly once per server load (tracking the `name` + version of the
  // config object) so user edits aren't blown away by background refetches.
  const seedDraft = useMemo<McpServerDraft | null>(() => {
    if (serverQ.data?.name !== name) return null
    const cfg = serverQ.data?.config
    if (!cfg) return null
    return draftFromServerBody(name, cfg)
  }, [name, serverQ.data?.config, serverQ.data?.name])

  const [draft, setDraft] = useState<McpServerDraft | null>(seedDraft)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)

  // Adopt the seed once the query lands. Subsequent edits keep `draft`.
  const [seededFor, setSeededFor] = useState<string | null>(null)
  if (seedDraft && seededFor !== name) {
    setSeededFor(name)
    setDraft(seedDraft)
    setSaveError(null)
  }

  const dirty = !!seedDraft && !!draft && !draftEquals(draft, seedDraft)
  useRegisterSettingsDirty(dirty)
  const fieldErrors = draft ? validateDraft(draft, { isNew: false }) : null
  const invalid = fieldErrors !== null
  const firstError = fieldErrors ? Object.values(fieldErrors)[0] : null

  const handleSave = async () => {
    if (!draft) return
    setSaveError(null)
    if (invalid) {
      setSaveError(firstError ?? 'Form has validation errors.')
      return
    }
    const result = draftToServerBody(draft)
    if (!result.ok) {
      setSaveError(result.error)
      return
    }
    try {
      await updateMut.mutateAsync({ name, server: result.body })
      push({
        tone: 'success',
        title: `Saved "${name}"`,
        description: 'Available on next turn.',
      })
    } catch (err) {
      const msg = err instanceof ApiValidationError ? err.message : String(err)
      setSaveError(msg)
      push({ tone: 'error', title: 'Save failed', description: msg })
    }
  }

  const handleDelete = async () => {
    try {
      await deleteMut.mutateAsync(name)
      push({ tone: 'success', title: `Deleted "${name}"` })
      navigate('/settings/mcp')
    } catch (err) {
      const msg = err instanceof ApiValidationError ? err.message : String(err)
      push({ tone: 'error', title: 'Delete failed', description: msg })
    }
  }

  const handleRestart = async () => {
    try {
      await restartMut.mutateAsync(name)
      push({ tone: 'success', title: `Restarted "${name}"` })
    } catch (err) {
      const msg = err instanceof ApiValidationError ? err.message : String(err)
      push({ tone: 'error', title: `Failed to restart "${name}"`, description: msg })
    }
  }

  const handleConnectOAuth = async () => {
    try {
      await connectOAuthMut.mutateAsync(name)
      push({ tone: 'success', title: `Connected OAuth for "${name}"` })
    } catch (err) {
      const msg = err instanceof ApiValidationError ? err.message : String(err)
      push({ tone: 'error', title: `OAuth connect failed for "${name}"`, description: msg })
    }
  }

  const server = serverQ.data

  return (
    <>
      <SettingsPage
        icon={Plug}
        title={name}
        lede={<span className="font-mono text-xs">.EvoFlux/config/mcp.json</span>}
        actions={
          <EditorHeaderActions
            dirty={dirty}
            invalid={invalid}
            saving={updateMut.isPending}
            error={saveError}
            validationHint={firstError}
            onSave={handleSave}
          />
        }
      >
        <SettingsAsyncBoundary
          loading={serverQ.isLoading}
          hasData={Boolean(server)}
          error={serverQ.isError ? serverQ.error : undefined}
          variant="detail"
          loadingLabel={`Loading MCP server ${name}`}
          errorTitle={`Failed to load MCP server ${name}`}
          onRetry={() => void serverQ.refetch()}
        >
          {server && (
          <>
            <StatusGroup server={server} />

            {server.state === 'error' && server.error && (
              <SettingsCallout tone="error" icon={AlertCircle}>
                <p className="font-medium">Runtime error</p>
                <p className="mt-1 font-mono break-all text-(--color-error)">{server.error}</p>
              </SettingsCallout>
            )}

            {server.state === 'auth_required' && (
              <SettingsCallout tone="warning" icon={AlertCircle}>
                <p className="font-medium">OAuth needed to connect</p>
                <p className="mt-1 text-(--color-text-muted)">
                  Connect OAuth to authorize this MCP server.
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-2.5 min-h-11 md:min-h-0"
                  onClick={handleConnectOAuth}
                  disabled={connectOAuthMut.isPending || !server.enabled}
                >
                  {connectOAuthMut.isPending ? 'Connecting…' : 'Connect OAuth'}
                </Button>
              </SettingsCallout>
            )}

            {draft ? (
              <SettingsGroup bare>
                <McpServerForm
                  value={draft}
                  onChange={setDraft}
                  isNew={false}
                  disabled={updateMut.isPending}
                  errors={fieldErrors}
                />
              </SettingsGroup>
            ) : (
              <SettingsCallout tone="info">
                No saved configuration found. The server may have been removed from{' '}
                <span className="font-mono">mcp.json</span>.
              </SettingsCallout>
            )}

            <div className="flex items-center justify-between gap-2 text-xs text-(--color-text-muted)">
              <div className="flex items-center gap-2">
                {dirty && (
                  <>
                    <Button
                      variant="ghost"
                      size="xs"
                      className="min-h-11 md:min-h-0"
                      onClick={() => seedDraft && setDraft(seedDraft)}
                    >
                      Discard changes
                    </Button>
                    <Button
                      variant="ghost"
                      size="xs"
                      className="min-h-11 md:min-h-0"
                      onClick={() => navigate('/settings/mcp', { force: true })}
                    >
                      Leave without saving
                    </Button>
                  </>
                )}
              </div>
              <Button
                variant="destructive"
                size="xs"
                className="min-h-11 md:min-h-0"
                onClick={() => setDeleteOpen(true)}
                disabled={deleteMut.isPending}
              >
                <Trash2 size={11} aria-hidden="true" />
                Delete server
              </Button>
            </div>

            <RestartGroup
              onRestart={handleRestart}
              pending={restartMut.isPending}
              enabled={server.enabled}
            />
          </>
          )}
        </SettingsAsyncBoundary>
      </SettingsPage>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete MCP server</DialogTitle>
            <DialogDescription>
              Delete `{name}` from mcp.json. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="p-3">
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteMut.isPending}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ── Status group ────────────────────────────────────────────────────────────

function StatusGroup({
  server,
}: {
  server: NonNullable<ReturnType<typeof useMcpServerQuery>['data']>
}) {
  return (
    <SettingsGroup title="Runtime status" description="Live state of the running connection.">
      <SettingsRow
        label="State"
        control={
          <span
            className={
              server.state === 'ready'
                ? 'text-sm text-(--accent-green)'
                : server.state === 'starting'
                  ? 'text-sm text-(--accent-orange)'
                  : server.state === 'auth_required'
                    ? 'text-sm text-(--accent-orange)'
                    : server.state === 'error'
                      ? 'text-sm text-(--color-error)'
                      : 'text-sm text-(--color-text-muted)'
            }
          >
            {server.state}
          </span>
        }
      />
      <SettingsRow
        label="Transport"
        control={<span className="font-mono text-sm text-(--color-text)">{server.transport}</span>}
      />
      <SettingsRow
        label="Enabled"
        control={
          <span className="text-sm text-(--color-text)">{server.enabled ? 'yes' : 'no'}</span>
        }
      />
      <SettingsRow
        label="Started"
        control={
          <span className="text-sm text-(--color-text)">
            {server.started_at ? new Date(server.started_at).toLocaleString(getIntlLocale()) : '-'}
          </span>
        }
      />

      {server.tool_names.length > 0 && (
        <SettingsRow
          label={`Tools (${server.tool_names.length})`}
          stacked
          control={
            <div className="flex flex-wrap gap-1">
              {server.tool_names.map((tool) => (
                <span
                  key={tool}
                  className="rounded-md bg-(--bg-key) px-1.5 py-0.5 font-mono text-xs text-(--color-text-muted)"
                >
                  {tool}
                </span>
              ))}
            </div>
          }
        />
      )}
    </SettingsGroup>
  )
}

// ── Restart group ───────────────────────────────────────────────────────────

function RestartGroup({
  onRestart,
  pending,
  enabled,
}: {
  onRestart: () => void
  pending: boolean
  enabled: boolean
}) {
  return (
    <SettingsGroup
      title="Connection"
      description="Restart the server process without changing its configuration."
    >
      <SettingsRow
        stacked
        control={
          <div className="space-y-2.5">
            <Button
              variant="outline"
              size="sm"
              className="min-h-11 md:min-h-0"
              onClick={onRestart}
              disabled={pending || !enabled}
              aria-label={pending ? 'Restarting' : 'Restart server'}
            >
              <RotateCw size={12} aria-hidden="true" />
              {pending ? 'Restarting…' : 'Restart'}
            </Button>
            {!enabled && (
              <p className="text-xs text-(--color-text-muted)">
                Server is disabled. Enable and save first to restart.
              </p>
            )}
          </div>
        }
      />
    </SettingsGroup>
  )
}
