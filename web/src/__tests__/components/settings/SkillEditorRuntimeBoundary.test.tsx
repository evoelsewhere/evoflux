import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { SkillEditorPage } from '@/routes/settings.skills.$name'

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  push: vi.fn(),
  refetch: vi.fn(),
  mutateAsync: vi.fn(),
  searchMode: 'coding' as string | undefined,
  activeWorkspaces: [] as string[],
  queryScope: null as null | { workspaces?: readonly string[] | null; mode?: string | null },
}))

vi.mock('@/queries', () => ({
  useSkillFileQuery: (
    _name: string,
    scope: { workspaces?: readonly string[] | null; mode?: string | null },
  ) => {
    mocks.queryScope = scope
    return {
      data: {
        name: 'code-graph-navigation',
        path: '/builtin/code-graph-navigation/SKILL.md',
        content: '---\nname: code-graph-navigation\ndescription: Navigate code.\n---\n',
        description: 'Navigate code.',
        display_name: 'Navigate Code Graph',
        short_description: 'Trace exact symbols',
        default_prompt: 'Use $code-graph-navigation.',
        allow_implicit_invocation: true,
        user_invocable: true,
        resource_count: 3,
        symlinked: false,
        diagnostics: [
          {
            code: 'invalid-runtime-settings',
            message: 'The runtime override is invalid and was ignored.',
            severity: 'warning',
          },
        ],
        shadowed_paths: [],
        error: null,
        built_in: true,
        editable: false,
        settings_editable: true,
        settings_id: 'builtin:code-graph-navigation',
        settings_overridden: false,
        source: 'builtin',
        modes: ['coding'],
        dependencies: [],
        bundle_truncated: false,
        files: [],
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: mocks.refetch,
    }
  },
  useUpdateSkillMutation: () => ({ isPending: false, mutateAsync: mocks.mutateAsync }),
  useUpdateSkillSettingsMutation: () => ({ isPending: false, mutateAsync: mocks.mutateAsync }),
  useResetSkillSettingsMutation: () => ({ isPending: false, mutateAsync: mocks.mutateAsync }),
  useDeleteSkillMutation: () => ({ isPending: false, mutateAsync: mocks.mutateAsync }),
}))

vi.mock('@/components/settings/EditorHeaderActions', () => ({
  EditorHeaderActions: () => null,
}))

vi.mock('@/components/settings/SettingsLayout', () => ({
  SettingsPage: ({ children }: { children: React.ReactNode }) => <main>{children}</main>,
  SettingsGroup: ({
    title,
    description,
    actions,
    children,
  }: {
    title?: string
    description?: React.ReactNode
    actions?: React.ReactNode
    children: React.ReactNode
  }) => (
    <section aria-label={title}>
      {description}
      {actions}
      {children}
    </section>
  ),
  SettingsRow: ({
    label,
    description,
    control,
  }: {
    label?: React.ReactNode
    description?: React.ReactNode
    control?: React.ReactNode
  }) => (
    <div>
      {label}
      {description}
      {control}
    </div>
  ),
  SettingsCallout: ({ children }: { children: React.ReactNode }) => <aside>{children}</aside>,
}))

vi.mock('@/components/settings/SettingsLoading', () => ({
  SettingsAsyncBoundary: ({ children }: { children: React.ReactNode }) => children,
}))

vi.mock('@/components/settings/SkillBundleEditor', () => ({
  SkillBundleEditor: ({ readOnly }: { readOnly?: boolean }) => (
    <div data-testid="bundle-editor" data-read-only={String(Boolean(readOnly))} />
  ),
}))

vi.mock('@/components/settings/SkillModeSelector', () => ({
  SkillModeSelector: ({ disabled }: { disabled?: boolean }) => (
    <button type="button" disabled={disabled}>Availability</button>
  ),
}))

vi.mock('@/contexts/SettingsContext', () => ({
  useSettingsParams: () => ({ name: 'code-graph-navigation' }),
  useSettingsNavigate: () => mocks.navigate,
  useSettingsSearch: () => ({ mode: mocks.searchMode }),
}))

vi.mock('@/hooks/useActiveSkillDiscoveryScope', () => ({
  useActiveSkillDiscoveryScope: () => ({ workspaces: mocks.activeWorkspaces }),
}))

vi.mock('@/lib/settings-dirty', () => ({
  useRegisterSettingsDirty: vi.fn(),
}))

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector: (state: { push: typeof mocks.push }) => unknown) =>
    selector({ push: mocks.push }),
}))

describe('SkillEditorPage runtime settings boundary', () => {
  beforeEach(() => {
    mocks.searchMode = 'coding'
    mocks.activeWorkspaces = []
    mocks.queryScope = null
  })

  it('keeps builtin bundle content read-only while runtime controls remain editable', () => {
    render(<SkillEditorPage />)

    expect(screen.getByTestId('bundle-editor')).toHaveAttribute('data-read-only', 'true')
    const discovery = screen.getByRole('switch', { name: 'Auto-discovery' })
    const invocation = screen.getByRole('switch', { name: 'Manual invocation' })
    expect(discovery).not.toHaveAttribute('aria-disabled', 'true')
    expect(invocation).not.toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('button', { name: 'Remove invalid override' })).toBeEnabled()
    expect(screen.getByText(/invalid EvoFlux runtime override was ignored/i)).toBeVisible()

    fireEvent.click(discovery)
    fireEvent.click(invocation)

    expect(discovery).not.toBeChecked()
    expect(invocation).not.toBeChecked()
  })

  it('keeps detail discovery unscoped when navigation omits mode in an active workspace', () => {
    mocks.searchMode = undefined
    mocks.activeWorkspaces = ['/repo/app']

    render(<SkillEditorPage />)

    expect(mocks.queryScope).toEqual({ workspaces: ['/repo/app'], mode: null })
  })
})
