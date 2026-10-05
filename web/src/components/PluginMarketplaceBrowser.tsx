import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Download, LoaderCircle, RefreshCw, Search, Trash2 } from 'lucide-react'

import {
  addMarketplace,
  installMarketplacePlugin,
  listMarketplaces,
  prepareMarketplacePlugin,
  removeMarketplace,
  searchMarketplacePlugins,
  syncMarketplace,
} from '@/api/client'
import type {
  MarketplaceCompatibility,
  MarketplaceCreateRequest,
  MarketplaceKind,
  MarketplacePlugin,
  MarketplacePluginPreview,
  MarketplaceSource,
  PluginOperationResponse,
} from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SelectControl } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { queryKeys } from '@/queries/keys'
import { PluginInspectionDetails, PluginPackageFiles } from '@/components/PluginPackageReview'
import { hasPluginReviewErrors, matchesMarketplaceFilters } from '@/utils/plugin-catalog'

interface PluginMarketplaceBrowserProps {
  onInstalled: (result: PluginOperationResponse) => void
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function CompatibilityBadge({ value }: { value: MarketplaceCompatibility }) {
  const styles: Record<MarketplaceCompatibility, string> = {
    compatible: 'border-(--color-success)/30 bg-(--color-success-subtle) text-(--color-success)',
    partial: 'border-(--color-warning)/30 bg-(--color-warning-subtle) text-(--color-warning)',
    unsupported: 'border-(--color-error)/30 bg-(--color-error-subtle) text-(--color-error)',
    unknown: 'border-(--color-border) bg-(--bg-muted) text-(--color-text-muted)',
  }
  const label = value === 'partial'
    ? 'Partial compatibility'
    : value === 'compatible'
      ? 'Compatible'
      : value === 'unsupported'
        ? 'Unsupported'
        : 'Compatibility unknown'

  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs ${styles[value]}`}>
      {label}
    </span>
  )
}

function MarketplaceRow({
  source,
  busy,
  onSync,
  onRemove,
}: {
  source: MarketplaceSource
  busy: boolean
  onSync: () => void
  onRemove: () => void
}) {
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 border-b border-(--color-border) py-3 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-(--color-text)">{source.name}</span>
          <span className="rounded-full bg-(--bg-muted) px-2 py-0.5 text-xs text-(--color-text-muted)">
            {source.kind === 'agent_plugins' ? 'Agent Plugins 1.0.0' : 'Claude Code'}
          </span>
        </div>
        <p className="mt-1 break-all text-xs text-(--color-text-muted)">{source.url}</p>
        {source.last_error ? (
          <p className="mt-1 text-xs text-(--color-error)" role="alert">{source.last_error}</p>
        ) : (
          <p className="mt-1 text-xs text-(--color-text-muted)">
            {source.last_synced_at
              ? `Last synced ${new Date(source.last_synced_at).toLocaleString()}`
              : 'Not synced yet'}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Button variant="outline" size="sm" disabled={busy} onClick={onSync}>
          {busy ? <LoaderCircle className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
          Sync
        </Button>
        <Button variant="ghost" size="sm" aria-label={`Remove ${source.name}`} disabled={busy} onClick={onRemove}>
          <Trash2 className="size-3.5" />
        </Button>
      </div>
    </li>
  )
}

function marketplacePluginMonogram(name: string): string {
  const words = name.trim().split(/[\s/_-]+/).filter(Boolean)
  const mark = words.length > 1
    ? words.slice(0, 2).map((word) => word.charAt(0)).join('')
    : words[0]?.slice(0, 2) ?? ''

  return mark.toUpperCase() || 'PL'
}

function MarketplacePluginRow({
  plugin,
  sourceName,
  selected,
  onSelect,
}: {
  plugin: MarketplacePlugin
  selected: boolean
  sourceName?: string
  onSelect: () => void
}) {
  const sourceTypeLabel = plugin.source_type === 'git-subdir'
    ? 'Git repository subdirectory'
    : plugin.source_type

  return (
    <li className="py-0.5">
      <button
        type="button"
        aria-label={`View details for ${plugin.name}`}
        aria-pressed={selected}
        onClick={onSelect}
        className={`w-full rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent) ${selected
          ? 'border-(--color-accent)/50 bg-(--bg-muted)'
          : 'border-transparent hover:border-(--color-border) hover:bg-(--bg-muted)'
        }`}
      >
        <span className="flex min-w-0 items-start gap-3">
          <span
            aria-hidden="true"
            className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg border border-(--color-border) bg-(--bg-muted) text-xs font-semibold tracking-wide text-(--color-text-muted)"
          >
            {marketplacePluginMonogram(plugin.name)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <span className="font-medium text-(--color-text)">{plugin.name}</span>
              <CompatibilityBadge value={plugin.compatibility} />
              {plugin.components.length > 0 && (
                <span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-xs text-(--color-text-muted)">
                  {plugin.components.length} component{plugin.components.length === 1 ? '' : 's'}
                </span>
              )}
            </span>
            <span className="mt-1 block truncate text-sm text-(--color-text-muted)">
              {plugin.description}
            </span>
            <span className="mt-1 block truncate text-xs text-(--color-text-muted)">
              {[sourceName, plugin.author, sourceTypeLabel, plugin.categories?.join(' / '), plugin.verification].filter(Boolean).join(' · ')}
            </span>
          </span>
        </span>
      </button>
    </li>
  )
}

function marketplaceInstallabilityReason(
  plugin: MarketplacePlugin,
  marketplaceKind: MarketplaceKind | undefined,
): string | null {
  if (plugin.installable && plugin.compatibility !== 'unsupported') return null

  if (plugin.source_type === 'npm') {
    return 'EvoFlux does not yet install npm-sourced Claude Code plugins. Use a relative, URL, GitHub, or Git subdirectory source.'
  }
  if (plugin.source_type === 'command') {
    return 'EvoFlux does not execute command-based Claude Code plugin sources. Use a relative, URL, GitHub, or Git subdirectory source.'
  }

  if (marketplaceKind === 'claude_code') {
    return 'This Claude Code plugin uses an unsupported source type. EvoFlux supports relative paths, URLs, GitHub, and Git subdirectories.'
  }

  if (marketplaceKind === 'agent_plugins') {
    return 'This Agent Plugins entry is not declared portable to EvoFlux. It needs portable: true, at least one supported Skills or MCP component, and compatibleClients must not exclude evoflux.'
  }

  return 'This catalog entry uses a source or component that EvoFlux cannot currently install.'
}

function MarketplacePluginDetails({
  plugin,
  busy,
  onPrepare,
  marketplaceKind,
  showTitle = true,
  pinActions = false,
}: {
  plugin: MarketplacePlugin
  busy: boolean
  onPrepare: () => void
  marketplaceKind: MarketplaceKind | undefined
  showTitle?: boolean
  pinActions?: boolean
}) {
  const sourceTypeLabel = plugin.source_type === 'git-subdir'
    ? 'Git repository subdirectory'
    : plugin.source_type
  const installable = plugin.installable && plugin.compatibility !== 'unsupported'
  const installabilityReason = marketplaceInstallabilityReason(plugin, marketplaceKind)
  const technicalDetails = [
    ['Categories', plugin.categories?.join(', ') ?? ''],
    ['Keywords', plugin.keywords?.join(', ') ?? ''],
    ['Author', plugin.author ?? ''],
    ['Version', plugin.version ? `v${plugin.version}` : ''],
    ['Source', sourceTypeLabel],
    ['Verification', plugin.verification],
  ].filter(([, value]) => Boolean(value))

  return (
    <section className={`flex min-h-0 flex-col ${showTitle ? 'rounded-xl border border-(--color-border) bg-(--bg-panel) p-4' : ''}`} aria-label={`Details for ${plugin.name}`}>
      <div className="space-y-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            {showTitle && (
              <h3 className="min-w-0 break-words text-lg font-semibold text-(--color-text)">{plugin.name}</h3>
            )}
            <CompatibilityBadge value={plugin.compatibility} />
          </div>
          {plugin.description && <p className="mt-2 text-sm leading-6 text-(--color-text-muted)">{plugin.description}</p>}
        </div>
        {plugin.verification === 'unverified' && (
          <p role="note" className="rounded-lg border border-(--color-border) px-3 py-2 text-xs text-(--color-text-muted)">
            Unverified is a trust warning, not an installability check. Review the source carefully; imported plugins remain disabled until you enable them.
          </p>
        )}
        {!installable && installabilityReason && (
          <p role="status" className="rounded-lg border border-(--color-border) px-3 py-2 text-sm text-(--color-text-muted)">
            {installabilityReason}
          </p>
        )}
        {plugin.components.length > 0 && <details className="rounded-lg border border-(--color-border) px-3 py-2">
          <summary className="cursor-pointer text-sm font-medium text-(--color-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)">Components</summary>
          <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Declared components">
            {plugin.components.map((component) => (
              <li key={component} className="rounded-full bg-(--bg-key) px-2.5 py-1 text-xs text-(--color-text)">
                {component}
              </li>
            ))}
          </ul>
        </details>}
        {technicalDetails.length > 0 && <details className="rounded-lg border border-(--color-border) px-3 py-2">
          <summary className="cursor-pointer text-sm font-medium text-(--color-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)">Technical details</summary>
          <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
            {technicalDetails.map(([label, value]) => <Fragment key={label}><dt className="text-(--color-text-muted)">{label}</dt><dd className="min-w-0 break-words text-(--color-text)">{value}</dd></Fragment>)}
          </dl>
        </details>}
      </div>
      <p className="text-xs text-(--color-text-muted)">Inspect downloads only this package for read-only review. Nothing is installed or started.</p>
      <div className={`${pinActions ? 'sticky bottom-0 border-t border-(--color-border) bg-(--bg-panel) pt-4 pb-1' : 'mt-auto border-t border-(--color-border) pt-4'}`}>
        <Button className="w-full" disabled={!installable || busy} onClick={onPrepare}>
          {busy ? <LoaderCircle className="size-4 animate-spin" /> : <Download className="size-4" />}
          {installable ? 'Inspect package' : 'Not installable'}
        </Button>
      </div>
    </section>
  )
}

function MarketplacePreview({
  preview,
  busy,
  onCancel,
  onInstall,
  pinActions = false,
}: {
  preview: MarketplacePluginPreview
  busy: boolean
  onCancel: () => void
  onInstall: (allowPartial: boolean) => void
  pinActions?: boolean
}) {
  const [allowPartial, setAllowPartial] = useState(false)
  const [filesReady, setFilesReady] = useState(false)
  const hasUnsupported = preview.unsupported_components.length > 0
  const hasSupported = preview.supported_components.length > 0
  const reviewErrors = hasPluginReviewErrors(preview.inspection)

  return (
    <section className={`${pinActions ? 'flex h-full min-h-0 flex-col' : 'mt-5'} rounded-xl border border-(--color-border) bg-(--bg-panel) p-4`} aria-labelledby="marketplace-preview-title">
      <div className={pinActions ? 'min-h-0 flex-1 overflow-y-auto' : ''}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 id="marketplace-preview-title" className="text-base font-semibold text-(--color-text)">
              Review {preview.plugin.name}
            </h3>
            <p className="mt-1 text-sm text-(--color-text-muted)">
              Nothing is installed until you confirm. Marketplace plugins are installed disabled.
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {hasSupported && <div className="rounded-lg border border-(--color-border) p-3">
            <p className="text-xs font-semibold tracking-wide text-(--color-text-muted)">Supported components</p>
            <p className="mt-1 text-sm text-(--color-text)">{preview.supported_components.join(', ')}</p>
          </div>}
          {hasUnsupported && <div className="rounded-lg border border-(--color-border) p-3">
            <p className="text-xs font-semibold tracking-wide text-(--color-text-muted)">Not imported</p>
            <p className="mt-1 text-sm text-(--color-text)">{preview.unsupported_components.join(', ')}</p>
          </div>}
        </div>
        {preview.warnings.length > 0 && <details className="mt-3 rounded-lg border border-(--color-border) px-3 py-2">
          <summary className="cursor-pointer text-sm font-medium text-(--color-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)">Technical details</summary>
          <ul className="mt-3 space-y-1 text-sm text-(--color-warning)" aria-label="Marketplace warnings">
            {preview.warnings.map((warning) => <li key={warning} className="flex gap-2"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{warning}</li>)}
          </ul>
        </details>}
        {hasUnsupported && hasSupported && (
          <label className="mt-4 flex cursor-pointer items-start gap-2 text-sm text-(--color-text)">
            <input
              type="checkbox"
              aria-label="Install only the supported components"
              checked={allowPartial}
              onChange={(event) => setAllowPartial(event.target.checked)}
              className="mt-0.5 accent-(--color-accent)"
            />
            Install only the supported components; leave unsupported components out.
          </label>
        )}
        {!hasSupported && (
          <p className="mt-4 text-sm text-(--color-error)" role="alert">
            This package has no components that EvoFlux can safely install.
          </p>
        )}
        <div className="mt-4 space-y-4">
          <PluginInspectionDetails inspection={preview.inspection} />
          <PluginPackageFiles key={preview.preview_id} target="preview" id={preview.preview_id} onReviewReady={setFilesReady} />
          {reviewErrors && <p role="alert" className="text-sm text-destructive">Installation is blocked by validation errors. Review the diagnostics above.</p>}
        </div>
      </div>
      <div className={`${pinActions ? 'sticky bottom-0 shrink-0 border-t border-(--color-border) bg-(--bg-panel) py-3' : 'mt-4'} flex flex-wrap items-center justify-end gap-2`}>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button disabled={busy || !filesReady || reviewErrors || !hasSupported || (hasUnsupported && !allowPartial)} onClick={() => onInstall(allowPartial)}>
          {busy && <LoaderCircle className="size-4 animate-spin" />}
          Install supported parts
        </Button>
      </div>
    </section>
  )
}

export function PluginMarketplaceBrowser({ onInstalled }: PluginMarketplaceBrowserProps) {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<MarketplaceKind>('agent_plugins')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [search, setSearch] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [selectedPluginId, setSelectedPluginId] = useState<string | null>(null)
  const [wideCatalog, setWideCatalog] = useState(false)
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [componentFilter, setComponentFilter] = useState('all')
  const [compatibilityFilter, setCompatibilityFilter] = useState('all')
  const activeFilterCount = [sourceFilter !== '', categoryFilter !== 'all', componentFilter !== 'all', compatibilityFilter !== 'all'].filter(Boolean).length
  const preparationRequest = useRef(0)
  const [reviewedPlugins, setReviewedPlugins] = useState<Record<string, MarketplacePlugin>>({})
  const [preview, setPreview] = useState<MarketplacePluginPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busySourceId, setBusySourceId] = useState<string | null>(null)
  const [preparingPluginId, setPreparingPluginId] = useState<string | null>(null)
  const [installing, setInstalling] = useState(false)
  const catalogRef = useRef<HTMLDivElement>(null)

  const sourcesQuery = useQuery({
    queryKey: queryKeys.plugins.marketplaces(),
    queryFn: listMarketplaces,
  })
  const sources = sourcesQuery.data ?? []
  const sourceCount = sources.length
  // null = not user-touched yet: open automatically only while no sources exist.
  const [manageOpen, setManageOpen] = useState<boolean | null>(null)
  const searchQuery = useQuery({
    queryKey: queryKeys.plugins.marketplaceSearch(search.trim(), sourceFilter || undefined),
    queryFn: () => searchMarketplacePlugins(search, sourceFilter || undefined),
    enabled: sources.length > 0,
  })
  const catalogPlugins = useMemo(() => searchQuery.data ?? [], [searchQuery.data])
  const classifiedPlugins = useMemo(() => catalogPlugins.map((plugin) => reviewedPlugins[plugin.id] ?? plugin), [catalogPlugins, reviewedPlugins])
  const categories = [...new Set(classifiedPlugins.flatMap((plugin) => plugin.categories ?? []))].sort()
  const plugins = useMemo(() => classifiedPlugins.filter((plugin) => matchesMarketplaceFilters(plugin, { category: categoryFilter, component: componentFilter, compatibility: compatibilityFilter })), [classifiedPlugins, categoryFilter, componentFilter, compatibilityFilter])
  const selectedPlugin = useMemo(
    () => classifiedPlugins.find((plugin) => plugin.id === selectedPluginId) ?? null,
    [classifiedPlugins, selectedPluginId],
  )

  useEffect(() => {
    const element = catalogRef.current
    if (!element || typeof ResizeObserver === 'undefined') return

    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWideCatalog(entry.contentRect.width >= 880)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [plugins.length])

  useEffect(() => {
    if (selectedPluginId && !classifiedPlugins.some((plugin) => plugin.id === selectedPluginId)) {
      setSelectedPluginId(null)
      setPreview(null)
    }
  }, [classifiedPlugins, selectedPluginId])

  const addMutation = useMutation({
    mutationFn: (request: MarketplaceCreateRequest) => addMarketplace(request),
    onSuccess: async () => {
      setName('')
      setUrl('')
      setError(null)
      await queryClient.invalidateQueries({ queryKey: queryKeys.plugins.marketplaces() })
    },
    onError: (cause) => setError(errorMessage(cause)),
  })

  const submitMarketplace = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError(null)
    addMutation.mutate({ kind, name: name.trim(), url: url.trim() })
  }

  const closePluginDetails = () => {
    preparationRequest.current += 1
    setPreparingPluginId(null)
    setSelectedPluginId(null)
    setPreview(null)
  }

  const runSourceAction = async (id: string, action: () => Promise<unknown>) => {
    setBusySourceId(id)
    setError(null)
    try {
      await action()
      preparationRequest.current += 1
      setPreparingPluginId(null)
      setPreview(null)
      setReviewedPlugins({})
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.plugins.marketplaces() }),
        queryClient.invalidateQueries({ queryKey: ['plugins', 'marketplaces', 'search'] }),
      ])
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setBusySourceId(null)
    }
  }

  const prepare = async (plugin: MarketplacePlugin) => {
    const request = ++preparationRequest.current
    setPreparingPluginId(plugin.id)
    setPreview(null)
    setError(null)
    try {
      const result = await prepareMarketplacePlugin(plugin.marketplace_id, plugin.name)
      if (request !== preparationRequest.current) return
      setReviewedPlugins((current) => ({ ...current, [plugin.id]: { ...result.plugin, components: [...result.supported_components, ...result.unsupported_components], compatibility: hasPluginReviewErrors(result.inspection) ? 'unsupported' : result.plugin.compatibility } }))
      setPreview(result)
    } catch (cause) {
      if (request === preparationRequest.current) setError(errorMessage(cause))
    } finally {
      if (request === preparationRequest.current) setPreparingPluginId(null)
    }
  }

  const install = async (allowPartial: boolean) => {
    if (!preview || hasPluginReviewErrors(preview.inspection)) return
    setInstalling(true)
    setError(null)
    try {
      const result = await installMarketplacePlugin(preview.preview_id, allowPartial)
      setPreview(null)
      setSelectedPluginId(null)
      await queryClient.invalidateQueries({ queryKey: queryKeys.plugins.list() })
      onInstalled(result)
    } catch (cause) {
      setError(errorMessage(cause))
    } finally {
      setInstalling(false)
    }
  }

  const selectedContent = selectedPlugin
    ? preview
      ? (
        <MarketplacePreview
          key={preview.preview_id}
          preview={preview}
          busy={installing}
          onCancel={() => setPreview(null)}
          onInstall={(allowPartial) => void install(allowPartial)}
           pinActions={true}
        />
      )
      : (
        <MarketplacePluginDetails
          plugin={selectedPlugin}
          busy={preparingPluginId === selectedPlugin.id}
          onPrepare={() => void prepare(selectedPlugin)}
          showTitle={wideCatalog}
           marketplaceKind={sources.find((source) => source.id === selectedPlugin.marketplace_id)?.kind}
           pinActions={true}
        />
      )
    : null

  return (
    <div className="@container/marketplace min-w-0 space-y-6" aria-label="Plugin marketplace">
      <details open={manageOpen ?? sourceCount === 0} className="rounded-xl border border-(--color-border) bg-(--bg-panel) px-4 py-3">
        <summary
          onClick={(event) => {
            // Controlled disclosure: suppress the native toggle so React state alone owns `open`.
            event.preventDefault()
            setManageOpen(!(manageOpen ?? sourceCount === 0))
          }}
          className="cursor-pointer text-sm font-semibold text-(--color-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)"
        >
          Manage marketplaces
        </summary>
      <section className="mt-3 grid min-w-0 items-start gap-4 @4xl/marketplace:grid-cols-[minmax(16rem,0.85fr)_minmax(20rem,1.15fr)]">
        <div className="min-w-0 rounded-xl border border-(--color-border) bg-(--bg-panel) p-4">
          <h2 className="text-base font-semibold text-(--color-text)">Add a marketplace</h2>
          <p className="mt-1 text-sm text-(--color-text-muted)">
            Add an Agent Plugins 1.0.0 or Claude Code marketplace URL. Sources are fetched only when you sync them.
          </p>
          <form className="mt-4 space-y-3" onSubmit={submitMarketplace}>
            <label className="block space-y-1 text-sm text-(--color-text-muted)">
              <span>Format</span>
              <SelectControl
                id="marketplace-kind"
                ariaLabel="Format"
                value={kind}
                onValueChange={(value) => setKind(value as MarketplaceKind)}
                options={[
                  { value: 'agent_plugins', label: 'Agent Plugins 1.0.0' },
                  { value: 'claude_code', label: 'Claude Code marketplace' },
                ]}
              />
            </label>
            <label className="block space-y-1 text-sm text-(--color-text-muted)" htmlFor="marketplace-name">
              Marketplace name
              <Input id="marketplace-name" value={name} onChange={(event) => setName(event.target.value)} required maxLength={120} />
            </label>
            <label className="block space-y-1 text-sm text-(--color-text-muted)" htmlFor="marketplace-url">
              Marketplace URL
              <Input id="marketplace-url" type="url" value={url} onChange={(event) => setUrl(event.target.value)} required maxLength={2048} placeholder="https://example.com/marketplace.json" />
            </label>
            <Button type="submit" disabled={addMutation.isPending || !name.trim() || !url.trim()}>
              {addMutation.isPending && <LoaderCircle className="size-4 animate-spin" />}
              Add marketplace
            </Button>
          </form>
        </div>

        <div className="min-w-0 rounded-xl border border-(--color-border) bg-(--bg-panel) p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-(--color-text)">Marketplace sources</h2>
              <p className="mt-1 text-sm text-(--color-text-muted)">Sync a source to refresh its searchable catalog.</p>
            </div>
            {sourcesQuery.isFetching && <LoaderCircle className="size-4 animate-spin text-(--color-text-muted)" aria-label="Loading marketplaces" />}
          </div>
          {sourcesQuery.isError && <p className="mt-3 text-sm text-(--color-error)" role="alert">{errorMessage(sourcesQuery.error)}</p>}
          {!sourcesQuery.isLoading && sources.length === 0 && (
            <p className="mt-4 rounded-lg border border-dashed border-(--color-border) p-4 text-sm text-(--color-text-muted)">
              No marketplace sources yet.
            </p>
          )}
          {sources.length > 0 && (
            <ul className="mt-2">
              {sources.map((source) => (
                <MarketplaceRow
                  key={source.id}
                  source={source}
                  busy={busySourceId === source.id}
                  onSync={() => void runSourceAction(source.id, () => syncMarketplace(source.id))}
                  onRemove={() => void runSourceAction(source.id, () => removeMarketplace(source.id))}
                />
              ))}
            </ul>
          )}
        </div>
      </section>
      </details>

      <section className="rounded-xl border border-(--color-border) bg-(--bg-panel) p-4" aria-labelledby="marketplace-catalog-title">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="marketplace-catalog-title" className="text-base font-semibold text-(--color-text)">Browse plugins</h2>
            <p className="mt-1 text-sm text-(--color-text-muted)">
              Only compatible skills and MCP configuration are imported from Claude Code plugins; unsupported components remain untouched.
            </p>
            {plugins.length > 0 && selectedPlugin === null && (
              <p className="mt-1 text-xs text-(--color-text-muted)">
                Select a result to review compatibility and installation details.
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <label className="relative min-w-48 flex-1" htmlFor="marketplace-search">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-(--color-text-muted)" />
              <Input
                id="marketplace-search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="pl-9"
                placeholder="Search plugins"
              />
            </label>
          </div>
        </div>
        {error && <p className="mt-3 text-sm text-(--color-error)" role="alert">{error}</p>}
        {sources.length === 0 && (
          <p className="mt-4 rounded-lg border border-dashed border-(--color-border) p-4 text-sm text-(--color-text-muted)">
            Add a marketplace source above before browsing its plugins.
          </p>
        )}
        {sources.length > 0 && <details className="mt-3 rounded-lg border border-(--color-border) px-3 py-2">
          <summary className="cursor-pointer text-sm font-medium text-(--color-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)">Filters{activeFilterCount > 0 && ` (${activeFilterCount} active)`}</summary>
          <div className="mt-3 space-y-2">
          <div className="grid grid-cols-1 gap-2 @lg/plugin-center:grid-cols-2 @4xl/plugin-center:grid-cols-4">
            <SelectControl id="marketplace-source-filter" ariaLabel="Marketplace source" value={sourceFilter} onValueChange={setSourceFilter} options={[{ value: '', label: 'All marketplaces' }, ...sources.map((source) => ({ value: source.id, label: source.name }))]} />
            <SelectControl id="marketplace-category-filter" ariaLabel="Filter by category" value={categoryFilter} onValueChange={setCategoryFilter} options={[{ value: 'all', label: 'All categories' }, ...categories.map((category) => ({ value: category, label: category })), { value: 'uncategorized', label: 'Uncategorized' }]} />
            <SelectControl id="marketplace-component-filter" ariaLabel="Filter by component" value={componentFilter} onValueChange={setComponentFilter} options={[{ value: 'all', label: 'All components' }, { value: 'skills', label: 'Skills' }, { value: 'mcp', label: 'MCP' }, { value: 'other', label: 'Other components' }, { value: 'unknown', label: 'Not declared' }]} />
            <SelectControl id="marketplace-compatibility-filter" ariaLabel="Filter by compatibility" value={compatibilityFilter} onValueChange={setCompatibilityFilter} options={[{ value: 'all', label: 'All compatibility states' }, { value: 'compatible', label: 'Compatible' }, { value: 'partial', label: 'Partially compatible' }, { value: 'unsupported', label: 'Unsupported' }, { value: 'unknown', label: 'Not inspected' }]} />
          </div>
          <p className="text-xs text-(--color-text-subtle)">{plugins.length} of {classifiedPlugins.length} matching catalog entries. Categories come from the catalog; undeclared components stay unknown until inspected.</p>
          {(sourceFilter || categoryFilter !== 'all' || componentFilter !== 'all' || compatibilityFilter !== 'all') && <Button variant="ghost" size="sm" onClick={() => { setSourceFilter(''); setCategoryFilter('all'); setComponentFilter('all'); setCompatibilityFilter('all') }}>Reset filters</Button>}
          </div>
        </details>}
        {sources.length > 0 && searchQuery.isLoading && (
          <p className="mt-4 flex items-center gap-2 text-sm text-(--color-text-muted)"><LoaderCircle className="size-4 animate-spin" />Loading marketplace catalog…</p>
        )}
        {searchQuery.isError && <p className="mt-4 text-sm text-(--color-error)" role="alert">{errorMessage(searchQuery.error)}</p>}
        {sources.length > 0 && !searchQuery.isLoading && !searchQuery.isError && plugins.length === 0 && (
          <p className="mt-4 rounded-lg border border-dashed border-(--color-border) p-4 text-sm text-(--color-text-muted)">
            {activeFilterCount > 0 || search.trim()
              ? 'No plugins match the current search and filters.'
              : 'No plugins yet. Sync a marketplace to populate the catalog.'}
          </p>
        )}
        {plugins.length > 0 && (
          <div ref={catalogRef} className="mt-3 min-w-0">
            <div className={`grid min-w-0 gap-4 ${wideCatalog && selectedPlugin !== null
              ? 'grid-cols-[minmax(0,1fr)_minmax(19rem,1.15fr)]'
              : 'grid-cols-1'
            }`}>
              <ul
                aria-label="Marketplace plugins"
                className="min-w-0 divide-y divide-(--color-border) border-y border-(--color-border)"
              >
                {plugins.map((plugin) => (
                  <MarketplacePluginRow
                    key={plugin.id}
                    plugin={plugin}
                    sourceName={sources.find((source) => source.id === plugin.marketplace_id)?.name}
                    selected={selectedPluginId === plugin.id}
                    onSelect={() => {
                      preparationRequest.current += 1
                      setPreparingPluginId(null)
                      setSelectedPluginId(plugin.id)
                      setPreview(null)
                    }}
                  />
                ))}
              </ul>
              {wideCatalog && selectedPlugin !== null && (
          <aside
            aria-label={`Selected details for ${selectedPlugin.name}`}
            className={`sticky top-4 min-h-0 self-start ${preview ? 'h-[calc(100dvh-8rem)] overflow-hidden' : 'max-h-[calc(100dvh-8rem)] overflow-y-auto'}`}
          >
            {selectedContent}
          </aside>
        )}
            </div>
          </div>
        )}
      </section>
      <Sheet
        open={!wideCatalog && selectedPlugin !== null}
        onOpenChange={(open) => {
          if (!open) closePluginDetails()
        }}
      >
        <SheetContent side="right" className="w-[min(36rem,92vw)] max-w-none gap-0 p-0">
          {selectedPlugin && (
            <>
              <SheetHeader className="border-b border-(--color-border) pr-12">
                <SheetTitle>{selectedPlugin.name}</SheetTitle>
                <SheetDescription>
                  {preview
                    ? 'Review supported and unsupported components before installing.'
                    : 'Review compatibility and package details before installation.'}
                </SheetDescription>
              </SheetHeader>
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4">
                {selectedContent}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}
