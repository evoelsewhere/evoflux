import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PluginInspection } from '@/api/types'
import { PluginInspectionDetails, PluginPackageFiles } from '@/components/PluginPackageReview'
import { PluginTrustReviewDialog } from '@/components/PluginTrustReviewDialog'

const api = vi.hoisted(() => ({
  getPluginPackageReview: vi.fn(),
  getPluginPackageFile: vi.fn(),
  trustPluginHook: vi.fn(),
  revokePluginHookTrust: vi.fn(),
}))
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

  it('explains workflows before enablement and hides technical hook metadata until requested', () => {
    render(<PluginTrustReviewDialog
      pluginName="workflow-plugin"
      review={{
        executable_commands: [],
        remote_hosts: [],
        environment_fields: [],
        capabilities: [],
        hooks: [{
          hook_id: 'session-bootstrap',
          event: 'session.start',
          execution_kind: 'command',
          command: ['./hooks/bootstrap.py'],
          command_path: 'hooks/bootstrap.py',
          runtime: 'python',
          files: ['./hooks/helper.py'],
          context_prefix: '',
          context_suffix: '',
          input_fields: ['source'],
          output_fields: ['context'],
          matcher: { source: 'new' },
          timeout_seconds: 15,
          failure_policy: 'fail_closed',
          environment_fields: ['EVOFLUX_HOOK_PROTOCOL'],
          isolation_profile: 'evoflux-plugin-hook-v2',
          digest: 'a'.repeat(64),
          valid: true,
        }],
      }}
      busy={false}
      onCancel={vi.fn()}
      onConfirm={vi.fn()}
    />)

    expect(screen.getByText('When a new session starts')).toBeVisible()
    expect(screen.getByText(/Runs this plugin’s command/)).toBeVisible()
    expect(screen.getByText(/Enabling the plugin does not approve its hooks/)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Enable plugin' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Trust MCP access and enable' })).not.toBeInTheDocument()
    expect(screen.getByText(/Matcher:.*source.*new/)).not.toBeVisible()
    fireEvent.click(screen.getByText('Technical details'))
    expect(screen.getByText('python')).toBeVisible()
    expect(screen.getByText(/Declared files:.*helper\.py/)).toBeVisible()
    expect(screen.getByText(/Matcher:.*source.*new/)).toBeVisible()
    expect(screen.getByText(/Timeout: 15 seconds/)).toBeVisible()
    expect(screen.getByText(/Failure policy: fail_closed/)).toBeVisible()
    expect(screen.getByText(/EVOFLUX_HOOK_PROTOCOL/)).toBeVisible()
    expect(screen.getByText(/evoflux-plugin-hook-v2/)).toBeVisible()
    expect(screen.getByText(/Hook approval is a separate choice/)).toBeVisible()
  })

  it('labels enablement as MCP consent only when the package declares MCP access', () => {
    render(<PluginTrustReviewDialog
      pluginName="mcp-plugin"
      review={{
        executable_commands: [{ server: 'docs', executable: 'node', args: ['server.js'] }],
        remote_hosts: [],
        environment_fields: ['DOCS_TOKEN'],
        capabilities: [],
        hooks: [],
      }}
      busy={false}
      onCancel={vi.fn()}
      onConfirm={vi.fn()}
    />)

    expect(screen.getByRole('button', { name: 'Trust MCP access and enable' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Enable plugin' })).not.toBeInTheDocument()
  })

  it('explains a static workflow in plain language before showing technical details', () => {
    const staticInspection = {
      ...inspection,
      hooks: [{
        definition: {
          hook_id: 'session-bootstrap', event: 'session.start', execution_kind: 'static_context',
          command: ['./hooks/session.md'], runtime: 'native', files: [], context_prefix: '', context_suffix: '',
          timeout_seconds: 10, input_fields: [], output_fields: ['context'], failure_policy: 'fail_closed', overrides: [],
        },
        command_path: 'hooks/session.md', digest: 'd'.repeat(64), valid: true, diagnostics: [],
      }],
      hook_statuses: [{
        hook_id: 'session-bootstrap', event: 'session.start', digest: 'd'.repeat(64),
        trusted: false, enabled: true, status: 'awaiting_trust',
      }],
      trust: { ...inspection.trust, hooks: [] },
    } as unknown as PluginInspection

    render(<PluginInspectionDetails inspection={staticInspection} installationId="install-1" />)
    fireEvent.click(screen.getByText('Components'))

    expect(screen.getByText('When a new session starts')).toBeVisible()
    expect(screen.getByText('Adds this plugin’s guidance to a new session.')).toBeVisible()
    expect(screen.getByText('This reads a Markdown guide and does not run code.')).toBeVisible()
    expect(screen.getByText('Needs review')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Review workflow' })).toBeVisible()
    expect(screen.queryByText('session.start')).not.toBeInTheDocument()
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

  it('shows hook runtime state without rendering executable output or event payloads', () => {
    const withHook = {
      ...inspection,
      hooks: [{
        definition: {
          hook_id: 'session-bootstrap',
          event: 'session.start',
          command: ['./hooks/bootstrap.py'],
          timeout_seconds: 5,
          input_fields: ['source'],
          output_fields: ['context'],
          failure_policy: 'fail_open',
          matcher: { source: 'new' },
          overrides: [],
        },
        command_path: 'hooks/bootstrap.py',
        digest: 'a'.repeat(64),
        valid: true,
        diagnostics: [],
      }],
      hook_statuses: [{
        hook_id: 'session-bootstrap',
        event: 'session.start',
        digest: 'a'.repeat(64),
        trusted: true,
        enabled: true,
        status: 'blocked_isolation_unavailable',
      }],
    } as unknown as PluginInspection

    render(<PluginInspectionDetails inspection={withHook} />)
    fireEvent.click(screen.getByText('Components'))
    const hookSection = screen.getByLabelText('Package lifecycle hooks')

    expect(hookSection).toHaveTextContent('When a new session starts')
    expect(hookSection).toHaveTextContent('Blocked on this device')
    expect(screen.getByText(/approved for this content/)).toBeVisible()
    expect(hookSection).not.toHaveTextContent('session-bootstrap')
    expect(hookSection).not.toHaveTextContent('session.start')
    expect(screen.getByText(/Command workflows are executable code/)).toBeVisible()
    expect(screen.queryByText(/hook stdout|secret payload/)).not.toBeInTheDocument()
  })

  it('requires reviewing the exact package hook digest before approving trust', async () => {
    const withHook = {
      ...inspection,
      hooks: [{
        definition: {
          hook_id: 'session-bootstrap',
          event: 'session.start',
          command: ['./hooks/bootstrap.py'],
          timeout_seconds: 5,
          input_fields: ['source'],
          output_fields: ['context'],
          failure_policy: 'fail_open',
          matcher: { source: 'new' },
          overrides: [],
        },
        command_path: 'hooks/bootstrap.py',
        digest: 'b'.repeat(64),
        valid: true,
        diagnostics: [],
      }],
      hook_statuses: [{
        hook_id: 'session-bootstrap',
        event: 'session.start',
        digest: 'b'.repeat(64),
        trusted: false,
        enabled: true,
        status: 'awaiting_trust',
      }],
      trust: {
        ...inspection.trust,
        hooks: [{
          hook_id: 'session-bootstrap',
          event: 'session.start',
          execution_kind: 'command',
          command: ['./hooks/bootstrap.py'],
          command_path: 'hooks/bootstrap.py',
          runtime: 'python',
          files: ['./hooks/helper.py'],
          context_prefix: '',
          context_suffix: '',
          matcher: { source: 'new' },
          timeout_seconds: 5,
          failure_policy: 'fail_open',
          input_fields: ['source'],
          output_fields: ['context'],
          environment_fields: ['EVOFLUX_HOOK_PROTOCOL'],
          isolation_profile: 'evoflux-plugin-hook-v2',
          digest: 'b'.repeat(64),
          valid: true,
        }],
      },
    } as unknown as PluginInspection
    const onHookTrustChanged = vi.fn()
    api.trustPluginHook.mockResolvedValue({})

    render(<PluginInspectionDetails
      inspection={withHook}
      installationId="install-1"
      onHookTrustChanged={onHookTrustChanged}
    />)
    fireEvent.click(screen.getByText('Components'))
    fireEvent.click(screen.getByRole('button', { name: 'Review workflow' }))
    const hookSection = screen.getByLabelText('Package lifecycle hooks')
    fireEvent.click(within(hookSection).getByText('Technical details'))

    expect(screen.getByText(/SHA-256:/)).toHaveTextContent('b'.repeat(64))
    expect(screen.getByText(/Matcher:/)).toHaveTextContent('source')
    expect(screen.getByText(/Timeout: 5 seconds/)).toBeVisible()
    expect(screen.getByText(/Failure policy:/)).toHaveTextContent('fail_open')
    expect(screen.getByText(/EVOFLUX_HOOK_PROTOCOL/)).toBeVisible()
    expect(screen.getByText(/evoflux-plugin-hook-v2/)).toBeVisible()
    expect(api.trustPluginHook).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Allow this workflow' }))
    expect(api.trustPluginHook).toHaveBeenCalledWith('install-1', 'session-bootstrap', 'b'.repeat(64))
    expect(screen.getByText(/Allowing approves this exact command/)).toBeVisible()
    await waitFor(() => expect(onHookTrustChanged).toHaveBeenCalledOnce())
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
