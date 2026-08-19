import { useMemo } from 'react'
import {
  AlertTriangle,
  Braces,
  CheckCircle2,
  CircleDashed,
  Download,
  Loader2,
  RefreshCw,
  ServerCog,
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
  useInstallLanguageServerMutation,
  useLanguageServersQuery,
} from '@/queries'
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

function LanguageServerRow({
  server,
  installing,
  onInstall,
}: {
  server: LanguageServerStatus
  installing: boolean
  onInstall: (server: LanguageServerStatus) => void
}) {
  const canInstall =
    server.installable
    && server.installer_available
    && server.state !== 'ready'
  const repositories = server.repositories.map((item) => item.name).join(', ')
  const version = server.source === 'managed'
    ? server.installed_version
    : server.state === 'missing'
      ? server.expected_version
      : null

  return (
    <div className={cn('flex items-start gap-3 px-4 py-4 sm:px-5', server.detected && server.state === 'missing' && 'bg-(--color-warning)/4')}>
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
      {canInstall && (
        <Button
          size="sm"
          variant={server.detected ? 'default' : 'outline'}
          disabled={installing}
          onClick={() => onInstall(server)}
          className="shrink-0"
        >
          {installing ? (
            <Loader2 size={13} className="animate-spin" aria-hidden="true" />
          ) : server.state === 'update_available' ? (
            <RefreshCw size={13} aria-hidden="true" />
          ) : (
            <Download size={13} aria-hidden="true" />
          )}
          {installing
            ? 'Installing…'
            : server.state === 'update_available'
              ? 'Update'
              : 'Install'}
        </Button>
      )}
    </div>
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
  const installingLanguage = installMutation.isPending ? installMutation.variables : null

  const install = (server: LanguageServerStatus) => {
    const action = server.state === 'update_available' ? 'Update' : 'Install'
    const confirmed = window.confirm(
      `${action} ${server.display_name} language server v${server.expected_version ?? 'pinned'} with ${server.installer ?? 'the configured installer'}?\n\n${server.install_hint}\nIt will be stored in the EvoFlux cache and shared across repositories.`,
    )
    if (!confirmed) return
    installMutation.mutate(server.language_id)
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
      icon={ServerCog}
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
                  : 'Language server installation failed.'}
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
                  installing={installingLanguage === server.language_id}
                  onInstall={install}
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
                    installing={installingLanguage === server.language_id}
                    onInstall={install}
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
                  installing={installingLanguage === server.language_id}
                  onInstall={install}
                />
              ))}
            </SettingsGroup>
          </>
        )}
      </SettingsAsyncBoundary>
    </SettingsPage>
  )
}
