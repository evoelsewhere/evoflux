import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PluginInspection } from '@/api/types'
import { PluginInspectionDetails, PluginPackageFiles } from '@/components/PluginPackageReview'

const api = vi.hoisted(() => ({ getPluginPackageReview: vi.fn(), getPluginPackageFile: vi.fn() }))
vi.mock('@/api/client', () => api)

const inspection = {
  valid: true, root: '/package', manifest: null, diagnostics: [], extension_namespaces: [], content_sha256: null,
  skills: [{ name: 'safe-skill', description: 'Explain a fictional dashboard without writing files.', path: 'skills/safe/SKILL.md', valid: true, diagnostics: [] }],
  mcp_servers: [{ name: 'docs', transport: 'stdio', enabled: true, valid: true, diagnostics: [], config: { command: 'node', args: ['server.js'], env: { API_TOKEN: 'never-show-env-secret' }, headers: { Authorization: 'never-show-header-secret' } } }],
  trust: { executable_commands: [], remote_hosts: [], environment_fields: [], capabilities: [] },
} as unknown as PluginInspection

function renderFiles() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><PluginPackageFiles target="preview" id="preview-1" /></QueryClientProvider>)
}

describe('read-only package review', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getPluginPackageReview.mockResolvedValue({ files: [{ path: 'README.md', kind: 'text', size: 20 }, { path: 'skills/safe/SKILL.md', kind: 'text', size: 40 }], truncated: false, readme: { path: 'README.md', content: '# Safe preview' } })
    api.getPluginPackageFile.mockResolvedValue({ path: 'skills/safe/SKILL.md', content: '<img src="https://invalid.example/track">\nRead-only instructions', truncated: false })
  })

  it('shows each Skill and MCP configuration, never environment or header values', () => {
    render(<PluginInspectionDetails inspection={inspection} />)
    fireEvent.click(screen.getByText('Components'))
    expect(screen.getByText('safe-skill')).toBeVisible()
    expect(screen.getByText(/Explain a fictional dashboard/)).toBeVisible()
    expect(screen.getByText('skills/safe/SKILL.md')).toBeVisible()
    expect(screen.getByText(/docs · stdio · Valid/)).toBeVisible()
    expect(screen.getByText(/node server.js/)).not.toBeVisible()
    fireEvent.click(screen.getByText('Technical details'))
    expect(screen.getByText(/node server.js/)).toBeVisible()
    expect(screen.getByText(/API_TOKEN/)).toBeVisible()
    expect(screen.getByText(/Authorization/)).toBeVisible()
    expect(screen.queryByText(/never-show-env-secret|never-show-header-secret/)).not.toBeInTheDocument()
  })

  it('loads a bounded package tree and displays file contents as inert text', async () => {
    const { container } = renderFiles()
    expect(screen.getByText('Package files')).toBeVisible()
    expect(screen.queryByText('# Safe preview')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('Package files'))
    expect(await screen.findByText('# Safe preview')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /skills\/safe\/SKILL.md/ }))
    expect(await screen.findByText(/Read-only instructions/)).toBeVisible()
    expect(api.getPluginPackageReview).toHaveBeenCalledWith('preview', 'preview-1')
    expect(api.getPluginPackageFile).toHaveBeenCalledWith('preview', 'preview-1', 'skills/safe/SKILL.md')
    expect(container.querySelector('img, iframe, script')).toBeNull()
  })

  it('keeps blocking diagnostics visible and discloses only nonblocking technical details', () => {
    const diagnostics = {
      ...inspection,
      skills: [],
      mcp_servers: [],
      diagnostics: [
        { code: 'blocked', severity: 'error', message: 'Invalid frontmatter blocks installation.' },
        { code: 'warning', severity: 'warning', message: 'Optional metadata is missing.' },
      ],
    } as unknown as PluginInspection
    render(<PluginInspectionDetails inspection={diagnostics} />)

    expect(screen.getByRole('alert')).toHaveTextContent('Invalid frontmatter blocks installation.')
    expect(screen.getByText('Technical details')).toBeVisible()
    expect(screen.queryByText('Optional metadata is missing.')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('Technical details'))
    expect(screen.getByText(/Optional metadata is missing/)).toBeVisible()
    expect(screen.queryByText(/No Skills|No MCP servers|None|Not provided/)).not.toBeInTheDocument()
  })

  it('shows package listing failures outside the closed files disclosure and keeps readiness blocked', async () => {
    api.getPluginPackageReview.mockRejectedValue(new Error('Package listing failed.'))
    const onReviewReady = vi.fn()
    const { container } = render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><PluginPackageFiles target="preview" id="preview-1" onReviewReady={onReviewReady} /></QueryClientProvider>)
    expect(await screen.findByRole('alert')).toHaveTextContent('Package listing failed.')
    expect(screen.getByText('Package files').closest('details')).not.toHaveAttribute('open')
    expect(onReviewReady).toHaveBeenLastCalledWith(false)
    expect(container.querySelector('[role="alert"]')?.closest('details')).toBeNull()
  })

  it('surfaces a denied file read and does not leave previous contents visible', async () => {
    api.getPluginPackageFile.mockRejectedValue(new Error('Sensitive file is not available for review'))
    renderFiles()
    fireEvent.click(screen.getByText('Package files'))
    await screen.findByText('# Safe preview')
    fireEvent.click(screen.getByRole('button', { name: /skills\/safe\/SKILL.md/ }))
    expect(await screen.findByText(/Sensitive file is not available for review/)).toBeVisible()
    expect(screen.queryByText('# Safe preview')).not.toBeInTheDocument()
  })
})
