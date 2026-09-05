import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Braces,
  CheckCircle2,
  CircleDashed,
  Download,
  Loader2,
  Blocks,
  RefreshCw,
  X,
} from 'lucide-react'

import type { LanguageServerStatus } from '@/api/types'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
} from '@/components/settings/SettingsLayout'
import { Button } from '@/components/ui/button'
import {
  useDismissLanguageServerErrorMutation,
  useInstallLanguageServerMutation,
  useLanguageServersQuery,
} from '@/queries'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useConfirm } from '@/hooks/use-confirm'
import { useCodingOverviewQuery } from '@/queries/useProjectsQuery'
import { useTeamStore } from '@/stores/useTeamStore'
import { cn } from '@/lib/utils'
import { useSettingsSearch } from '@/contexts/SettingsContext'

function ServerState({ server }: { server: LanguageServerStatus }) {
  if (server.state === 'ready') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-(--color-success)/10 px-2 py-0.5 text-[10px] font-medium text-(--color-success)">
        <CheckCircle2 size={10} aria-hidden="true" />
        {server.source === 'managed' ? 'Managed' : 'On PATH'}
      </span>
    )
  }
  if (server.state === 'update_available') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-(--color-warning)/10 px-2 py-0.5 text-[10px] font-medium text-(--color-warning)">
        <RefreshCw size={10} aria-hidden="true" /> Update available
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-(--bg-key) px-2 py-0.5 text-[10px] font-medium text-(--color-text-muted)">
      <CircleDashed size={10} aria-hidden="true" /> Missing
    </span>
  )
}

/**
 * One language's row, including why its action cannot be taken.
 *
 * The action used to be hidden whenever it was unavailable, which made three
 * different situations look identical: no managed installer exists, the
 * installer exists but its prerequisite is missing, and the server is already
 * installed. "Install does nothing" was usually "there was never a button".
 */
function LanguageServerRow({
  server,
  onInstall,
  onDismissError,
}: {
  server: LanguageServerStatus
  onInstall: (server: LanguageServerStatus) => void
  onDismissError: (server: LanguageServerStatus) => void
}) {
  const running = server.install_phase === 'running'
  const canInstall = server.installable && server.blocked_reason === null && !running
  const repositories = server.repositories.map((item) => item.name).join(', ')
  const version = server.source === 'managed'
    ? server.installed_version
    : server.state === 'missing'
      ? server.expected_version
      : null

  return (
    <div
      className={cn(
        'flex flex-col gap-2 px-4 py-4 sm:px-5',
        server.detected && server.state === 'missing' && 'bg-(--color-warning)/4',
        server.install_phase === 'failed' && 'bg-(--color-error)/5',
      )}
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-(--bg-key) text-(--color-text-muted)">
          <Braces size={14} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-(--color-text)">{server.display_name}</p>
            <ServerState server={server} />
            {version && (
              <span className="font-mono text-[10px] text-(--color-text-subtle)">v{version}</span>
            )}
            {server.installer && (
              <span className="rounded-full bg-(--bg-key) px-2 py-0.5 font-mono text-[10px] text-(--color-text-subtle)">
                {server.installer}
              </span>
            )}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-(--color-text-muted)">
            {server.detected
              ? `${server.file_count} matching ${server.file_count === 1 ? 'file' : 'files'}${repositories ? ` across ${repositories}` : ''}.`
              : 'Not detected in the active repository set.'}
            {' '}{server.install_hint}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-(--color-text-subtle)">
            <span>{server.extensions.slice(0, 8).join(' ')}</span>
            {server.command && (
              <span className="max-w-full truncate font-mono" title={server.command}>
                {server.command}
              </span>
            )}
          </div>
        </div>

        {server.installable && (
          <div className="flex shrink-0 flex-col items-end gap-1">
            <Button
              size="sm"
              variant={server.detected ? 'default' : 'outline'}
              disabled={!canInstall}
              title={server.blocked_reason ?? undefined}
              onClick={() => onInstall(server)}
              aria-label={
                server.blocked_reason
                  ? `${server.display_name}: ${server.blocked_reason}`
                  : `Install ${server.display_name} language server`
              }
            >
              {running ? (
                <Loader2 size={13} className="animate-spin" aria-hidden="true" />
              ) : server.state === 'update_available' ? (
                <RefreshCw size={13} aria-hidden="true" />
              ) : (
                <Download size={13} aria-hidden="true" />
              )}
              {running
                ? 'Installing…'
                : server.state === 'update_available'
                  ? 'Update'
                  : 'Install'}
            </Button>
            {running && server.install_started_at && (
              <InstallElapsed startedAt={server.install_started_at} />
            )}
          </div>
        )}
      </div>

      {/* A blocked action explains itself where the button is, not in a
          paragraph of grey prose above it. */}
      {server.blocked_reason && server.state !== 'ready' && !running && (
        <p className="pl-11 text-[11px] text-(--color-text-subtle)">
          {server.blocked_reason}
        </p>
      )}

      {server.install_error && (
        <div className="ml-11 flex items-start gap-2 rounded-md border border-(--color-error)/40 bg-(--color-error)/8 px-3 py-2">
          <AlertTriangle size={12} className="mt-0.5 shrink-0 text-(--color-error)" aria-hidden="true" />
          <p className="min-w-0 flex-1 text-[11px] leading-relaxed break-words text-(--color-error)">
            {server.install_error}
          </p>
          <button
            type="button"
            onClick={() => onDismissError(server)}
            aria-label={`Dismiss ${server.display_name} install error`}
            className="shrink-0 rounded p-0.5 text-(--color-error)/70 hover:text-(--color-error)"
          >
            <X size={12} aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  )
}

/** How long the running install has been going, so it never looks stuck. */
function InstallElapsed({ startedAt }: { startedAt: string }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [])
  const seconds = Math.max(0, Math.round((now - new Date(startedAt).getTime()) / 1000))
  return (
    <span className="font-mono text-[10px] text-(--color-text-subtle)">
      {seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`}
    </span>
  )
}

export function LanguageServersSettingsPage() {
  const settingsSearch = useSettingsSearch()
  const storeWorkspace = useTeamStore((state) => state._workspace)
  const activeWorkspace = storeWorkspace ?? settingsSearch.workspace ?? null
  const projectId = useTeamStore((state) => state.projectId)
  const projectsQuery = useCodingOverviewQuery()
  const workspaces = useMemo(() => {
    if (projectId) {
      const project = projectsQuery.data?.projects.find((item) => item.id === projectId)
      if (project) return project.workspaces.map((item) => item.path)
    }
    return activeWorkspace ? [activeWorkspace] : []
  }, [activeWorkspace, projectId, projectsQuery.data?.projects])
  const statusQuery = useLanguageServersQuery(workspaces)
  const installMutation = useInstallLanguageServerMutation(workspaces)
  const dismissMutation = useDismissLanguageServerErrorMutation(workspaces)
  const { request, confirm, close } = useConfirm()

  const install = (server: LanguageServerStatus) => {
    const action = server.state === 'update_available' ? 'Update' : 'Install'
    const version = server.expected_version ? ` v${server.expected_version}` : ' the pinned version'
    confirm({
      title: `${action} ${server.display_name} language server?`,
      description:
        `EvoFlux runs ${server.installer ?? 'the configured installer'} to install`
        + `${version}. ${server.install_hint}`,
      confirmLabel: action,
      onConfirm: () => {
        close()
        installMutation.mutate(server.language_id)
      },
    })
  }

  const detected = statusQuery.data?.servers.filter((server) => server.detected) ?? []
  const installedElsewhere = statusQuery.data?.servers.filter(
    (server) => !server.detected && server.source !== 'missing',
  ) ?? []
  const other = statusQuery.data?.servers.filter(
    (server) => !server.detected && server.source === 'missing',
  ) ?? []
  const readyCount = detected.filter((server) => server.state === 'ready').length

  return (
    <SettingsPage
      icon={Blocks}
      title="Language servers"
      lede="Detect semantic engines across the active project, install pinned servers with confirmation, and reuse one managed cache across repositories."
      size="wide"
      actions={
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void statusQuery.refetch()}
          disabled={statusQuery.isFetching || installMutation.isPending}
        >
          <RefreshCw
            size={13}
            className={statusQuery.isFetching ? 'animate-spin' : undefined}
            aria-hidden="true"
          />
          Refresh
        </Button>
      }
    >
      <SettingsAsyncBoundary
        loading={statusQuery.isLoading}
        hasData={Boolean(statusQuery.data)}
        error={statusQuery.error}
        variant="list"
        loadingLabel="Detecting repository languages"
        errorTitle="Could not inspect language servers"
        onRetry={() => void statusQuery.refetch()}
      >
        {statusQuery.data && (
          <>
            {workspaces.length === 0 ? (
              <SettingsCallout icon={AlertTriangle} tone="warning">
                Open a Coding workspace or project to detect its languages. Installed and supported servers are still listed below.
              </SettingsCallout>
            ) : (
              <SettingsCallout icon={CheckCircle2} tone={readyCount === detected.length ? 'success' : 'warning'}>
                <span className="font-medium">{readyCount} of {detected.length} detected language servers ready.</span>
                <span className="text-(--color-text-muted)"> Scanned {workspaces.length} {workspaces.length === 1 ? 'repository' : 'repositories'}; no server was installed automatically.</span>
              </SettingsCallout>
            )}

            {installMutation.error && (
              <SettingsCallout icon={AlertTriangle} tone="error">
                {installMutation.error instanceof Error
                  ? installMutation.error.message
                  : 'Could not start the installation.'}
              </SettingsCallout>
            )}

            {statusQuery.data.scan_truncated && (
              <SettingsCallout icon={AlertTriangle} tone="warning">
                <span className="font-medium">Detection stopped early.</span>
                <span className="text-(--color-text-muted)">
                  {' '}More than {statusQuery.data.scan_limit.toLocaleString()} files were
                  walked, so languages further down the tree may be missing from the list
                  below. Everything remains installable by hand.
                </span>
              </SettingsCallout>
            )}

            <SettingsGroup
              title="Detected languages"
              description={detected.length
                ? 'Each repository keeps its own LSP process; managed binaries are shared.'
                : 'No supported source files were detected in the active repository set.'}
            >
              {detected.length ? detected.map((server) => (
                <LanguageServerRow
                  key={server.language_id}
                  server={server}
                  onInstall={install}
                  onDismissError={(item) => dismissMutation.mutate(item.language_id)}
                />
              )) : (
                <div className="px-5 py-8 text-center text-sm text-(--color-text-muted)">
                  No detected languages
                </div>
              )}
            </SettingsGroup>

            {installedElsewhere.length > 0 && (
              <SettingsGroup title="Installed for other repositories">
                {installedElsewhere.map((server) => (
                  <LanguageServerRow
                    key={server.language_id}
                    server={server}
                    onInstall={install}
                    onDismissError={(item) => dismissMutation.mutate(item.language_id)}
                  />
                ))}
              </SettingsGroup>
            )}

            <SettingsGroup
              title="Other supported languages"
              description={`Managed cache: ${statusQuery.data.cache_dir}`}
            >
              {other.map((server) => (
                <LanguageServerRow
                  key={server.language_id}
                  server={server}
                  onInstall={install}
                  onDismissError={(item) => dismissMutation.mutate(item.language_id)}
                />
              ))}
            </SettingsGroup>
          </>
        )}
      </SettingsAsyncBoundary>
      <ConfirmDialog request={request} onClose={close} />
    </SettingsPage>
  )
}
