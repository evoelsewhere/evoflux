import { describe, expect, it } from 'vitest'
import type { MarketplacePlugin, PluginInstallation, PluginInspection } from '@/api/types'
import { pluginOriginKind, pluginOriginLabel, matchesMarketplaceFilters, hasPluginReviewErrors } from '@/utils/plugin-catalog'

const catalog = { name: 'sample', components: ['skills'], compatibility: 'compatible', categories: ['Data'], keywords: ['sql'] } as MarketplacePlugin
const installation = { source_type: 'installed' } as PluginInstallation

describe('plugin catalog classification', () => {
  it('does not pretend old installed packages came from a marketplace or file import', () => {
    expect(pluginOriginKind(installation)).toBe('unknown')
    expect(pluginOriginLabel(installation)).toBe('Unknown origin')
    expect(pluginOriginKind({ ...installation, source_type: 'linked' })).toBe('development_link')
    expect(pluginOriginKind({ ...installation, source_type: 'builtin' })).toBe('builtin')
  })

  it('shows marketplace name and distinguishes local archive, directory, and dev link', () => {
    expect(pluginOriginLabel({ ...installation, origin: { kind: 'marketplace', marketplace_name: 'Official catalog' } })).toBe('Marketplace · Official catalog')
    expect(pluginOriginLabel({ ...installation, origin: { kind: 'import_archive' } })).toBe('Imported archive')
    expect(pluginOriginLabel({ ...installation, origin: { kind: 'import_directory' } })).toBe('Imported directory')
  })

  it('filters catalog metadata without inventing unknown categories or components', () => {
    expect(matchesMarketplaceFilters(catalog, { category: 'Data', component: 'skills', compatibility: 'compatible' })).toBe(true)
    expect(matchesMarketplaceFilters(catalog, { category: 'Design', component: 'all', compatibility: 'all' })).toBe(false)
    const unknown = { ...catalog, categories: [], components: [], compatibility: 'unknown' } as MarketplacePlugin
    expect(matchesMarketplaceFilters(unknown, { category: 'uncategorized', component: 'unknown', compatibility: 'unknown' })).toBe(true)
    expect(matchesMarketplaceFilters(unknown, { category: 'all', component: 'mcp', compatibility: 'all' })).toBe(false)
  })

  it('blocks component validation errors even when package manifest is valid', () => {
    const inspection = { valid: true, diagnostics: [], skills: [{ valid: false, diagnostics: [{ severity: 'error', message: 'Invalid Skill' }] }], mcp_servers: [] } as unknown as PluginInspection
    expect(hasPluginReviewErrors(inspection)).toBe(true)
  })
})
