import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { PluginCenterPanel } from '@/components/PluginCenterPanel'

const pluginApi = vi.hoisted(() => ({
  createPlugin: vi.fn(),
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

    expect(screen.getByLabelText('Plugin parent folder')).toBeVisible()
    expect(screen.getByLabelText('Plugin name')).toBeVisible()
    expect(screen.getByLabelText('Plugin description')).toBeVisible()
    expect(screen.getByLabelText('Plugin version')).toBeVisible()
    expect(screen.getByLabelText('Plugin author')).toBeVisible()
    expect(screen.getByLabelText('Plugin license')).toBeVisible()
    expect(screen.getByLabelText('Starter Skill name')).toBeVisible()
    expect(screen.queryByLabelText('Starter MCP server name')).not.toBeInTheDocument()
    expect(screen.getByText('Create development plugin').closest('section')).toHaveClass(
      '@container/plugin-center',
    )
    expect(screen.getByLabelText('Plugin name').parentElement).toHaveClass(
      '@lg/plugin-center:grid-cols-2',
    )

    fireEvent.change(screen.getByLabelText('Plugin parent folder'), {
      target: { value: ' /tmp/plugins/ ' },
    })
    fireEvent.change(screen.getByLabelText('Plugin name'), {
      target: { value: ' demo-plugin ' },
    })
    fireEvent.change(screen.getByLabelText('Plugin description'), {
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
    fireEvent.change(screen.getByLabelText('Plugin parent folder'), {
      target: { value: '/tmp/plugins' },
    })
    fireEvent.change(screen.getByLabelText('Plugin name'), {
      target: { value: 'demo-plugin' },
    })
    fireEvent.change(screen.getByLabelText('Plugin version'), {
      target: { value: '0.1.0' },
    })
    fireEvent.change(screen.getByLabelText('Plugin author'), {
      target: { value: 'Demo Team' },
    })
    fireEvent.change(screen.getByLabelText('Plugin license'), {
      target: { value: 'MIT' },
    })
    fireEvent.change(screen.getByLabelText('Starter Skill name'), {
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
