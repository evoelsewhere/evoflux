import { useRef, useState } from 'react'
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
  Server,
  Trash2,
} from 'lucide-react'
import {
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

function diagnosticsCount(inspection: PluginInspection): number {
  return [
    ...inspection.diagnostics,
    ...inspection.skills.flatMap((skill) => skill.diagnostics),
    ...inspection.mcp_servers.flatMap((server) => server.diagnostics),
  ].filter((item) => item.severity === 'error').length
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
  onUpdate: () => void
}) {
  const { installation, inspection } = item
  const [expanded, setExpanded] = useState(false)
  const errors = diagnosticsCount(inspection)
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
  return (
    <article className="@container/plugin-card overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card) shadow-sm transition-colors hover:border-(--color-accent)/50">
      <button
        type="button"
        className="flex w-full min-w-0 items-center gap-3 px-3 py-2.5 text-left hover:bg-(--bg-key)/50"
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={() => setExpanded((current) => !current)}
      >
        <div className="min-w-0 flex-1 @lg/plugin-card:flex @lg/plugin-card:items-center @lg/plugin-card:gap-4">
          <div className="flex min-w-0 flex-wrap items-center gap-2 @lg/plugin-card:min-w-52">
            <h3 className="truncate font-semibold text-(--color-text)">
              {installation.name}
            </h3>
            {installation.version && (
              <span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-xs text-(--color-text-muted)">
                v{installation.version}
              </span>
            )}
            <span className="rounded-full border border-(--color-border) px-2 py-0.5 text-xs text-(--color-text-muted)">
              {installation.source_type === 'linked' ? 'dev link' : 'installed'}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5 text-xs text-(--color-text-muted) @lg/plugin-card:mt-0">
            <span
              className={cn(
                'inline-flex items-center gap-1 rounded-md px-2 py-1',
                errors ? 'bg-(--color-error-subtle) text-(--color-error)' : 'bg-(--color-success-subtle) text-(--color-success)',
              )}
            >
              {errors ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />}
              {errors ? `${errors} component errors` : 'valid'}
            </span>
            {item.credentials.supported && (
              <span className={cn(
                'inline-flex items-center gap-1 rounded-md px-2 py-1',
                item.credentials.configured
                  ? 'bg-(--color-success-subtle) text-(--color-success)'
                  : 'bg-(--color-warning-subtle) text-(--color-warning)',
              )}>
                <KeyRound size={12} /> {credentialLabel}
              </span>
            )}
          </div>
        </div>
        <span
          className={cn(
            'hidden rounded-full px-2 py-0.5 text-xs @sm/plugin-card:inline-flex',
            installation.enabled
              ? 'bg-(--color-success-subtle) text-(--color-success)'
              : 'bg-(--bg-key) text-(--color-text-muted)',
          )}
        >
          {installation.enabled ? 'Enabled' : 'Disabled'}
        </span>
        <ChevronDown
          size={17}
          className={cn(
            'shrink-0 text-(--color-text-muted) transition-transform',
            expanded && 'rotate-180',
          )}
          aria-hidden="true"
        />
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
            className="grid gap-4 p-4 @lg/plugin-card:grid-cols-[minmax(150px,1fr)_minmax(150px,1fr)_auto]"
          >
            <div className="min-w-0">
              <p className="text-sm text-(--color-text-muted)">
                {installation.description || 'Portable Agent Plugin'}
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5 text-xs text-(--color-text-muted)">
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

            <div className="min-w-0 border-t border-(--color-border) pt-3 @lg/plugin-card:border-t-0 @lg/plugin-card:border-l @lg/plugin-card:pt-0 @lg/plugin-card:pl-4">
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

            <div className="flex content-start items-center justify-between gap-3 border-t border-(--color-border) pt-3 @lg/plugin-card:w-36 @lg/plugin-card:flex-col @lg/plugin-card:items-end @lg/plugin-card:justify-start @lg/plugin-card:border-t-0 @lg/plugin-card:pt-0">
              <div className="flex items-center gap-2">
                <span className="text-xs text-(--color-text-muted)">
                  {installation.enabled ? 'Enabled' : 'Disabled'}
                </span>
                <Switch
                  checked={installation.enabled}
                  disabled={busy}
                  aria-label={`${installation.enabled ? 'Disable' : 'Enable'} ${installation.name}`}
                  onCheckedChange={onToggle}
                />
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger
                  disabled={busy}
                  aria-label={`Actions for ${installation.name}`}
                  className={buttonVariants({ variant: 'outline', size: 'sm' })}
                >
                  <MoreHorizontal /> Actions <ChevronDown className="transition-transform group-data-[popup-open]:rotate-180" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-44">
                  <DropdownMenuItem onClick={onCredentials}>
                    <KeyRound /> Credentials
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={onOpen}>
                    <Code2 /> Edit plugin
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={onPack}>
                    <FileArchive /> Pack archive
                  </DropdownMenuItem>
                  {installation.source_type === 'installed' && (
                    <DropdownMenuItem onClick={onUpdate}>
                      <RefreshCw /> Update package
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem variant="destructive" onClick={onDelete}>
                    <Trash2 /> Uninstall
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
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
  const [updateTarget, setUpdateTarget] = useState<PluginListItem | null>(null)
  const [createParent, setCreateParent] = useState('')
  const [createName, setCreateName] = useState('')
  const [createDescription, setCreateDescription] = useState('')
  const [createVersion, setCreateVersion] = useState('0.1.0')
  const [createAuthor, setCreateAuthor] = useState('')
  const [createLicense, setCreateLicense] = useState('MIT')
  const [createSkill, setCreateSkill] = useState('')
  const [createMcp, setCreateMcp] = useState('')

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
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Plugin operation failed',
        description: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setBusy(null)
    }
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
        const result = await importPlugin(path, 'link')
        setInspection(result.inspection)
        pushToast({ tone: 'success', title: `${result.installation.name} linked` })
      })
      return
    }
    const path = await choosePath({
      directory: mode === 'link',
      archive: mode === 'install',
    })
    if (!path) return
    await run(`${mode}:${path}`, async () => {
      const result = await importPlugin(path, mode)
      setInspection(result.inspection)
      pushToast({ tone: 'success', title: `${result.installation.name} imported` })
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
    if (!createParent || !createName) return
    const destination = `${createParent.replace(/[\\/]+$/, '')}/${createName}`
    await run('create', async () => {
      const result = await createPlugin({
        destination,
        name: createName,
        description: createDescription || `EvoFlux plugin ${createName}`,
        version: createVersion || undefined,
        author: createAuthor || undefined,
        license: createLicense || undefined,
        skill_name: createSkill || undefined,
        mcp_name: createMcp || undefined,
      })
      const resultInspection = await inspectPlugin(result.path)
      setInspection(resultInspection)
      setActiveView({
        kind: 'editor',
        root: result.path,
        name: resultInspection.manifest?.name || createName,
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
          const result = await importPlugin(activeView.root, 'link')
          setInspection(result.inspection)
          await refresh()
          pushToast({ tone: 'success', title: `${result.installation.name} linked` })
        }}
      />
    )
  }

  return (
    <section className="flex h-full min-h-0 flex-col bg-(--bg-page)">
      <header className="border-b border-(--color-border) px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Box className="text-(--color-accent)" size={20} />
              <h2 className="text-lg font-semibold text-(--color-text)">Plugin Center</h2>
            </div>
            <p className="mt-1 text-sm text-(--color-text-muted)">
              Create, import, and use portable plugins with Agent Skills and MCP server configurations.
            </p>
          </div>
          <Button variant="ghost" size="icon-sm" onClick={() => void refresh()} aria-label="Refresh plugins">
            <RefreshCw className={cn(query.isFetching && 'animate-spin')} />
          </Button>
        </div>
        <div className="mt-4">
          <DropdownMenu>
            <DropdownMenuTrigger
              disabled={busy !== null}
              className={buttonVariants()}
            >
              <PackagePlus /> Add plugin
              <ChevronDown className="transition-transform group-data-[popup-open]:rotate-180" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-52">
              <DropdownMenuItem onClick={() => void pickAndImport('install')}>
                <PackagePlus /> Import package
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={!desktop && !hostPath.trim()}
                onClick={() => void pickAndImport('link')}
              >
                <FolderInput /> Link development folder
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={!desktop && !hostPath.trim()}
                onClick={() => void validateFolder()}
              >
                <CheckCircle2 /> Validate folder
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => setShowCreate(true)}>
                <FolderPlus /> Create plugin
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
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
                const result = await uploadPlugin(file)
                setInspection(result.inspection)
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

        {!desktop && (
          <div className="mt-3">
            <Input
              value={hostPath}
              onChange={(event) => setHostPath(event.target.value)}
              placeholder="Plugin folder path on the EvoFlux host"
              aria-label="Plugin folder path on the EvoFlux host"
            />
            <p className="mt-1 text-xs text-(--color-text-subtle)">
              Link and Validate use a folder that is accessible to the local EvoFlux backend.
            </p>
          </div>
        )}

        {showCreate && (
          <div className="mt-4 space-y-3 rounded-lg border border-(--color-border) bg-(--bg-card) p-3">
            <div>
              <h3 className="text-sm font-medium text-(--color-text)">Create development plugin</h3>
              <p className="text-xs text-(--color-text-subtle)">Scaffold the package, then continue in the built-in code editor.</p>
            </div>
            <div className="grid gap-2 md:grid-cols-2">
              <div className="flex gap-2">
                <Input value={createParent} onChange={(event) => setCreateParent(event.target.value)} placeholder="Parent folder" aria-label="Plugin parent folder" />
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
              <Input value={createName} onChange={(event) => setCreateName(event.target.value)} placeholder="plugin-name" aria-label="Plugin name" />
              <Input value={createDescription} onChange={(event) => setCreateDescription(event.target.value)} placeholder="Description" aria-label="Plugin description" />
              <Input value={createVersion} onChange={(event) => setCreateVersion(event.target.value)} placeholder="Version (0.1.0)" aria-label="Plugin version" />
              <Input value={createAuthor} onChange={(event) => setCreateAuthor(event.target.value)} placeholder="Author" aria-label="Plugin author" />
              <Input value={createLicense} onChange={(event) => setCreateLicense(event.target.value)} placeholder="License (MIT)" aria-label="Plugin license" />
              <Input value={createSkill} onChange={(event) => setCreateSkill(event.target.value)} placeholder="Optional Skill name" aria-label="Starter Skill name" />
              <Input value={createMcp} onChange={(event) => setCreateMcp(event.target.value)} placeholder="Optional MCP server name" aria-label="Starter MCP server name" />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setShowCreate(false)}>Cancel</Button>
              <Button disabled={!createParent || !createName || busy !== null} onClick={() => void createPackage()}>
                Create &amp; edit
              </Button>
            </div>
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
        ) : query.data?.plugins.length ? (
          <div className="space-y-2">
            {query.data.plugins.map((item) => (
              <PluginCard
                key={item.installation.id}
                item={item}
                servers={(query.data?.mcp_servers ?? []).filter(
                  (server) => server.installation_id === item.installation.id,
                )}
                busy={busy !== null}
                onToggle={(enabled) => void run(`toggle:${item.installation.id}`, () => setPluginEnabled(item.installation.id, enabled))}
                onPack={() => void run(`pack:${item.installation.id}`, async () => {
                  const result = await packPlugin(item.installation.root)
                  pushToast({ tone: 'success', title: 'Plugin archive created', description: result.path })
                })}
                onDelete={() => {
                  if (!window.confirm(`Uninstall ${item.installation.name}? Plugin data will be preserved.`)) return
                  void run(`delete:${item.installation.id}`, () => uninstallPlugin(item.installation.id))
                }}
                onOpen={() => setActiveView({ kind: 'editor', root: item.installation.root, name: item.installation.name })}
                onCredentials={() => setActiveView({ kind: 'credentials', plugin: item })}
                onUpdate={() => void chooseUpdate(item)}
              />
            ))}
          </div>
        ) : (
          <div className="mx-auto max-w-md py-16 text-center">
            <Blocks className="mx-auto text-(--color-text-subtle)" size={36} />
            <h3 className="mt-3 font-medium text-(--color-text)">No plugins yet</h3>
            <p className="mt-1 text-sm text-(--color-text-muted)">Import a .evoplugin archive or link a development folder.</p>
          </div>
        )}
      </div>
    </section>
  )
}
