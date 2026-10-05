import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { PluginMarketplaceBrowser } from '@/components/PluginMarketplaceBrowser'

const marketplaceApi = vi.hoisted(() => ({
  addMarketplace: vi.fn(),
  installMarketplacePlugin: vi.fn(),
  listMarketplaces: vi.fn(),
  getPluginPackageReview: vi.fn(),
  getPluginPackageFile: vi.fn(),
  prepareMarketplacePlugin: vi.fn(),
  removeMarketplace: vi.fn(),
  searchMarketplacePlugins: vi.fn(),
  syncMarketplace: vi.fn(),
}))

vi.mock('@/api/client', () => marketplaceApi)

const source = {
  id: '0123456789abcdef',
  kind: 'claude_code',
  name: 'Research tools',
  url: 'https://example.test/marketplace.json',
  added_at: '2026-09-01T00:00:00Z',
  last_synced_at: '2026-09-02T00:00:00Z',
  last_error: null,
}

const plugin = {
  id: '0123456789abcdef:research-skills',
  marketplace_id: source.id,
  name: 'research-skills',
  description: 'Research skills for Claude Code',
  version: '1.0.0',
  author: 'Example Author',
  source_type: 'github',
  source_url: 'https://example.test/research-skills',
  source_path: null,
  source_ref: null,
  components: ['skills', 'hooks'],
  compatibility: 'partial',
  installable: true,
  verification: 'unverified',
  artifact_sha256: null,
  artifact_size: null,
}

const preview = {
  preview_id: 'a'.repeat(32),
  plugin,
  supported_components: ['skills'],
  unsupported_components: ['hooks'],
  warnings: ['Hooks are not imported or executed.'],
  inspection: { valid: true, diagnostics: [] },
}

function renderBrowser(onInstalled = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <PluginMarketplaceBrowser onInstalled={onInstalled} />
    </QueryClientProvider>,
  )
}

describe('PluginMarketplaceBrowser', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: { clear: vi.fn() },
    })
    Object.values(marketplaceApi).forEach((mock) => mock.mockReset())
    marketplaceApi.getPluginPackageReview.mockResolvedValue({ files: [], truncated: false, readme: null })
    marketplaceApi.listMarketplaces.mockResolvedValue([source])
    marketplaceApi.searchMarketplacePlugins.mockResolvedValue([plugin])
    marketplaceApi.prepareMarketplacePlugin.mockResolvedValue(preview)
    marketplaceApi.installMarketplacePlugin.mockResolvedValue({
      installation: { enabled: false },
      inspection: { valid: true, trust: { capabilities: [] } },
    })
    marketplaceApi.addMarketplace.mockResolvedValue(source)
    marketplaceApi.syncMarketplace.mockResolvedValue(source)
    marketplaceApi.removeMarketplace.mockResolvedValue(source)
  })

  it('opens marketplace management for initial setup when no sources exist', async () => {
    marketplaceApi.listMarketplaces.mockResolvedValue([])
    renderBrowser()

    expect(await screen.findByRole('heading', { name: 'Add a marketplace' })).toBeVisible()
    expect(screen.getByText('Manage marketplaces').closest('details')).toHaveAttribute('open')
  })

  it('keeps marketplace management collapsed once sources are configured', async () => {
    marketplaceApi.listMarketplaces.mockResolvedValue([source])
    renderBrowser()

    await screen.findByRole('button', { name: 'View details for research-skills' })
    expect(screen.getByText('Manage marketplaces').closest('details')).not.toHaveAttribute('open')
    expect(screen.getByRole('heading', { name: 'Add a marketplace' })).not.toBeVisible()
  })

  it('shows the active filter count in the closed filters summary', async () => {
    renderBrowser()
    const disclosure = await screen.findByText('Filters').then((node) => node.closest('details'))
    fireEvent.click(screen.getByText('Filters'))
    fireEvent.click(screen.getByRole('combobox', { name: 'Filter by component' }))
    const skillsOption = await screen.findByRole('option', { name: 'Skills' })
    fireEvent.focus(skillsOption)
    fireEvent.click(skillsOption)
    fireEvent.click(disclosure!.querySelector('summary')!)

    expect(disclosure).not.toHaveAttribute('open')
    expect(disclosure!.querySelector('summary')).toHaveTextContent('(1 active)')
    expect(screen.getByRole('button', { name: 'Reset filters' })).not.toBeVisible()
    fireEvent.click(disclosure!.querySelector('summary')!)
    expect(screen.getByRole('button', { name: 'Reset filters' })).toBeVisible()
  })

  it('reviews partial compatibility and requires explicit consent before installing supported components', async () => {
    const onInstalled = vi.fn()
    renderBrowser(onInstalled)

    expect(await screen.findByText('research-skills')).toBeVisible()
    expect(screen.getByText(/partial compatibility/i)).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'View details for research-skills' }))
    fireEvent.click(screen.getByRole('button', { name: /inspect package/i }))

    const warning = await screen.findByText('Hooks are not imported or executed.')
    const packageFiles = screen.getByText('Package files').closest('details')
    expect(packageFiles).not.toBeNull()
    expect(packageFiles).not.toHaveAttribute('open')
    await waitFor(() => expect(marketplaceApi.getPluginPackageReview).toHaveBeenCalledWith('preview', preview.preview_id))

    const warningDetails = warning.closest('details')
    expect(warningDetails).not.toBeNull()
    fireEvent.click(warningDetails!.querySelector('summary')!)
    expect(warning).toBeVisible()
    expect(screen.getByText('Supported components')).toBeVisible()
    expect(screen.getByText('Not imported')).toBeVisible()
    expect(screen.getByText('skills')).toBeVisible()
    expect(screen.getByText('hooks')).toBeVisible()
    const installButton = screen.getByRole('button', { name: /install supported parts/i })
    expect(installButton).toBeDisabled()

    fireEvent.click(screen.getByRole('checkbox', { name: /install only the supported components/i }))
    expect(installButton).toBeEnabled()
    expect(packageFiles).not.toHaveAttribute('open')
    fireEvent.click(installButton)

    await waitFor(() => expect(marketplaceApi.installMarketplacePlugin).toHaveBeenCalledWith(preview.preview_id, true))
    expect(onInstalled).toHaveBeenCalledWith(expect.objectContaining({
      installation: expect.objectContaining({ enabled: false }),
    }))
  })

  it('lets compatible Claude sources enter preview when catalog metadata cannot identify components', async () => {
    marketplaceApi.searchMarketplacePlugins.mockResolvedValue([{
      ...plugin,
      components: [],
      compatibility: 'unknown',
      installable: true,
    }])
    renderBrowser()

    fireEvent.click(await screen.findByRole('button', { name: 'View details for research-skills' }))
    expect(screen.getByRole('note')).toHaveTextContent(/unverified.*not an installability check/i)
    fireEvent.click(screen.getByRole('button', { name: /inspect package/i }))

    await waitFor(() => expect(marketplaceApi.prepareMarketplacePlugin).toHaveBeenCalledWith(
      source.id,
      plugin.name,
    ))
    expect(await screen.findByText('Review research-skills')).toBeVisible()
  })

  it('adds marketplace sources without enabling imported plugins', async () => {
    marketplaceApi.listMarketplaces.mockResolvedValue([])
    marketplaceApi.searchMarketplacePlugins.mockResolvedValue([])
    renderBrowser()

    fireEvent.change(screen.getByLabelText('Marketplace name'), { target: { value: 'Research tools' } })
    fireEvent.change(screen.getByLabelText('Marketplace URL'), {
      target: { value: 'https://example.test/marketplace.json' },
    })
    fireEvent.click(screen.getByRole('button', { name: /add marketplace/i }))

    await waitFor(() => expect(marketplaceApi.addMarketplace).toHaveBeenCalledWith({
      kind: 'agent_plugins',
      name: 'Research tools',
      url: 'https://example.test/marketplace.json',
    }))
  })

  it('keeps catalog search prominent while marketplace controls stay progressively disclosed', async () => {
    renderBrowser()

    expect(screen.getByPlaceholderText('Search plugins')).toBeVisible()
    expect(screen.getByText('Manage marketplaces')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Add a marketplace' })).toBeVisible()
    const filters = await screen.findByText('Filters')
    fireEvent.click(filters)
    expect(screen.getByRole('combobox', { name: 'Filter by category' })).toBeVisible()
  })

  it('sizes marketplace source-management cards from the panel container', async () => {
    renderBrowser()
    fireEvent.click(screen.getByText('Manage marketplaces'))

    const marketplace = screen.getByLabelText('Plugin marketplace')
    const setupCard = screen.getByRole('heading', { name: 'Add a marketplace' }).closest('div.rounded-xl')
    const sourcesCard = screen.getByRole('heading', { name: 'Marketplace sources' }).closest('div.rounded-xl')

    expect(marketplace).toHaveClass('@container/marketplace')
    expect(setupCard).toHaveClass('min-w-0')
    expect(sourcesCard).toHaveClass('min-w-0')
    expect(setupCard?.parentElement).toHaveClass('items-start')
    expect(setupCard?.parentElement).toHaveClass(
      '@4xl/marketplace:grid-cols-[minmax(16rem,0.85fr)_minmax(20rem,1.15fr)]',
    )
  })

  it('browses catalog entries as a compact list and opens selected plugin details', async () => {
    marketplaceApi.searchMarketplacePlugins.mockResolvedValue([
      plugin,
      {
        ...plugin,
        id: `${source.id}:mcp-tools`,
        name: 'mcp-tools',
        description: 'Configuration tools for MCP servers',
      },
    ])
    renderBrowser()

    const list = await screen.findByRole('list', { name: 'Marketplace plugins' })
    expect(list).toBeVisible()
    expect(screen.getByText('RS')).toBeVisible()
    expect(screen.getByText('MT')).toBeVisible()
    const secondPlugin = screen.getByRole('button', { name: 'View details for mcp-tools' })
    expect(secondPlugin).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(secondPlugin)

    const details = await screen.findByRole('dialog')
    expect(details).toHaveTextContent('mcp-tools')
    expect(details).toHaveTextContent('Configuration tools for MCP servers')
    expect(secondPlugin).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /inspect package/i })).toBeVisible()
  })

  it('uses an inline detail panel when the marketplace container is wide', async () => {
    class MockResizeObserver {
      private readonly callback: ResizeObserverCallback

      constructor(callback: ResizeObserverCallback) {
        this.callback = callback
      }

      observe(target: Element) {
        this.callback(
          [{ target, contentRect: { width: 900 } as DOMRectReadOnly } as ResizeObserverEntry],
          this as unknown as ResizeObserver,
        )
      }

      unobserve() {}
      disconnect() {}
    }

    vi.stubGlobal('ResizeObserver', MockResizeObserver)
    try {
      renderBrowser()
      const list = await screen.findByRole('list', { name: 'Marketplace plugins' })
      expect(list.parentElement).toHaveClass('grid-cols-1')
      expect(screen.queryByText('Select a plugin to review its details and compatibility.')).not.toBeInTheDocument()
      expect(screen.getByText('Select a result to review compatibility and installation details.')).toBeVisible()
      fireEvent.click(screen.getByRole('button', { name: 'View details for research-skills' }))

      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      expect(screen.queryByText('Select a result to review compatibility and installation details.')).not.toBeInTheDocument()
      expect(list.parentElement).toHaveClass('grid-cols-[minmax(0,1fr)_minmax(19rem,1.15fr)]')
      expect(screen.getByRole('region', { name: 'Details for research-skills' })).toBeVisible()
      const selectedPanel = screen.getByRole('complementary', { name: 'Selected details for research-skills' })
      expect(selectedPanel).toHaveClass('sticky', 'top-4', 'max-h-[calc(100dvh-8rem)]', 'overflow-y-auto')
      expect(screen.getByRole('button', { name: /inspect package/i }).parentElement).toHaveClass('sticky', 'bottom-0')

      fireEvent.click(screen.getByRole('button', { name: /inspect package/i }))
      const reviewTitle = await screen.findByRole('heading', { name: 'Review research-skills' })
      expect(selectedPanel).toHaveClass('h-[calc(100dvh-8rem)]', 'overflow-hidden')
      const review = reviewTitle.closest('section')
      expect(review).toHaveClass('h-full', 'min-h-0', 'flex', 'flex-col')
      const reviewContent = review?.querySelector(':scope > div.min-h-0.flex-1.overflow-y-auto')
      expect(reviewContent).toContainElement(screen.getByText(/Nothing is installed until you confirm/))

      const installButton = screen.getByRole('button', { name: 'Install supported parts' })
      expect(installButton).toBeDisabled()
      expect(installButton.parentElement).toHaveClass('sticky', 'bottom-0', 'shrink-0')
      fireEvent.click(screen.getByRole('checkbox', { name: 'Install only the supported components' }))
      await waitFor(() => expect(installButton).toBeEnabled())
      expect(marketplaceApi.installMarketplacePlugin).not.toHaveBeenCalled()
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('explains why unsupported Claude Code sources cannot be installed', async () => {
    marketplaceApi.listMarketplaces.mockResolvedValue([{ ...source, kind: 'claude_code' }])
    marketplaceApi.searchMarketplacePlugins.mockResolvedValue([{
      ...plugin,
      source_type: 'npm',
      compatibility: 'unsupported',
      installable: false,
      verification: 'unverified',
    }])
    renderBrowser()

    fireEvent.click(await screen.findByRole('button', { name: 'View details for research-skills' }))

    expect(screen.getByText(/does not yet install npm-sourced Claude Code plugins/i)).toBeVisible()
    expect(screen.getByRole('note')).toHaveTextContent(/unverified.*not an installability check/i)
    expect(screen.getByRole('button', { name: 'Not installable' })).toBeDisabled()
  })

  it('explains the portability requirements for Agent Plugins', async () => {
    marketplaceApi.listMarketplaces.mockResolvedValue([{ ...source, kind: 'agent_plugins' }])
    marketplaceApi.searchMarketplacePlugins.mockResolvedValue([{
      ...plugin,
      source_type: 'artifact',
      compatibility: 'unsupported',
      installable: false,
      verification: 'unverified',
    }])
    renderBrowser()

    fireEvent.click(await screen.findByRole('button', { name: 'View details for research-skills' }))

    expect(screen.getByText(/declared portable to EvoFlux.*portable: true.*Skills or MCP/i)).toBeVisible()
  })

  it('filters categories and components instead of treating unknown packages as supported', async () => {
    marketplaceApi.searchMarketplacePlugins.mockResolvedValue([
      { ...plugin, categories: ['Design'], components: ['skills'] },
      { ...plugin, id: 'docs', name: 'docs', categories: ['Data'], components: ['mcp'] },
    ])
    renderBrowser()
    await screen.findByRole('button', { name: 'View details for docs' })
    fireEvent.click(screen.getByText('Filters'))
    fireEvent.click(screen.getByRole('combobox', { name: 'Filter by category' }))
    const categoryOption = await screen.findByRole('option', { name: 'Data' })
    fireEvent.focus(categoryOption)
    fireEvent.click(categoryOption)
    await waitFor(() => expect(screen.queryByRole('button', { name: 'View details for research-skills' })).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'View details for docs' })).toBeVisible()
    fireEvent.click(screen.getByRole('combobox', { name: 'Filter by component' }))
    const componentOption = await screen.findByRole('option', { name: 'Skills' })
    fireEvent.focus(componentOption)
    fireEvent.click(componentOption)
    await waitFor(() => expect(screen.queryByRole('button', { name: 'View details for docs' })).not.toBeInTheDocument())
  })

  it('does not offer installation when package files cannot be reviewed', async () => {
    marketplaceApi.getPluginPackageReview.mockRejectedValue(new Error('Package review unavailable'))
    renderBrowser()
    fireEvent.click(await screen.findByRole('button', { name: 'View details for research-skills' }))
    fireEvent.click(screen.getByRole('button', { name: 'Inspect package' }))
    await screen.findByText('Package review unavailable')
    fireEvent.click(screen.getByRole('checkbox'))
    expect(screen.getByRole('button', { name: 'Install supported parts' })).toBeDisabled()
  })

  it('ignores a stale inspection result after another package is selected', async () => {
    let resolvePreview!: (value: typeof preview) => void
    marketplaceApi.prepareMarketplacePlugin.mockImplementation(() => new Promise((resolve) => { resolvePreview = resolve }))
    marketplaceApi.searchMarketplacePlugins.mockResolvedValue([plugin, { ...plugin, id: 'docs', name: 'docs' }])
    renderBrowser()
    fireEvent.click(await screen.findByRole('button', { name: 'View details for research-skills' }))
    fireEvent.click(screen.getByRole('button', { name: 'Inspect package' }))
    await waitFor(() => expect(marketplaceApi.prepareMarketplacePlugin).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    fireEvent.click(screen.getByRole('button', { name: 'View details for docs' }))
    await act(async () => { resolvePreview(preview) })
    expect(screen.queryByRole('button', { name: 'Install supported parts' })).not.toBeInTheDocument()
  })

  it('blocks installation when a component is invalid even though the manifest parsed', async () => {
    marketplaceApi.prepareMarketplacePlugin.mockResolvedValue({ ...preview, inspection: {
      ...preview.inspection, skills: [{ name: 'bad', path: 'skills/bad/SKILL.md', description: 'Broken skill', valid: false, diagnostics: [{ severity: 'error', code: 'skill-invalid', message: 'Invalid frontmatter', scope: 'skill' }] }], mcp_servers: [],
    } })
    renderBrowser()
    fireEvent.click(await screen.findByRole('button', { name: 'View details for research-skills' }))
    fireEvent.click(screen.getByRole('button', { name: 'Inspect package' }))
    expect(await screen.findByRole('button', { name: 'Install supported parts' })).toBeDisabled()
    expect(screen.getByText(/Invalid frontmatter/)).toBeVisible()
    expect(marketplaceApi.installMarketplacePlugin).not.toHaveBeenCalled()
  })

  it('keeps marketplace management open across re-renders once expanded', async () => {
    renderBrowser()

    const manage = await screen.findByText('Manage marketplaces')
    const details = manage.closest('details')!
    // With one source configured the section starts collapsed once data resolves.
    await waitFor(() => expect(details).not.toHaveAttribute('open'))
    fireEvent.click(manage)
    expect(details).toHaveAttribute('open')

    // A data-triggered re-render must not snap the disclosure shut.
    fireEvent.change(screen.getByPlaceholderText('Search plugins'), { target: { value: 'research' } })
    await waitFor(() => expect(marketplaceApi.searchMarketplacePlugins).toHaveBeenCalled())
    expect(details).toHaveAttribute('open')
  })

  it('pins package actions inside the narrow review drawer', async () => {
    renderBrowser()

    fireEvent.click(await screen.findByRole('button', { name: 'View details for research-skills' }))
    const dialog = await screen.findByRole('dialog')

    const inspect = screen.getByRole('button', { name: 'Inspect package' })
    expect(inspect.parentElement).toHaveClass('sticky', 'bottom-0')

    fireEvent.click(inspect)
    const review = (await screen.findByRole('heading', { name: 'Review research-skills' })).closest('section')!
    expect(review).toHaveClass('h-full', 'min-h-0', 'flex', 'flex-col')
    expect(review.querySelector(':scope > div.min-h-0.flex-1.overflow-y-auto')).not.toBeNull()
    const install = screen.getByRole('button', { name: 'Install supported parts' })
    expect(install.parentElement).toHaveClass('sticky', 'bottom-0', 'shrink-0')
    expect(dialog.querySelector('.flex-1.overflow-hidden')).not.toBeNull()
  })

  it('distinguishes an empty catalog from a filtered-empty catalog', async () => {
    marketplaceApi.searchMarketplacePlugins.mockResolvedValue([])
    renderBrowser()

    expect(await screen.findByText('No plugins yet. Sync a marketplace to populate the catalog.')).toBeVisible()

    fireEvent.change(screen.getByPlaceholderText('Search plugins'), { target: { value: 'zzz' } })
    expect(await screen.findByText('No plugins match the current search and filters.')).toBeVisible()
    expect(screen.queryByText(/Sync a marketplace to populate the catalog/)).not.toBeInTheDocument()
  })
})
