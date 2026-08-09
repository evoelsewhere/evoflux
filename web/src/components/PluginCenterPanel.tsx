import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Blocks,
  Box,
  CheckCircle2,
  FileArchive,
  FolderInput,
  FolderPlus,
  Loader2,
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
  uploadPlugin,
} from '@/api/client'
import type {
  PluginInspection,
  PluginListItem,
  PluginMcpRuntimeStatus,
} from '@/api/types'
import { queryKeys } from '@/queries/keys'
import { usePlatform } from '@/hooks/use-platform'
import { useToastStore } from '@/stores/useToastStore'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'

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

function PluginCard({
  item,
  servers,
  busy,
  onToggle,
  onPack,
  onDelete,
}: {
  item: PluginListItem
  servers: PluginMcpRuntimeStatus[]
  busy: boolean
  onToggle: (enabled: boolean) => void
  onPack: () => void
  onDelete: () => void
}) {
  const { installation, inspection } = item
  const errors = diagnosticsCount(inspection)
  return (
    <article className="rounded-xl border border-(--color-border) bg-(--bg-card) p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
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
          <p className="mt-1 text-sm text-(--color-text-muted)">
            {installation.description || 'Portable Agent Plugin'}
          </p>
        </div>
        <Switch
          checked={installation.enabled}
          disabled={busy}
          aria-label={`${installation.enabled ? 'Disable' : 'Enable'} ${installation.name}`}
          onCheckedChange={onToggle}
        />
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-xs text-(--color-text-muted)">
        <span className="inline-flex items-center gap-1 rounded-md bg-(--bg-key) px-2 py-1">
          <Blocks size={12} /> {inspection.skills.filter((skill) => skill.valid).length} skills
        </span>
        <span className="inline-flex items-center gap-1 rounded-md bg-(--bg-key) px-2 py-1">
          <Server size={12} /> {inspection.mcp_servers.filter((server) => server.valid).length} MCP
        </span>
        <span
          className={cn(
            'inline-flex items-center gap-1 rounded-md px-2 py-1',
            errors ? 'bg-(--color-error-subtle) text-(--color-error)' : 'bg-(--color-success-subtle) text-(--color-success)',
          )}
        >
          {errors ? <AlertTriangle size={12} /> : <CheckCircle2 size={12} />}
          {errors ? `${errors} component errors` : 'valid'}
        </span>
      </div>

      <p className="mt-3 truncate font-mono text-[11px] text-(--color-text-subtle)" title={installation.root}>
        {installation.root}
      </p>
      {servers.length > 0 && (
        <div className="mt-3 space-y-2 rounded-lg border border-(--color-border) bg-(--bg-key) p-2.5">
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
              <p className="mt-1 truncate font-mono text-[11px] text-(--color-text-subtle)" title={server.runtime_name}>
                runtime: {server.runtime_name}
              </p>
              {server.tool_names.length > 0 && (
                <p className="mt-1 break-words text-[11px] text-(--color-text-muted)">
                  tools: {server.tool_names.join(', ')}
                </p>
              )}
              {server.error && <p className="mt-1 text-[11px] text-(--color-error)">{server.error}</p>}
            </div>
          ))}
        </div>
      )}
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="outline" size="sm" disabled={busy} onClick={onPack}>
          <FileArchive /> Pack
        </Button>
        <Button variant="destructive" size="sm" disabled={busy} onClick={onDelete}>
          <Trash2 /> Uninstall
        </Button>
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
  const [busy, setBusy] = useState<string | null>(null)
  const [inspection, setInspection] = useState<PluginInspection | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [createParent, setCreateParent] = useState('')
  const [createName, setCreateName] = useState('')
  const [createSkill, setCreateSkill] = useState('')

  const query = useQuery({
    queryKey: queryKeys.plugins.list(),
    queryFn: listPlugins,
    refetchInterval: 5_000,
  })

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.plugins.all() })
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
      uploadRef.current?.click()
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
    if (!desktop) return
    const path = await choosePath({ directory: true })
    if (!path) return
    await run(`inspect:${path}`, async () => setInspection(await inspectPlugin(path)))
  }

  const createPackage = async () => {
    if (!createParent || !createName) return
    const destination = `${createParent.replace(/[\\/]+$/, '')}/${createName}`
    await run('create', async () => {
      const result = await createPlugin({
        destination,
        name: createName,
        description: `EvoFlux plugin ${createName}`,
        skill_name: createSkill || undefined,
      })
      setInspection(await inspectPlugin(result.path))
      setShowCreate(false)
      pushToast({ tone: 'success', title: 'Plugin scaffold created', description: result.path })
    })
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
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={() => void pickAndImport('install')} disabled={busy !== null}>
            <PackagePlus /> Import package
          </Button>
          <Button variant="outline" onClick={() => void pickAndImport('link')} disabled={busy !== null || !desktop}>
            <FolderInput /> Link folder
          </Button>
          <Button variant="outline" onClick={() => void validateFolder()} disabled={busy !== null || !desktop}>
            <CheckCircle2 /> Validate
          </Button>
          <Button variant="outline" onClick={() => setShowCreate((value) => !value)} disabled={!desktop}>
            <FolderPlus /> Create
          </Button>
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
        </div>

        {showCreate && (
          <div className="mt-4 grid gap-2 rounded-lg border border-(--color-border) bg-(--bg-card) p-3 md:grid-cols-[1fr_0.7fr_0.7fr_auto]">
            <div className="flex gap-2">
              <Input value={createParent} onChange={(event) => setCreateParent(event.target.value)} placeholder="Parent folder" />
              <Button
                variant="outline"
                size="icon"
                onClick={() => void choosePath({ directory: true }).then((path) => path && setCreateParent(path))}
                aria-label="Choose parent folder"
              >
                <FolderPlus />
              </Button>
            </div>
            <Input value={createName} onChange={(event) => setCreateName(event.target.value)} placeholder="plugin-name" />
            <Input value={createSkill} onChange={(event) => setCreateSkill(event.target.value)} placeholder="optional-skill" />
            <Button disabled={!createParent || !createName || busy !== null} onClick={() => void createPackage()}>
              Create
            </Button>
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
          <div className={cn(
            'mb-5 rounded-xl border p-4',
            inspection.valid ? 'border-(--color-success)/30 bg-(--color-success-subtle)' : 'border-(--color-error)/30 bg-(--color-error-subtle)',
          )}>
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
          <div className="grid gap-3 xl:grid-cols-2">
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
