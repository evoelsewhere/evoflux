import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { HookSettingsResponse, PluginListResponse } from '@/api/types'
import { HookSettingsPage } from '@/routes/settings.hooks'

const mocks = vi.hoisted(() => ({
  settings: {
    mode: 'augment',
    replace_plugin_events: [],
    disabled_plugin_hooks: [],
    definitions: [],
    execution_state: 'blocked_isolation_unavailable',
    trust_required: true,
    hook_statuses: [],
  } as HookSettingsResponse,
  plugins: { plugins: [], mcp_servers: [] } as PluginListResponse,
  confirmOptions: null as null | { title: string; description: string; confirmLabel?: string; onConfirm: () => void },
  update: vi.fn(),
  saveContent: vi.fn(),
  getContent: vi.fn(),
  deleteContent: vi.fn(),
  preview: vi.fn(),
  trust: vi.fn(),
  trustPlugin: vi.fn(),
  revokePluginTrust: vi.fn(),
  push: vi.fn(),
}))

vi.mock('@/queries', () => ({
  useHookSettingsQuery: () => ({
    data: mocks.settings,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  useUpdateHookSettingsMutation: () => ({
    mutateAsync: mocks.update,
    isPending: false,
  }),
  useSaveSettingsHookWorkflowContentMutation: () => ({
    mutateAsync: mocks.saveContent,
    isPending: false,
  }),
  useTrustSettingsHookMutation: () => ({ mutate: mocks.trust, isPending: false }),
  useRevokeSettingsHookTrustMutation: () => ({ mutate: vi.fn(), isPending: false }),
}))

vi.mock('@/api/client', () => ({
  previewHookReplacement: mocks.preview,
  listPlugins: () => Promise.resolve(mocks.plugins),
  getSettingsHookWorkflowContent: mocks.getContent,
  deleteSettingsHookWorkflowContent: mocks.deleteContent,
  trustPluginHook: mocks.trustPlugin,
  revokePluginHookTrust: mocks.revokePluginTrust,
}))

vi.mock('@/hooks/use-confirm', () => ({
  useConfirm: () => ({
    request: null,
    close: vi.fn(),
    confirm: (options: typeof mocks.confirmOptions) => {
      mocks.confirmOptions = options
    },
  }),
}))

vi.mock('@/lib/settings-dirty', () => ({
  useRegisterSettingsDirty: vi.fn(),
}))

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector: (state: { push: typeof mocks.push }) => unknown) =>
    selector({ push: mocks.push }),
}))

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <HookSettingsPage />
    </QueryClientProvider>,
  )
}

describe('HookSettingsPage', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
    mocks.settings = {
      mode: 'augment',
      replace_plugin_events: [],
      disabled_plugin_hooks: [],
      definitions: [],
      execution_state: 'blocked_isolation_unavailable',
      trust_required: true,
      hook_statuses: [],
    }
    mocks.plugins = { plugins: [], mcp_servers: [] }
    mocks.confirmOptions = null
    mocks.update.mockReset()
    mocks.saveContent.mockReset()
    mocks.getContent.mockReset()
    mocks.getContent.mockResolvedValue({ path: './settings-workflows/test.md', content: '' })
    mocks.deleteContent.mockReset()
    mocks.preview.mockReset()
    mocks.trust.mockReset()
    mocks.trustPlugin.mockReset()
    mocks.revokePluginTrust.mockReset()
    mocks.push.mockReset()
  })

  it('presents a plain-language default and keeps JSON under Advanced', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Agent hooks' })).toBeTruthy()
    expect(screen.getByRole('radio', { name: /Run plugin workflows alongside my workflows/i })).toHaveProperty('checked', true)
    expect(screen.getByText(/called hooks/i)).toBeTruthy()
    const advanced = screen.getByText('Advanced: edit hook settings JSON').closest('details')
    expect(advanced?.open).toBe(false)
    fireEvent.click(screen.getByText('Advanced: edit hook settings JSON'))
    expect(screen.getByLabelText('Hook settings JSON')).toBeTruthy()
  })

  it('keeps common moment choices simple on a narrow screen and folds technical moments away', async () => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
    renderPage()

    fireEvent.click(await screen.findByRole('radio', { name: /use my workflows at selected moments/i }))
    expect(screen.getByText('At the start of a chat')).toBeTruthy()
    expect(screen.getByRole('checkbox', { name: 'At the start of a chat' })).toBeTruthy()
    expect(screen.getByText('When you send a message')).toBeTruthy()
    const otherMoments = screen.getByText(/other moments/i).closest('details')
    expect(otherMoments?.open).toBe(false)
    fireEvent.click(screen.getByText(/other moments/i))
    expect(otherMoments?.open).toBe(true)
    expect(screen.getByText('When an agent starts')).toBeTruthy()
    expect(screen.getByText('session.end')).toBeTruthy()
  })

  it('previews replacement and warns when no Settings workflow will run', async () => {
    mocks.preview.mockResolvedValue({ registrations: [] })
    mocks.update.mockResolvedValue(mocks.settings)
    renderPage()

    fireEvent.click(await screen.findByRole('radio', { name: /Use my workflows at selected moments/i }))
    fireEvent.click(screen.getByText('At the start of a chat'))
    expect(screen.getByText(/No approved workflow in My workflows/i)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Save workflows' }))

    await waitFor(() => expect(mocks.preview).toHaveBeenCalledOnce())
    expect(mocks.update).not.toHaveBeenCalled()
    expect(mocks.confirmOptions?.description).toContain('At the start of a chat')
    expect(mocks.confirmOptions?.description).toContain('No enabled plugin workflows will be replaced')
    await act(async () => mocks.confirmOptions?.onConfirm())
    expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({
      mode: 'replace',
      replace_plugin_events: ['session.start'],
    }))
  })

  it('warns when the matching Settings workflow still needs approval', async () => {
    const definition = {
      hook_id: 'workflow-onboarding-a1b2c3d4', event: 'session.start', runtime: 'native',
      command: ['./settings-workflows/0123456789abcdef0123456789abcdef.md'], files: [],
      execution_kind: 'static_context', context_prefix: '', context_suffix: '', timeout_seconds: 10,
      input_fields: [], output_fields: ['context'], failure_policy: 'fail_closed', overrides: [],
    }
    mocks.settings = {
      ...mocks.settings,
      definitions: [definition],
      hook_statuses: [{
        hook_id: definition.hook_id, event: 'session.start', command: definition.command,
        runtime: 'native', files: [], execution_kind: 'static_context', context_prefix: '',
        context_suffix: '', input_fields: [], output_fields: ['context'], digest: 'a'.repeat(64),
        isolation_profile: 'evoflux-static-context-v1', trusted: false, has_approvals: false,
        status: 'awaiting_trust',
      }],
    } as HookSettingsResponse
    renderPage()

    fireEvent.click(await screen.findByRole('radio', { name: /Use my workflows at selected moments/i }))
    fireEvent.click(screen.getByText('At the start of a chat'))

    expect(screen.getByText(/No approved workflow in My workflows. Nothing will happen at this time./i)).toBeTruthy()
  })

  it('pauses only the selected plugin and hook pair', async () => {
    mocks.plugins = {
      mcp_servers: [],
      plugins: [{
        installation: {
          id: 'a'.repeat(32), name: 'Superpowers', version: '1.0.0', description: null,
          root: 'C:/plugins/superpowers', source_type: 'installed', source_ref: '',
          content_sha256: 'b'.repeat(64), enabled: true, installed_at: '', updated_at: '',
        },
        inspection: {
          root: 'C:/plugins/superpowers', valid: true,
          manifest: { name: 'superpowers' },
          diagnostics: [], skills: [], mcp_servers: [],
          hooks: [{
            definition: {
              hook_id: 'session-bootstrap', event: 'session.start', execution_kind: 'static_context',
              command: ['./hooks/session.md'], input_fields: [], output_fields: ['context'],
            },
            command_path: 'hooks/session.md', digest: 'c'.repeat(64), valid: true, diagnostics: [],
          }],
          hook_statuses: [{
            hook_id: 'session-bootstrap', event: 'session.start', digest: 'c'.repeat(64),
            trusted: true, enabled: true, status: 'active',
          }],
          trust: { capabilities: [] },
          extension_namespaces: [], content_sha256: null,
        },
        credentials: { supported: false, configured: true, fields: [] },
        capabilities: { can_enable: true, can_edit: false, can_pack: false, can_update: false, can_uninstall: false },
      }],
    } as unknown as PluginListResponse
    mocks.update.mockResolvedValue(mocks.settings)
    renderPage()

    expect(await screen.findByText('Superpowers')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Pause workflow' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save workflows' }))

    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({
      disabled_plugin_hooks: [{ plugin_id: 'superpowers', hook_id: 'session-bootstrap' }],
    })))
  })

  it('reviews and approves only the selected plugin workflow without enabling the plugin', async () => {
    mocks.plugins = {
      mcp_servers: [],
      plugins: [{
        installation: {
          id: 'a'.repeat(32), name: 'Superpowers', version: '1.0.0', description: null,
          root: 'C:/plugins/superpowers', source_type: 'installed', source_ref: '',
          content_sha256: 'b'.repeat(64), enabled: true, installed_at: '', updated_at: '',
        },
        inspection: {
          root: 'C:/plugins/superpowers', valid: true, manifest: { name: 'superpowers' },
          diagnostics: [], skills: [], mcp_servers: [],
          hooks: [{ definition: {
            hook_id: 'session-bootstrap', event: 'session.start', execution_kind: 'static_context',
            command: ['./hooks/session.md'], input_fields: [], output_fields: ['context'],
          }, command_path: 'hooks/session.md', digest: 'c'.repeat(64), valid: true, diagnostics: [] }],
          hook_statuses: [{ hook_id: 'session-bootstrap', event: 'session.start', digest: 'c'.repeat(64), trusted: false, enabled: true, status: 'awaiting_trust' }],
          trust: { capabilities: [] }, extension_namespaces: [], content_sha256: null,
        },
        credentials: { supported: false, configured: true, fields: [] },
        capabilities: { can_enable: true, can_edit: false, can_pack: false, can_update: false, can_uninstall: false },
      }],
    } as unknown as PluginListResponse
    mocks.trustPlugin.mockResolvedValue({})
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: 'Review workflow' }))
    expect(mocks.confirmOptions?.title).toContain('Superpowers')
    expect(mocks.confirmOptions?.description).toContain('At the start of a chat')
    expect(mocks.confirmOptions?.description).toContain('does not run code')
    expect(mocks.confirmOptions?.confirmLabel).toBe('Allow this workflow')
    await act(async () => mocks.confirmOptions?.onConfirm())
    await waitFor(() => expect(mocks.trustPlugin).toHaveBeenCalledWith('a'.repeat(32), 'session-bootstrap', 'c'.repeat(64)))
    expect(mocks.update).not.toHaveBeenCalled()
  })

  it('shows the saved Markdown title instead of the technical hook id', async () => {
    const definition = {
      hook_id: 'workflow-daily-guidance-a1b2c3d4', event: 'session.start', runtime: 'native',
      command: ['./settings-workflows/0123456789abcdef0123456789abcdef.md'], files: [],
      execution_kind: 'static_context', context_prefix: '', context_suffix: '', timeout_seconds: 10,
      input_fields: [], output_fields: ['context'], failure_policy: 'fail_closed', overrides: [],
    }
    mocks.settings = {
      ...mocks.settings,
      definitions: [definition],
      hook_statuses: [{
        hook_id: definition.hook_id, event: 'session.start', command: definition.command,
        runtime: 'native', files: [], execution_kind: 'static_context', context_prefix: '',
        context_suffix: '', input_fields: [], output_fields: ['context'], digest: 'a'.repeat(64),
        isolation_profile: 'evoflux-static-context-v1', trusted: false, has_approvals: false,
        status: 'awaiting_trust',
      }],
    } as HookSettingsResponse
    mocks.getContent.mockResolvedValue({
      path: definition.command[0], content: '# Daily research companion\n\nUse project skills first.\n',
    })
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Daily research companion' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: definition.hook_id })).toBeNull()
  })

  it('creates Settings guidance without granting trust', async () => {
    const savedSettings = {
      ...mocks.settings,
      definitions: [{
        hook_id: 'daily-guidance-a1b2c3d4', event: 'session.start', runtime: 'native',
        command: ['./settings-workflows/0123456789abcdef0123456789abcdef.md'], files: [],
        execution_kind: 'static_context', context_prefix: '', context_suffix: '',
        timeout_seconds: 10, input_fields: [], output_fields: ['context'],
        failure_policy: 'fail_closed', overrides: [],
      }],
      hook_statuses: [{
        hook_id: 'daily-guidance-a1b2c3d4', event: 'session.start',
        command: ['./settings-workflows/0123456789abcdef0123456789abcdef.md'],
        runtime: 'native', files: [], execution_kind: 'static_context', context_prefix: '',
        context_suffix: '', input_fields: [], output_fields: ['context'], digest: 'a'.repeat(64),
        isolation_profile: 'evoflux-static-context-v1', trusted: false, has_approvals: false,
        status: 'awaiting_trust',
      }],
    } as HookSettingsResponse
    mocks.saveContent.mockResolvedValue({ path: './settings-workflows/0123456789abcdef0123456789abcdef.md' })
    mocks.update.mockResolvedValue(savedSettings)
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: 'Create workflow' }))
    fireEvent.change(screen.getByLabelText('Workflow name'), { target: { value: 'Daily guidance' } })
    fireEvent.change(screen.getByLabelText('Guidance text'), { target: { value: 'Use the project skill first.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save workflow' }))

    await waitFor(() => expect(mocks.saveContent).toHaveBeenCalledOnce())
    expect(mocks.saveContent.mock.calls[0]?.[0].workflowId).toMatch(/^[a-f0-9]{32}$/)
    expect(mocks.saveContent.mock.calls[0]?.[0].content).toContain('# Daily guidance\n\nUse the project skill first.')
    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
    const savedDefinition = mocks.update.mock.calls[0]?.[0].definitions[0]
    expect(savedDefinition).toMatchObject({
      event: 'session.start',
      execution_kind: 'static_context',
      command: ['./settings-workflows/0123456789abcdef0123456789abcdef.md'],
      input_fields: [],
      output_fields: ['context'],
    })
    expect(savedDefinition).not.toHaveProperty('shell')
    expect(mocks.trust).not.toHaveBeenCalled()
  })

  it('edits only the named session guidance file and keeps its hook identity', async () => {
    const definition = {
      hook_id: 'workflow-daily-guidance-a1b2c3d4', event: 'session.start', runtime: 'native',
      command: ['./settings-workflows/0123456789abcdef0123456789abcdef.md'], files: [],
      execution_kind: 'static_context', context_prefix: '', context_suffix: '', timeout_seconds: 10,
      input_fields: [], output_fields: ['context'], failure_policy: 'fail_closed', overrides: [],
    }
    mocks.settings = {
      ...mocks.settings,
      definitions: [definition],
      hook_statuses: [{
        hook_id: definition.hook_id, event: 'session.start', command: definition.command,
        runtime: 'native', files: [], execution_kind: 'static_context', context_prefix: '',
        context_suffix: '', input_fields: [], output_fields: ['context'], digest: 'a'.repeat(64),
        isolation_profile: 'evoflux-static-context-v1', trusted: true, has_approvals: true, status: 'active',
      }],
    } as HookSettingsResponse
    mocks.getContent.mockResolvedValue({
      path: definition.command[0], content: '# Daily guidance\n\nOld guidance.',
    })
    mocks.saveContent.mockResolvedValue({ path: definition.command[0] })
    mocks.update.mockResolvedValue({
      ...mocks.settings,
      hook_statuses: [{ ...mocks.settings.hook_statuses[0]!, trusted: false, status: 'awaiting_trust' }],
    })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    await waitFor(() => expect(mocks.getContent).toHaveBeenCalledWith('0123456789abcdef0123456789abcdef'))
    expect(await screen.findByLabelText('Workflow name')).toHaveProperty('value', 'Daily guidance')
    fireEvent.change(screen.getByLabelText('Guidance text'), { target: { value: 'Updated guidance.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save workflow' }))

    await waitFor(() => expect(mocks.saveContent).toHaveBeenCalledOnce())
    expect(mocks.saveContent.mock.calls[0]?.[0]).toEqual({
      workflowId: '0123456789abcdef0123456789abcdef',
      content: '# Daily guidance\n\nUpdated guidance.\n',
    })
    expect(mocks.update.mock.calls[0]?.[0].definitions[0].hook_id).toBe(definition.hook_id)
    expect(mocks.trust).not.toHaveBeenCalled()
  })

  it('removes the definition before deleting only its owned content file', async () => {
    const definition = {
      hook_id: 'workflow-daily-guidance-a1b2c3d4', event: 'session.start', runtime: 'native',
      command: ['./settings-workflows/0123456789abcdef0123456789abcdef.md'], files: [],
      execution_kind: 'static_context', context_prefix: '', context_suffix: '', timeout_seconds: 10,
      input_fields: [], output_fields: ['context'], failure_policy: 'fail_closed', overrides: [],
    }
    mocks.settings = {
      ...mocks.settings,
      definitions: [definition],
      hook_statuses: [{
        hook_id: definition.hook_id, event: 'session.start', command: definition.command,
        runtime: 'native', files: [], execution_kind: 'static_context', context_prefix: '',
        context_suffix: '', input_fields: [], output_fields: ['context'], digest: 'a'.repeat(64),
        isolation_profile: 'evoflux-static-context-v1', trusted: true, has_approvals: true, status: 'active',
      }],
    } as HookSettingsResponse
    mocks.update.mockResolvedValue({ ...mocks.settings, definitions: [], hook_statuses: [] })
    mocks.deleteContent.mockResolvedValue({ deleted: true })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: 'Remove' }))
    expect(mocks.confirmOptions?.title).toBe('Remove this workflow?')
    await act(async () => mocks.confirmOptions?.onConfirm())

    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(expect.objectContaining({ definitions: [] })))
    expect(mocks.deleteContent).toHaveBeenCalledWith('0123456789abcdef0123456789abcdef')
  })

  it('explains the execution gate and confirms exact hooks before replace mode', async () => {
    mocks.preview.mockResolvedValue({
      registrations: [
        {
          event: 'tool.before',
          plugin_id: 'demo-plugin',
          hook_id: 'validate-command',
          installation_id: 'a'.repeat(32),
          source: 'managed_plugin',
          display_name: 'Demo plugin',
          certainty: 'exact',
        },
      ],
    })
    mocks.update.mockResolvedValue(mocks.settings)
    renderPage()

    expect(await screen.findByText(/no verified OS isolation backend/i)).toBeTruthy()
    fireEvent.click(screen.getByText('Advanced: edit hook settings JSON'))
    const editor = await screen.findByLabelText('Hook settings JSON')
    fireEvent.change(editor, {
      target: {
        value: JSON.stringify({
          mode: 'replace',
          replace_plugin_events: ['tool.before'],
          disabled_plugin_hooks: [],
          definitions: [],
        }),
      },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save workflows' }))

    await waitFor(() => expect(mocks.preview).toHaveBeenCalledOnce())
    expect(mocks.confirmOptions?.title).toBe('Replace plugin workflows at selected moments?')
    expect(mocks.confirmOptions?.description).toContain('These plugin hooks will be suppressed at the selected moments:')
    expect(mocks.confirmOptions?.description).toContain('validate-command')
    expect(mocks.confirmOptions?.description).toContain('a'.repeat(32))
    expect(mocks.update).not.toHaveBeenCalled()

    await act(async () => mocks.confirmOptions?.onConfirm())
    await waitFor(() => expect(mocks.update).toHaveBeenCalledOnce())
  })

  it('labels trusted legacy Python hooks and marks dynamic subscriptions as possible impact', async () => {
    mocks.preview.mockResolvedValue({
      registrations: [
        {
          event: 'tool.before',
          plugin_id: 'local-python',
          hook_id: 'dynamic_guide',
          installation_id: 'b'.repeat(16),
          source: 'legacy_python',
          display_name: 'dynamic_guide.py',
          certainty: 'possible',
        },
      ],
    })
    renderPage()

    fireEvent.click(screen.getByText('Advanced: edit hook settings JSON'))
    const editor = await screen.findByLabelText('Hook settings JSON')
    fireEvent.change(editor, {
      target: {
        value: JSON.stringify({
          mode: 'replace',
          replace_plugin_events: ['tool.before'],
          disabled_plugin_hooks: [],
          definitions: [],
        }),
      },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save workflows' }))

    await waitFor(() => expect(mocks.preview).toHaveBeenCalledOnce())
    expect(mocks.confirmOptions?.description).toContain('These workflows will stop or may be affected:')
    expect(mocks.confirmOptions?.description).toContain('dynamic_guide.py (Local Python extension)')
    expect(mocks.confirmOptions?.description).toContain('did not run it to inspect its event list')
  })
})
