import { type ReactNode, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Blocks,
  Box,
  CheckCircle2,
  ChevronDown,
  Code2,
  FileArchive,
  FolderInput,
  FolderPlus,
  KeyRound,
  Loader2,
  MoreHorizontal,
  PackagePlus,
  RefreshCw,
  Search,
  Server,
  Trash2,
} from 'lucide-react'
import {
  approveConductorResource,
  createPlugin,
  importPlugin,
  inspectPlugin,
  listPlugins,
  packPlugin,
  setPluginEnabled,
  uninstallPlugin,
  updatePluginFromPath,
  updatePluginFromUpload,
  uploadPlugin,
} from '@/api/client'
import type {
  PluginCredentialState,
  PluginInspection,
  PluginListItem,
  PluginListResponse,
  PluginMcpRuntimeStatus,
  PluginOperationResponse,
} from '@/api/types'
import { queryKeys } from '@/queries/keys'
import { usePlatform } from '@/hooks/use-platform'
import { useToastStore } from '@/stores/useToastStore'
import { Button, buttonVariants } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { PluginWorkspaceEditor } from '@/components/PluginWorkspaceEditor'
import { PluginCredentialsPanel } from '@/components/PluginCredentialsPanel'
import { PluginTrustReviewDialog } from '@/components/PluginTrustReviewDialog'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useConfirm } from '@/hooks/use-confirm'
import { ManagedResourceProviderBadge } from '@/components/settings/ManagedResourceProviderBadge'
import { ManagedResourceUpdateBanner } from '@/components/settings/ManagedResourceUpdateBanner'
import { CONDUCTOR_RESOURCE_STATE } from '@/lib/conductor-constants'

async function choosePath(options: {
  directory?: boolean
  archive?: boolean
}): Promise<string | null> {
  const { open } = await import('@tauri-apps/plugin-dialog')
  const selected = await open({
    directory: options.directory,
    multiple: false,
    filters: options.archive
      ? [{ name: 'Agent Plugin', extensions: ['evoplugin', 'zip'] }]
      : undefined,
  })
  return typeof selected === 'string' ? selected : null
}

function errorDiagnostics(inspection: PluginInspection) {
  return [
    ...inspection.diagnostics,
    ...inspection.skills.flatMap((skill) => skill.diagnostics),
    ...inspection.mcp_servers.flatMap((server) => server.diagnostics),
  ].filter((item) => item.severity === 'error')
}

/**
 * A labelled field in the create form.
 *
 * The form used to be seven bare inputs whose only label was a placeholder,
 * which is the one piece of text that disappears the moment you type into
 * it — so the moment a field had a value, nothing said what it was.
 */
function CreateField({
  id,
  label,
  optional,
  className,
  children,
}: {
  id: string
  label: string
  optional?: boolean
  className?: string
  children: ReactNode
}) {
  return (
    <div className={cn('min-w-0', className)}>
      <label
        htmlFor={id}
        className="mb-1 block text-xs font-medium text-(--color-text-2)"
      >
        {label}
        {optional && ' '}
        {optional && (
          <span className="font-normal text-(--color-text-subtle)">optional</span>
        )}
      </label>
      {children}
    </div>
  )
}

function conciseToolNames(server: PluginMcpRuntimeStatus): string {
  const generatedPrefix = `mcp_${server.runtime_name}_`
  return server.tool_names
    .map((name) => name.startsWith(generatedPrefix) ? name.slice(generatedPrefix.length) : name)
    .join(', ')
}

function PluginCard({
  item,
  servers,
  busy,
  onToggle,
  onPack,
  onDelete,
  onOpen,
  onCredentials,
  onUpdate,
}: {
  item: PluginListItem
  servers: PluginMcpRuntimeStatus[]
  busy: boolean
  onToggle: (enabled: boolean) => void
  onPack: () => void
  onDelete: () => void
  onOpen: () => void
  onCredentials: () => void
  onUpdate: () => void | Promise<void>
}) {
  const { installation, inspection } = item
  const displayName = installation.name
  const description = installation.description || 'Portable Agent Plugin'
  const [expanded, setExpanded] = useState(false)
  // A plugin's health is three separate facts, and the card used to show
  // only the first. `inspection.valid` means the *package* parses: it stays
  // true when a skill has no frontmatter or mcp.json is malformed, because
  // one broken component must not make the rest of the plugin unloadable.
  // And it says nothing about whether the servers actually came up — a
  // plugin whose only MCP server died with FileNotFoundError still
  // validated. So the card stayed green and the badge still read "Enabled";
  // you had to expand every plugin to find out anything was wrong.
  const errors = errorDiagnostics(inspection)
  const failedServers = installation.enabled
    ? servers.filter((server) => server.enabled && server.state === 'error')
    : []
  const problems: { key: string; label: string; title: string }[] = []
  if (failedServers.length > 0) {
    problems.push({
      key: 'mcp',
      label: failedServers.length === 1
        ? '1 MCP server failed'
        : `${failedServers.length} MCP servers failed`,
      title: failedServers
        .map((server) => `${server.server_name}: ${server.error ?? 'failed to start'}`)
        .join(String.fromCharCode(10)),
    })
  }
  if (errors.length > 0) {
    problems.push({
      key: 'diagnostics',
      label: errors.length === 1 ? '1 error' : `${errors.length} errors`,
      title: errors
        .map((item) => item.message)
        .join(String.fromCharCode(10)),
    })
  }
  const isValid = inspection.valid && problems.length === 0
  const skillCount = inspection.skills.filter((skill) => skill.valid).length
  const mcpCount = inspection.mcp_servers.filter((server) => server.valid).length
  const configuredCredentialCount = item.credentials.fields.filter(
    (field) => field.configured,
  ).length
  const credentialLabel = item.credentials.configured
    ? 'credentials set'
    : configuredCredentialCount > 0
      ? 'credentials incomplete'
      : 'credentials missing'
  const detailsId = `plugin-details-${installation.id}`
  const managed = installation.managed_by === 'conductor'
  const sourceLabel = installation.source_type === 'builtin'
    ? 'bundled'
    : installation.source_type === 'linked'
      ? 'dev link'
      : 'installed'
  const hasActions = item.credentials.supported
    || (!managed && (
      item.capabilities.can_edit
      || item.capabilities.can_pack
      || item.capabilities.can_update
      || item.capabilities.can_uninstall
    ))
  return (
    <article
      className={cn(
        '@container/plugin-card overflow-hidden rounded-2xl border bg-(--bg-card) shadow-sm transition-[border-color,box-shadow] hover:shadow-md',
        isValid
          ? 'border-(--color-success)/60 hover:border-(--color-success)'
          : 'border-(--color-error)/60 hover:border-(--color-error)',
      )}
    >
      <button
        type="button"
        className="group flex w-full min-w-0 items-start gap-3.5 px-4 py-3.5 text-left transition-colors hover:bg-(--bg-key)/40 @sm/plugin-card:items-center"
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={() => setExpanded((current) => !current)}
      >
        <span
          className={cn(
            'flex size-11 shrink-0 items-center justify-center rounded-xl border shadow-sm',
            'border-(--color-border) bg-(--bg-key) text-(--color-text-muted)',
          )}
          aria-hidden="true"
        >
          <Box size={21} />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h3 className="truncate text-[15px] font-semibold text-(--color-text)">
              {displayName}
            </h3>
            {installation.version && (
              <span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-[11px] font-medium text-(--color-text-muted)">
                v{installation.version}
              </span>
            )}
            {item.provider && (
              <ManagedResourceProviderBadge provider={item.provider} />
            )}
            <span className="rounded-full border border-(--color-border) px-2 py-0.5 text-[11px] font-medium text-(--color-text-muted)">
              {sourceLabel}
            </span>
          </div>

          <p className="mt-1 max-w-3xl text-sm leading-5 text-(--color-text-muted)">
            {description}
          </p>

          <span className="sr-only">
            {isValid
              ? 'Plugin is valid.'
              : inspection.valid
                ? `Plugin package is valid but needs attention: ${problems.map((problem) => problem.label).join(', ')}.`
                : `Plugin is not valid${errors.length ? `: ${errors.length} component errors` : ''}.`}
          </span>

          {/* Every state the card reports lives in this one wrapping row, so
              the right-hand column stays a fixed-width disclosure control.
              Competing for that column truncated the plugin's own name on a
              narrow card, and dropped the enabled pill entirely below 24rem
              — which is exactly where you can least afford to hide it. */}
          <div className="mt-2 flex flex-wrap gap-1.5 text-xs text-(--color-text-muted)">
            <span
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-medium',
                installation.enabled
                  ? 'bg-(--color-success-subtle) text-(--color-success)'
                  : 'bg-(--bg-key) text-(--color-text-muted)',
              )}
            >
              <span
                className={cn(
                  'size-1.5 rounded-full',
                  installation.enabled ? 'bg-(--color-success)' : 'bg-(--color-text-subtle)',
                )}
                aria-hidden="true"
              />
              {installation.enabled ? 'Enabled' : 'Disabled'}
            </span>
            {problems.map((problem) => (
              <span
                key={problem.key}
                className="inline-flex items-center gap-1 rounded-full bg-(--color-error-subtle) px-2 py-0.5 font-medium text-(--color-error)"
                title={problem.title}
              >
                <AlertTriangle size={12} aria-hidden="true" /> {problem.label}
              </span>
            ))}
            {item.credentials.supported && (
              <span className={cn(
                'inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium',
                item.credentials.configured
                  ? 'bg-(--color-success-subtle) text-(--color-success)'
                  : 'bg-(--color-warning-subtle) text-(--color-warning)',
              )}>
                <KeyRound size={12} /> {credentialLabel}
              </span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2 self-center">
          <span className="flex size-8 items-center justify-center rounded-lg text-(--color-text-muted) transition-colors group-hover:bg-(--bg-key) group-hover:text-(--color-text)">
            <ChevronDown
              size={17}
              className={cn(
                'transition-transform',
                expanded && 'rotate-180',
              )}
              aria-hidden="true"
            />
          </span>
        </div>
      </button>

      <div
        className={cn(
          'grid transition-[grid-template-rows] duration-200 ease-out',
          expanded ? 'grid-rows-[1fr] border-t border-(--color-border)' : 'grid-rows-[0fr]',
        )}
      >
        <div
          className="min-h-0 overflow-hidden"
          aria-hidden={!expanded}
          inert={!expanded}
        >
          <div
            id={detailsId}
            className="grid gap-4 p-4 @2xl/plugin-card:grid-cols-[minmax(150px,1fr)_minmax(150px,1fr)_auto]"
          >
            {item.provider
              && installation.managed_version_id === item.provider.applied_version_id && (
              <ManagedResourceUpdateBanner
                provider={item.provider}
                resourceName={installation.name}
                className="@lg/plugin-card:col-span-3"
                onPulled={async () => { await onUpdate() }}
              />
            )}
            <div className="min-w-0">
              <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-(--color-text-subtle)">
                Components
              </p>
              <div className="flex flex-wrap gap-1.5 text-xs text-(--color-text-muted)">
                <span className="inline-flex items-center gap-1 rounded-md bg-(--bg-key) px-2 py-1">
                  <Blocks size={12} /> {skillCount} skills
                </span>
                <span className="inline-flex items-center gap-1 rounded-md bg-(--bg-key) px-2 py-1">
                  <Server size={12} /> {mcpCount} MCP
                </span>
              </div>
              <p className="mt-2 break-all font-mono text-[10px] text-(--color-text-subtle)">
                {installation.root}
              </p>
            </div>

            <div className="min-w-0 border-t border-(--color-border) pt-3 @2xl/plugin-card:border-t-0 @2xl/plugin-card:border-l @2xl/plugin-card:pt-0 @2xl/plugin-card:pl-4">
              <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-(--color-text-subtle)">
                MCP runtime
              </p>
              {servers.length > 0 ? (
                <div className="space-y-3">
                  {servers.map((server) => (
                    <div key={server.runtime_name} className="min-w-0 text-xs">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={cn(
                            'h-2 w-2 rounded-full',
                            server.state === 'ready'
                              ? 'bg-(--color-success)'
                              : server.error
                                ? 'bg-(--color-error)'
                                : 'bg-(--color-text-subtle)',
                          )}
                        />
                        <span className="font-medium text-(--color-text)">{server.server_name}</span>
                        <span className="text-(--color-text-muted)">{server.state}</span>
                      </div>
                      <p className="mt-1 break-all font-mono text-[11px] text-(--color-text-subtle)">
                        runtime: {server.runtime_name}
                      </p>
                      {server.tool_names.length > 0 && (
                        <p className="mt-1 break-words text-[11px] text-(--color-text-muted)">
                          tools ({server.tool_names.length}): {conciseToolNames(server)}
                        </p>
                      )}
                      {server.error && <p className="mt-1 text-[11px] text-(--color-error)">{server.error}</p>}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-(--color-text-subtle)">No active MCP runtime</p>
              )}
            </div>

            <div className="flex content-start items-center justify-between gap-3 border-t border-(--color-border) pt-3 @2xl/plugin-card:w-36 @2xl/plugin-card:flex-col @2xl/plugin-card:items-end @2xl/plugin-card:justify-start @2xl/plugin-card:border-t-0 @2xl/plugin-card:pt-0">
              <div className="flex items-center gap-2">
                <span className="text-xs text-(--color-text-muted)">
                  {installation.enabled ? 'Enabled' : 'Disabled'}
                </span>
                <Switch
                  checked={installation.enabled}
                  disabled={busy || !item.capabilities.can_enable}
                  aria-label={item.capabilities.can_enable
                    ? `${installation.enabled ? 'Disable' : 'Enable'} ${displayName}`
                    : managed
                      ? `${displayName} is managed by Conductor and read-only`
                      : `${displayName} is bundled and always enabled`}
                  onCheckedChange={onToggle}
                />
              </div>
              {hasActions && <DropdownMenu>
                <DropdownMenuTrigger
                  disabled={busy}
                  aria-label={`Actions for ${displayName}`}
                  className={buttonVariants({ variant: 'outline', size: 'sm' })}
                >
                  <MoreHorizontal /> Actions <ChevronDown className="transition-transform group-data-[popup-open]:rotate-180" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-44">
                  {item.credentials.supported && <DropdownMenuItem onClick={onCredentials}>
                    <KeyRound /> Credentials
                  </DropdownMenuItem>}
                  {!managed && item.capabilities.can_edit && <DropdownMenuItem onClick={onOpen}>
                    <Code2 /> Edit plugin
                  </DropdownMenuItem>}
                  {!managed && item.capabilities.can_pack && <DropdownMenuItem onClick={onPack}>
                    <FileArchive /> Pack archive
                  </DropdownMenuItem>}
                  {!managed && item.capabilities.can_update && (
                    <DropdownMenuItem onClick={onUpdate}>
                      <RefreshCw /> Update package
                    </DropdownMenuItem>
                  )}
                  {!managed && item.capabilities.can_uninstall && <DropdownMenuSeparator />}
                  {!managed && item.capabilities.can_uninstall && <DropdownMenuItem variant="destructive" onClick={onDelete}>
                    <Trash2 /> Uninstall
                  </DropdownMenuItem>}
                </DropdownMenuContent>
              </DropdownMenu>}
            </div>
          </div>
        </div>
      </div>
    </article>
  )
}

export function PluginCenterPanel() {
  const queryClient = useQueryClient()
  const pushToast = useToastStore((state) => state.push)
  const { isTauri, os } = usePlatform()
  const desktop = isTauri && os !== 'ios' && os !== 'android'
  const uploadRef = useRef<HTMLInputElement>(null)
  const updateUploadRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [inspection, setInspection] = useState<PluginInspection | null>(null)
  const [activeView, setActiveView] = useState<
    | { kind: 'editor'; root: string; name: string }
    | { kind: 'credentials'; plugin: PluginListItem }
    | null
  >(null)
  const [showCreate, setShowCreate] = useState(false)
  const [hostPath, setHostPath] = useState('')
  // The host path used to be a permanent field above the list, wanted by
  // two of the four Add-plugin actions and by nobody else. Worse, those two
  // menu items sat disabled until you typed into an input *below* the menu,
  // so the reason they were greyed out was hidden behind the popover. It is
  // now asked for by the action that needs it, at the moment it needs it.
  const [pathPrompt, setPathPrompt] = useState<'link' | 'validate' | null>(null)
  const [filter, setFilter] = useState('')
  const {
    request: confirmRequest,
    confirm: confirmAction,
    close: closeConfirm,
  } = useConfirm()
  const [updateTarget, setUpdateTarget] = useState<PluginListItem | null>(null)
  const [trustReview, setTrustReview] = useState<
    (PluginOperationResponse & { managedResourceId?: string }) | null
  >(null)
  const [createParent, setCreateParent] = useState('')
  const [createName, setCreateName] = useState('')
  const [createDescription, setCreateDescription] = useState('')
  const [createVersion, setCreateVersion] = useState('')
  const [createAuthor, setCreateAuthor] = useState('')
  const [createLicense, setCreateLicense] = useState('')
  const [createSkill, setCreateSkill] = useState('')

  const query = useQuery({
    queryKey: queryKeys.plugins.list(),
    queryFn: listPlugins,
    refetchInterval: 5_000,
  })

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.plugins.all() })
  }

  const syncCredentials = async (
    installationId: string,
    credentials: PluginCredentialState,
  ) => {
    queryClient.setQueryData<PluginListResponse>(
      queryKeys.plugins.list(),
      (current) => current
        ? {
            ...current,
            plugins: current.plugins.map((item) =>
              item.installation.id === installationId
                ? { ...item, credentials }
                : item,
            ),
          }
        : current,
    )
    await queryClient.invalidateQueries({ queryKey: queryKeys.plugins.list() })
  }

  const run = async (label: string, action: () => Promise<unknown>) => {
    setBusy(label)
    try {
      await action()
      await refresh()
      return true
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Plugin operation failed',
        description: error instanceof Error ? error.message : String(error),
      })
      return false
    } finally {
      setBusy(null)
    }
  }

  const stageTrustReview = (result: PluginOperationResponse, action: string) => {
    setInspection(result.inspection)
    setTrustReview(result)
    pushToast({
      tone: 'success',
      title: `${result.installation.name} ${action}`,
      description: 'The plugin is installed but disabled until you review its access.',
    })
  }

  const confirmTrust = async () => {
    if (!trustReview) return
    const enabled = await run(
      `trust:${trustReview.installation.id}`,
      () => trustReview.managedResourceId
        ? approveConductorResource(trustReview.managedResourceId)
        : setPluginEnabled(trustReview.installation.id, true),
    )
    if (enabled) setTrustReview(null)
  }

  const pickAndImport = async (mode: 'install' | 'link') => {
    if (!desktop) {
      if (mode === 'install') {
        uploadRef.current?.click()
        return
      }
      const path = hostPath.trim()
      if (!path) return
      await run(`link:${path}`, async () => {
        const result = await importPlugin(path, 'link', false)
        stageTrustReview(result, 'linked')
      })
      return
    }
    const path = await choosePath({
      directory: mode === 'link',
      archive: mode === 'install',
    })
    if (!path) return
    await run(`${mode}:${path}`, async () => {
      const result = await importPlugin(path, mode, false)
      stageTrustReview(result, 'imported')
    })
  }

  const validateFolder = async () => {
    const path = desktop ? await choosePath({ directory: true }) : hostPath.trim()
    if (!path) return
    await run(`inspect:${path}`, async () => setInspection(await inspectPlugin(path)))
  }

  const chooseUpdate = async (item: PluginListItem) => {
    if (!desktop) {
      setUpdateTarget(item)
      updateUploadRef.current?.click()
      return
    }
    const path = await choosePath({ archive: true })
    if (!path) return
    await run(`update:${item.installation.id}`, async () => {
      const result = await updatePluginFromPath(item.installation.id, path)
      setInspection(result.inspection)
      pushToast({
        tone: 'success',
        title: `${result.installation.name} updated`,
        description: result.installation.version
          ? `Version ${result.installation.version}`
          : undefined,
      })
    })
  }

  const createPackage = async () => {
    const parent = createParent.trim()
    const name = createName.trim()
    if (!parent || !name) return
    const destination = `${parent.replace(/[\\/]+$/, '')}/${name}`
    const version = createVersion.trim()
    const author = createAuthor.trim()
    const license = createLicense.trim()
    const skillName = createSkill.trim() || name
    await run('create', async () => {
      const result = await createPlugin({
        destination,
        name,
        description: createDescription.trim() || `EvoFlux plugin ${name}`,
        skill_name: skillName,
        ...(version ? { version } : {}),
        ...(author ? { author } : {}),
        ...(license ? { license } : {}),
      })
      const resultInspection = await inspectPlugin(result.path)
      setInspection(resultInspection)
      setActiveView({
        kind: 'editor',
        root: result.path,
        name: resultInspection.manifest?.name || name,
      })
      setShowCreate(false)
      pushToast({ tone: 'success', title: 'Plugin scaffold created', description: result.path })
    })
  }

  if (activeView?.kind === 'credentials') {
    const credentialPlugin = activeView.plugin
    return (
      <PluginCredentialsPanel
        installation={credentialPlugin.installation}
        onBack={() => setActiveView(null)}
        onEdit={() => {
          setActiveView({
            kind: 'editor',
            root: credentialPlugin.installation.root,
            name: credentialPlugin.installation.name,
          })
        }}
        onSaved={(credentials) =>
          syncCredentials(credentialPlugin.installation.id, credentials)
        }
      />
    )
  }

  if (activeView?.kind === 'editor') {
    const linked = query.data?.plugins.some((item) => item.installation.root === activeView.root) ?? false
    return (
      <PluginWorkspaceEditor
        root={activeView.root}
        name={activeView.name}
        linked={linked}
        onBack={() => setActiveView(null)}
        onInspection={setInspection}
        onLink={async () => {
          const result = await importPlugin(activeView.root, 'link', false)
          setActiveView(null)
          stageTrustReview(result, 'linked')
          await refresh()
        }}
      />
    )
  }

  const plugins = query.data?.plugins ?? []
  const runtimeServers = query.data?.mcp_servers ?? []
  // One summary of the whole shelf, so the header answers "is anything
  // broken?" without reading every card. Same two facts a card reports.
  const failingCount = plugins.filter((item) => {
    const failed = item.installation.enabled
      && runtimeServers.some((server) =>
        server.installation_id === item.installation.id
        && server.enabled
        && server.state === 'error')
    return !item.inspection.valid || failed || errorDiagnostics(item.inspection).length > 0
  }).length
  const needle = filter.trim().toLowerCase()
  const visiblePlugins = needle
    ? plugins.filter((item) =>
        `${item.installation.name} ${item.installation.description ?? ''}`
          .toLowerCase()
          .includes(needle))
    : plugins
  const showFilter = plugins.length >= 3
  const closePanels = () => {
    setPathPrompt(null)
    setShowCreate(false)
  }
  const submitPathPrompt = async () => {
    const mode = pathPrompt
    if (!mode || !hostPath.trim()) return
    setPathPrompt(null)
    if (mode === 'link') await pickAndImport('link')
    else await validateFolder()
  }

  return (
    <section className="@container/plugin-center flex h-full min-h-0 flex-col bg-(--bg-page)">
      <header className="border-b border-(--color-border) px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <Box className="shrink-0 text-(--color-accent)" size={20} />
            <h2 className="text-lg font-semibold text-(--color-text)">Plugin Center</h2>
            {plugins.length > 0 && (
              <span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-xs font-medium tabular-nums text-(--color-text-muted)">
                {plugins.length}
              </span>
            )}
            {failingCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full border border-(--color-error)/25 bg-(--color-error-subtle) px-2 py-0.5 text-xs font-medium text-(--color-error)">
                <AlertTriangle size={11} aria-hidden="true" />
                {failingCount} need{failingCount === 1 ? 's' : ''} attention
              </span>
            )}
          </div>
          {/* Refresh belongs beside the action it complements, not adrift in
              the opposite corner of the description. */}
          <div className="flex shrink-0 items-center gap-1.5">
            <Button variant="ghost" size="icon-sm" onClick={() => void refresh()} aria-label="Refresh plugins">
              <RefreshCw className={cn(query.isFetching && 'animate-spin')} />
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger
                disabled={busy !== null}
                className={buttonVariants({ size: 'sm' })}
              >
                <PackagePlus /> Add plugin
                <ChevronDown className="transition-transform group-data-[popup-open]:rotate-180" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuItem onClick={() => { closePanels(); void pickAndImport('install') }}>
                  <PackagePlus /> Import package
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => {
                    if (desktop) { closePanels(); void pickAndImport('link'); return }
                    setShowCreate(false)
                    setPathPrompt('link')
                  }}
                >
                  <FolderInput /> Link development folder
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => {
                    if (desktop) { closePanels(); void validateFolder(); return }
                    setShowCreate(false)
                    setPathPrompt('validate')
                  }}
                >
                  <CheckCircle2 /> Validate folder
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => { setPathPrompt(null); setShowCreate(true) }}>
                  <FolderPlus /> Create plugin
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        <p className="mt-1.5 max-w-2xl text-sm text-(--color-text-muted)">
          Create, import, and use portable plugins with Agent Skills and MCP server configurations.
        </p>
        <div className="hidden">
          <input
            ref={uploadRef}
            hidden
            type="file"
            accept=".evoplugin,.zip"
            onChange={(event) => {
              const file = event.target.files?.[0]
              event.currentTarget.value = ''
              if (!file) return
              void run(`upload:${file.name}`, async () => {
                const result = await uploadPlugin(file, false)
                stageTrustReview(result, 'imported')
              })
            }}
          />
          <input
            ref={updateUploadRef}
            hidden
            type="file"
            accept=".evoplugin,.zip"
            onChange={(event) => {
              const file = event.target.files?.[0]
              event.currentTarget.value = ''
              const target = updateTarget
              setUpdateTarget(null)
              if (!file || !target) return
              void run(`update:${target.installation.id}`, async () => {
                const result = await updatePluginFromUpload(
                  target.installation.id,
                  file,
                )
                setInspection(result.inspection)
                pushToast({
                  tone: 'success',
                  title: `${result.installation.name} updated`,
                  description: result.installation.version
                    ? `Version ${result.installation.version}`
                    : undefined,
                })
              })
            }}
          />
        </div>

        {pathPrompt && (
          <div className="mt-3 rounded-lg border border-(--color-border) bg-(--bg-card) p-3">
            <h3 className="text-sm font-medium text-(--color-text)">
              {pathPrompt === 'link' ? 'Link a development folder' : 'Validate a folder'}
            </h3>
            <p className="mt-0.5 text-xs text-(--color-text-subtle)">
              The folder is read by the EvoFlux backend, so the path has to resolve on the
              machine the backend runs on — not on this one.
            </p>
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <Input
                autoFocus
                className="min-w-48 flex-1"
                value={hostPath}
                // The last path is kept, because linking and then validating
                // the same folder is the common pair. Selecting it means
                // typing still replaces rather than appends.
                onFocus={(event) => event.currentTarget.select()}
                onChange={(event) => setHostPath(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    void submitPathPrompt()
                  }
                  if (event.key === 'Escape') setPathPrompt(null)
                }}
                placeholder="/srv/evoflux/plugins/my-plugin"
                aria-label="Plugin folder path on the EvoFlux host"
              />
              <Button variant="ghost" onClick={() => setPathPrompt(null)}>Cancel</Button>
              <Button
                disabled={!hostPath.trim() || busy !== null}
                onClick={() => void submitPathPrompt()}
              >
                {pathPrompt === 'link' ? 'Link folder' : 'Validate'}
              </Button>
            </div>
          </div>
        )}

        {showCreate && (
          <div className="mt-4 space-y-3 rounded-lg border border-(--color-border) bg-(--bg-card) p-3">
            <div>
              <h3 className="text-sm font-medium text-(--color-text)">Create development plugin</h3>
              <p className="text-xs text-(--color-text-subtle)">Scaffold the package, then continue in the built-in code editor.</p>
            </div>
            <div className="grid gap-3 @lg/plugin-center:grid-cols-2">
              <CreateField id="plugin-create-parent" label="Parent folder">
                <div className="flex min-w-0 gap-2">
                  <Input id="plugin-create-parent" value={createParent} onChange={(event) => setCreateParent(event.target.value)} placeholder="/srv/evoflux/plugins" />
                  {desktop && (
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => void choosePath({ directory: true }).then((path) => path && setCreateParent(path))}
                      aria-label="Choose parent folder"
                    >
                      <FolderPlus />
                    </Button>
                  )}
                </div>
              </CreateField>
              <CreateField id="plugin-create-name" label="Plugin name">
                <Input id="plugin-create-name" value={createName} onChange={(event) => setCreateName(event.target.value)} placeholder="my-plugin" />
              </CreateField>
              <CreateField id="plugin-create-description" label="Description" className="@lg/plugin-center:col-span-2">
                <Input id="plugin-create-description" value={createDescription} onChange={(event) => setCreateDescription(event.target.value)} placeholder="What the plugin does" />
              </CreateField>
              <CreateField id="plugin-create-version" label="Version" optional>
                <Input id="plugin-create-version" value={createVersion} onChange={(event) => setCreateVersion(event.target.value)} placeholder="0.1.0" />
              </CreateField>
              <CreateField id="plugin-create-author" label="Author" optional>
                <Input id="plugin-create-author" value={createAuthor} onChange={(event) => setCreateAuthor(event.target.value)} placeholder="Your name or team" />
              </CreateField>
              <CreateField id="plugin-create-license" label="License" optional>
                <Input id="plugin-create-license" value={createLicense} onChange={(event) => setCreateLicense(event.target.value)} placeholder="MIT" />
              </CreateField>
              <CreateField id="plugin-create-skill" label="Starter Skill" optional>
                <Input id="plugin-create-skill" value={createSkill} onChange={(event) => setCreateSkill(event.target.value)} placeholder="Defaults to the plugin name" />
              </CreateField>
            </div>
            <p className="text-xs text-(--color-text-subtle)">
              Add MCP only when the package includes a verified portable runtime.
            </p>
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="ghost" onClick={() => setShowCreate(false)}>Cancel</Button>
              <Button disabled={!createParent.trim() || !createName.trim() || busy !== null} onClick={() => void createPackage()}>
                Create &amp; edit
              </Button>
            </div>
          </div>
        )}

        {showFilter && (
          <div className="relative mt-3">
            <Search
              className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-(--color-text-subtle)"
              size={15}
              aria-hidden="true"
            />
            <Input
              className="pl-9"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder={`Filter ${plugins.length} plugins`}
              aria-label="Filter plugins"
            />
          </div>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {busy && (
          <div className="mb-4 flex items-center gap-2 rounded-lg bg-(--bg-key) px-3 py-2 text-sm text-(--color-text-muted)">
            <Loader2 className="animate-spin" size={15} /> Working…
          </div>
        )}

        {inspection && (
          <div
            className={cn(
              'mb-5 cursor-pointer rounded-xl border p-4 transition-opacity hover:opacity-90',
              inspection.valid ? 'border-(--color-success)/30 bg-(--color-success-subtle)' : 'border-(--color-error)/30 bg-(--color-error-subtle)',
            )}
            role="button"
            tabIndex={0}
            aria-label={`Edit ${inspection.manifest?.name || 'plugin package'}`}
            onClick={() => setActiveView({ kind: 'editor', root: inspection.root, name: inspection.manifest?.name || 'Plugin package' })}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                setActiveView({ kind: 'editor', root: inspection.root, name: inspection.manifest?.name || 'Plugin package' })
              }
            }}
          >
            <div className="flex items-center gap-2 font-medium text-(--color-text)">
              {inspection.valid ? <CheckCircle2 className="text-(--color-success)" /> : <AlertTriangle className="text-(--color-error)" />}
              {inspection.manifest?.name || 'Package inspection'}
            </div>
            <p className="mt-1 truncate font-mono text-xs text-(--color-text-muted)" title={inspection.root}>{inspection.root}</p>
            <p className="mt-2 text-sm text-(--color-text-muted)">
              {inspection.skills.filter((skill) => skill.valid).length} skills · {inspection.mcp_servers.filter((server) => server.valid).length} MCP servers · SHA-256 {inspection.content_sha256?.slice(0, 12) || 'unavailable'}
            </p>
            {inspection.diagnostics.map((item) => (
              <p key={`${item.scope}:${item.code}`} className="mt-1 text-xs text-(--color-error)">{item.message}</p>
            ))}
          </div>
        )}

        {query.isLoading ? (
          <div className="flex justify-center py-16"><Loader2 className="animate-spin text-(--color-text-muted)" /></div>
        ) : query.isError ? (
          <div className="rounded-xl border border-(--color-error)/30 bg-(--color-error-subtle) p-4 text-sm text-(--color-error)">
            {query.error instanceof Error ? query.error.message : 'Could not load plugins.'}
          </div>
        ) : visiblePlugins.length ? (
          <div className="space-y-2">
            {visiblePlugins.map((item) => (
              <PluginCard
                key={item.installation.id}
                item={item}
                servers={runtimeServers.filter(
                  (server) => server.installation_id === item.installation.id,
                )}
                busy={busy !== null}
                onToggle={(enabled) => {
                  if (enabled) {
                    setTrustReview({
                      installation: item.installation,
                      inspection: item.inspection,
                      managedResourceId:
                        item.provider?.observed_state === CONDUCTOR_RESOURCE_STATE.TRUST_PENDING
                        && item.installation.managed_version_id === item.provider.version_id
                          ? item.provider.resource_id
                          : undefined,
                    })
                    return
                  }
                  void run(`toggle:${item.installation.id}`, () => setPluginEnabled(item.installation.id, false))
                }}
                onPack={() => void run(`pack:${item.installation.id}`, async () => {
                  const result = await packPlugin(item.installation.root)
                  pushToast({ tone: 'success', title: 'Plugin archive created', description: result.path })
                })}
                onDelete={() => confirmAction({
                  title: `Uninstall ${item.installation.name}?`,
                  description: item.installation.source_type === 'linked'
                    ? 'The development folder stays on disk; only the link and its runtime state are removed. Plugin data is preserved.'
                    : 'The installed package is removed and its MCP servers stop. Plugin data is preserved, so reinstalling restores it.',
                  confirmLabel: 'Uninstall',
                  destructive: true,
                  onConfirm: () => void run(
                    `delete:${item.installation.id}`,
                    () => uninstallPlugin(item.installation.id),
                  ),
                })}
                onOpen={() => setActiveView({ kind: 'editor', root: item.installation.root, name: item.installation.name })}
                onCredentials={() => setActiveView({ kind: 'credentials', plugin: item })}
                onUpdate={() => item.provider ? refresh() : chooseUpdate(item)}
              />
            ))}
          </div>
        ) : needle ? (
          <div className="mx-auto max-w-md py-16 text-center">
            <Search className="mx-auto text-(--color-text-subtle)" size={32} aria-hidden="true" />
            <h3 className="mt-3 font-medium text-(--color-text)">No plugin matches “{filter.trim()}”</h3>
            <Button variant="ghost" className="mt-2" onClick={() => setFilter('')}>
              Clear filter
            </Button>
          </div>
        ) : (
          <div className="mx-auto max-w-md py-16 text-center">
            <Blocks className="mx-auto text-(--color-text-subtle)" size={36} />
            <h3 className="mt-3 font-medium text-(--color-text)">No plugins yet</h3>
            <p className="mt-1 text-sm text-(--color-text-muted)">Import a .evoplugin archive or link a development folder.</p>
          </div>
        )}
      </div>
      <PluginTrustReviewDialog
        pluginName={trustReview?.installation.name ?? null}
        review={trustReview?.inspection.trust ?? null}
        busy={busy?.startsWith('trust:') === true}
        onCancel={() => setTrustReview(null)}
        onConfirm={() => void confirmTrust()}
      />
      <ConfirmDialog request={confirmRequest} onClose={closeConfirm} />
    </section>
  )
}
