import type { MarketplacePlugin, PluginInstallation, PluginInspection, PluginOrigin } from '@/api/types'

export function pluginOriginKind(installation: PluginInstallation): PluginOrigin['kind'] {
  if (installation.origin) return installation.origin.kind
  if (installation.source_type === 'builtin') return 'builtin'
  if (installation.source_type === 'linked') return 'development_link'
  return 'unknown'
}

export function pluginOriginLabel(installation: PluginInstallation): string {
  const kind = pluginOriginKind(installation)
  if (kind === 'marketplace') return `Marketplace · ${installation.origin?.marketplace_name || installation.origin?.marketplace_id || 'Unknown catalog'}`
  return {
    import_archive: 'Imported archive',
    import_directory: 'Imported directory',
    development_link: 'Development link',
    builtin: 'Built-in',
    unknown: 'Unknown origin',
  }[kind]
}

export function matchesMarketplaceFilters(plugin: MarketplacePlugin, filters: { category: string; component: string; compatibility: string }): boolean {
  const categories = plugin.categories ?? []
  const components = plugin.components.map((value) => value === 'skill' ? 'skills' : value)
  return (filters.category === 'all' || (filters.category === 'uncategorized' ? categories.length === 0 : categories.includes(filters.category)))
    && (filters.component === 'all' || (filters.component === 'unknown' ? components.length === 0 : filters.component === 'other' ? components.some((item) => !['skills', 'mcp'].includes(item)) : components.includes(filters.component)))
    && (filters.compatibility === 'all' || plugin.compatibility === filters.compatibility)
}

export function hasPluginReviewErrors(inspection: PluginInspection): boolean {
  return !inspection.valid || (inspection.diagnostics ?? []).some((item) => item.severity === 'error')
    || (inspection.skills ?? []).some((item) => !item.valid || item.diagnostics.some((entry) => entry.severity === 'error'))
    || (inspection.mcp_servers ?? []).some((item) => !item.valid || item.diagnostics.some((entry) => entry.severity === 'error'))
}
