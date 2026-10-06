import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { PluginCenterPanel } from '@/components/PluginCenterPanel'

const pluginApi = vi.hoisted(() => ({
  addMarketplace: vi.fn(),
  createPlugin: vi.fn(),
  installMarketplacePlugin: vi.fn(),
  listMarketplaces: vi.fn(),
  getPluginPackageReview: vi.fn(),
  getPluginPackageFile: vi.fn(),
  prepareMarketplacePlugin: vi.fn(),
  removeMarketplace: vi.fn(),
  searchMarketplacePlugins: vi.fn(),
  syncMarketplace: vi.fn(),
  importPlugin: vi.fn(),
  inspectPlugin: vi.fn(),
  listPlugins: vi.fn(),
  packPlugin: vi.fn(),
  setPluginEnabled: vi.fn(),
  uninstallPlugin: vi.fn(),
  updatePluginFromPath: vi.fn(),
  updatePluginFromUpload: vi.fn(),
  uploadPlugin: vi.fn(),
}))

vi.mock('@/api/client', () => pluginApi)

vi.mock('@/hooks/use-platform', () => ({
  usePlatform: () => ({ isTauri: true, os: 'macos', isMacOverlay: true }),
}))

vi.mock('@/components/PluginWorkspaceEditor', () => ({
  PluginWorkspaceEditor: ({ root, name }: { root: string; name: string }) => (
    <div data-testid="plugin-editor">{name} · {root}</div>
  ),
}))

describe('PluginCenterPanel create flow', () => {
  beforeEach(() => {
    Object.values(pluginApi).forEach((mock) => mock.mockReset())
    pluginApi.getPluginPackageReview.mockResolvedValue({ files: [], truncated: false, readme: null })
    pluginApi.listPlugins.mockResolvedValue({ plugins: [], mcp_servers: [] })
    pluginApi.createPlugin.mockResolvedValue({ path: '/tmp/plugins/demo-plugin' })
    pluginApi.inspectPlugin.mockResolvedValue({
      root: '/tmp/plugins/demo-plugin',
      valid: true,
      manifest: { name: 'demo-plugin' },
      diagnostics: [],
      skills: [],
      mcp_servers: [],
    })
  })

  it('creates a usable Skill scaffold by default, then opens the editor', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <PluginCenterPanel />
      </QueryClientProvider>,
    )

    fireEvent.click(await screen.findByRole('button', { name: /Add plugin/i }))
    fireEvent.click(await screen.findByText('Create plugin'))

    expect(screen.getByLabelText('Parent folder')).toBeVisible()
    expect(screen.getByLabelText('Plugin name')).toBeVisible()
    expect(screen.getByLabelText('Description')).toBeVisible()
    expect(screen.getByLabelText('Version optional')).toBeVisible()
    expect(screen.getByLabelText('Author optional')).toBeVisible()
    expect(screen.getByLabelText('License optional')).toBeVisible()
    expect(screen.getByLabelText('Starter Skill optional')).toBeVisible()
    expect(screen.queryByLabelText('Starter MCP server name')).not.toBeInTheDocument()
    expect(screen.getByText('Create development plugin').closest('section')).toHaveClass(
      '@container/plugin-center',
    )
    // Each field now sits in its own labelled wrapper, so the responsive
    // grid is the wrapper's parent rather than the input's.
    expect(
      screen.getByLabelText('Plugin name').closest('div')?.parentElement,
    ).toHaveClass('@lg/plugin-center:grid-cols-2')

    fireEvent.change(screen.getByLabelText('Parent folder'), {
      target: { value: ' /tmp/plugins/ ' },
    })
    fireEvent.change(screen.getByLabelText('Plugin name'), {
      target: { value: ' demo-plugin ' },
    })
    fireEvent.change(screen.getByLabelText('Description'), {
      target: { value: ' Demo description ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create & edit' }))

    await waitFor(() => expect(pluginApi.createPlugin).toHaveBeenCalledWith({
      destination: '/tmp/plugins/demo-plugin',
      name: 'demo-plugin',
      description: 'Demo description',
      skill_name: 'demo-plugin',
    }))
    expect(await screen.findByTestId('plugin-editor')).toHaveTextContent(
      'demo-plugin · /tmp/plugins/demo-plugin',
    )
  })

  it('forwards optional manifest and starter fields', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <PluginCenterPanel />
      </QueryClientProvider>,
    )

    fireEvent.click(await screen.findByRole('button', { name: /Add plugin/i }))
    fireEvent.click(await screen.findByText('Create plugin'))
    fireEvent.change(screen.getByLabelText('Parent folder'), {
      target: { value: '/tmp/plugins' },
    })
    fireEvent.change(screen.getByLabelText('Plugin name'), {
      target: { value: 'demo-plugin' },
    })
    fireEvent.change(screen.getByLabelText('Version optional'), {
      target: { value: '0.1.0' },
    })
    fireEvent.change(screen.getByLabelText('Author optional'), {
      target: { value: 'Demo Team' },
    })
    fireEvent.change(screen.getByLabelText('License optional'), {
      target: { value: 'MIT' },
    })
    fireEvent.change(screen.getByLabelText('Starter Skill optional'), {
      target: { value: 'demo-workflow' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create & edit' }))

    await waitFor(() => expect(pluginApi.createPlugin).toHaveBeenCalledWith({
      destination: '/tmp/plugins/demo-plugin',
      name: 'demo-plugin',
      description: 'EvoFlux plugin demo-plugin',
      version: '0.1.0',
      author: 'Demo Team',
      license: 'MIT',
      skill_name: 'demo-workflow',
    }))
  })
})

describe('PluginCenterPanel marketplace tab', () => {
  it('opens source management from Plugin Center', async () => {
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: { clear: vi.fn() },
    })
    pluginApi.listPlugins.mockResolvedValue({ plugins: [], mcp_servers: [] })
    pluginApi.listMarketplaces.mockResolvedValue([])
    pluginApi.searchMarketplacePlugins.mockResolvedValue([])
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <PluginCenterPanel />
      </QueryClientProvider>,
    )

    fireEvent.click(await screen.findByRole('tab', { name: 'Marketplace' }))

    expect(await screen.findByRole('heading', { name: 'Add a marketplace' })).toBeVisible()
    expect(await screen.findByText('No marketplace sources yet.')).toBeVisible()
  })
})

describe('PluginCenterPanel health status', () => {
  const installation = {
    id: 'inst-1',
    name: 'broken-mcp',
    version: '1.0.0',
    description: 'A plugin whose MCP server cannot start.',
    root: '/tmp/plugins/broken-mcp',
    source_type: 'installed',
    source_ref: '/tmp/plugins/broken-mcp',
    content_sha256: 'a'.repeat(64),
    enabled: true,
    managed_by: null,
    managed_project_id: null,
    managed_resource_id: null,
    managed_version_id: null,
    installed_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
  const inspection = {
    root: '/tmp/plugins/broken-mcp',
    valid: true,
    manifest: { name: 'broken-mcp', version: '1.0.0' },
    diagnostics: [],
    skills: [],
    mcp_servers: [
      { name: 'always-fails', transport: 'stdio', valid: true, config: {}, diagnostics: [] },
    ],
    trust: {
      executable_commands: [],
      remote_hosts: [],
      environment_fields: [],
      capabilities: [],
    },
    extension_namespaces: [],
    content_sha256: 'a'.repeat(64),
  }
  const item = {
    installation,
    inspection,
    credentials: { supported: false, configured: true, fields: [], error: null },
    capabilities: {
      can_enable: true,
      can_edit: true,
      can_pack: true,
      can_update: true,
      can_uninstall: true,
    },
    provider: null,
  }

  const renderPanel = async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <PluginCenterPanel />
      </QueryClientProvider>,
    )
    return screen.findByText('broken-mcp')
  }

  beforeEach(() => {
    Object.values(pluginApi).forEach((mock) => mock.mockReset())
    pluginApi.getPluginPackageReview.mockResolvedValue({ files: [], truncated: false, readme: null })
  })

  it('keeps installed package contents behind a compact keyboard-accessible disclosure', async () => {
    pluginApi.listPlugins.mockResolvedValue({ plugins: [item], mcp_servers: [] })
    await renderPanel()

    const row = screen.getByText('broken-mcp').closest('button')
    expect(row).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByLabelText('Package contents for broken-mcp')).not.toBeInTheDocument()
    fireEvent.click(row!)
    expect(row).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByLabelText('Package contents for broken-mcp')).toBeVisible()
  })

  // The package validated, so the card read "Enabled" on a green border
  // while the plugin contributed no tools at all. The failure was only
  // visible once you expanded the card.
  it('reports a failed MCP server without expanding the card', async () => {
    pluginApi.listPlugins.mockResolvedValue({
      plugins: [item],
      mcp_servers: [{
        installation_id: 'inst-1',
        plugin_name: 'broken-mcp',
        server_name: 'always-fails',
        runtime_name: 'plugin_inst1_always-fails',
        transport: 'stdio',
        enabled: true,
        state: 'error',
        error: 'FileNotFoundError: [WinError 2]',
        tool_names: [],
        started_at: null,
      }],
    })
    await renderPanel()

    expect(screen.getByText('1 MCP server failed')).toBeVisible()
    expect(screen.getByText(/needs attention: 1 MCP server failed/)).toBeInTheDocument()
  })

  it('shows active installed filters in the collapsed summary and offers reset', async () => {
    pluginApi.listPlugins.mockResolvedValue({ plugins: [item], mcp_servers: [] })
    await renderPanel()
    const summary = screen.getByText('Filters')
    const disclosure = summary.closest('details')
    const search = screen.getByLabelText('Filter plugins')
    expect(search).toBeVisible()
    expect(search.closest('details')).toBeNull()
    expect(disclosure).not.toHaveAttribute('open')
    search.focus()
    expect(search).toHaveFocus()
    fireEvent.change(search, { target: { value: 'no-match' } })

    expect(disclosure).not.toHaveAttribute('open')
    expect(summary).toHaveTextContent('(1 active)')
    fireEvent.click(summary)
    expect(screen.getByRole('button', { name: 'Reset filters' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }))
    expect(summary).not.toHaveTextContent('active')
  })

  it('keeps authentication-required visible on the collapsed installed row', async () => {
    pluginApi.listPlugins.mockResolvedValue({
      plugins: [item],
      mcp_servers: [{
        installation_id: 'inst-1', plugin_name: 'broken-mcp', server_name: 'private-api',
        runtime_name: 'plugin_inst1_private-api', transport: 'http', enabled: true,
        state: 'auth_required', error: null, tool_names: [], started_at: null,
      }],
    })
    await renderPanel()

    expect(screen.getAllByText('Authentication required').some((node) => node.getAttribute('class')?.includes('rounded-full'))).toBe(true)
    expect(screen.getByText('broken-mcp').closest('button')).toHaveAttribute('aria-expanded', 'false')
  })

  // `inspection.valid` means the package parses, not that every component
  // does: a skill with no frontmatter leaves it true.
  it('reports component diagnostics the package validity hides', async () => {
    pluginApi.listPlugins.mockResolvedValue({
      plugins: [{
        ...item,
        installation: { ...installation, enabled: false },
        inspection: {
          ...inspection,
          diagnostics: [{
            severity: 'error',
            code: 'mcp-json-invalid',
            message: 'mcp.json must contain exactly $schema and mcpServers.',
            scope: 'mcp',
          }],
          skills: [{
            name: 's1',
            description: '',
            path: 'skills/s1/SKILL.md',
            valid: false,
            diagnostics: [{
              severity: 'error',
              code: 'skill-frontmatter-invalid',
              message: 'frontmatter requires a non-empty name',
              scope: 'skill:s1',
            }],
          }],
        },
      }],
      mcp_servers: [],
    })
    await renderPanel()

    expect(screen.getByText('2 errors')).toBeVisible()
  })

  it('distinguishes marketplace installs from uploaded packages and filters their origin', async () => {
    pluginApi.listPlugins.mockResolvedValue({ plugins: [
      { ...item, installation: { ...installation, origin: { kind: 'marketplace', marketplace_name: 'Official catalog' } } },
      { ...item, installation: { ...installation, id: 'upload-1', name: 'uploaded-plugin', origin: { kind: 'import_archive' } } },
    ], mcp_servers: [] })
    await renderPanel()
    expect(screen.getByText('Marketplace · Official catalog')).toBeVisible()
    expect(screen.getByText('Imported archive')).toBeVisible()
    fireEvent.click(screen.getByRole('combobox', { name: 'Filter installed plugins by origin' }))
    const originOption = await screen.findByRole('option', { name: 'Imported archive' })
    fireEvent.focus(originOption)
    fireEvent.click(originOption)
    await waitFor(() => expect(screen.queryByText('broken-mcp')).not.toBeInTheDocument())
    expect(screen.getByText('uploaded-plugin')).toBeVisible()
  })

  it('shows remote MCP authorization as unavailable, not ready', async () => {
    pluginApi.listPlugins.mockResolvedValue({ plugins: [item], mcp_servers: [{
      installation_id: 'inst-1', plugin_name: 'broken-mcp', server_name: 'always-fails',
      runtime_name: 'plugin_inst1_always-fails', transport: 'http', enabled: true,
      state: 'auth_required', error: null, tool_names: [], started_at: null,
    }] })
    await renderPanel()
    fireEvent.click(screen.getByText('broken-mcp'))
    expect(screen.getAllByText('Authentication required').some((node) => node.getAttribute('class')?.includes('rounded-full'))).toBe(true)
    expect(screen.getByText(/Authorize this remote MCP server before its tools can be used/)).toBeVisible()
    expect(screen.queryByText('ready')).not.toBeInTheDocument()
  })

  it('stays quiet when nothing is wrong', async () => {
    pluginApi.listPlugins.mockResolvedValue({ plugins: [item], mcp_servers: [] })
    await renderPanel()

    expect(screen.queryByText(/MCP server(s)? failed/)).not.toBeInTheDocument()
    expect(screen.queryByText(/errors?$/)).not.toBeInTheDocument()
    expect(screen.getByText('Plugin is valid.')).toBeInTheDocument()
  })

  // A disabled plugin has no runners, so a stale error must not paint the
  // card red for a plugin the user deliberately turned off.
  it('does not blame a disabled plugin for a server that is not running', async () => {
    pluginApi.listPlugins.mockResolvedValue({
      plugins: [{ ...item, installation: { ...installation, enabled: false } }],
      mcp_servers: [{
        installation_id: 'inst-1',
        plugin_name: 'broken-mcp',
        server_name: 'always-fails',
        runtime_name: 'plugin_inst1_always-fails',
        transport: 'stdio',
        enabled: false,
        state: 'error',
        error: 'FileNotFoundError: [WinError 2]',
        tool_names: [],
        started_at: null,
      }],
    })
    await renderPanel()

    expect(screen.queryByText(/MCP server(s)? failed/)).not.toBeInTheDocument()
  })
})
