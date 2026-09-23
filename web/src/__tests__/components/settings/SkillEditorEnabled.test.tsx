import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { SkillDetail } from '@/api/types'
import { SkillEditorPage } from '@/routes/settings.skills.$name'

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  push: vi.fn(),
  refetch: vi.fn(),
  update: vi.fn(),
  setEnabled: vi.fn(),
  remove: vi.fn(),
  queryScope: null as null | { workspaces?: readonly string[] | null },
  skill: null as unknown,
}))

function builtinSkill(overrides: Partial<SkillDetail> = {}): SkillDetail {
  return {
    name: 'pdf',
    description: 'Extracts text from PDF files. Use when working with PDFs.',
    location: '/app/agent/builtin_skills/pdf/SKILL.md',
    source: 'builtin',
    plugin_id: null,
    enabled: true,
    model_invocable: false,
    user_invocable: true,
    license: 'Apache-2.0',
    compatibility: 'Requires Python 3.12',
    allowed_tools: 'read shell',
    metadata: { author: 'evoflux' },
    valid: true,
    diagnostics: [],
    shadowed_paths: ['/home/u/.claude/skills/pdf/SKILL.md'],
    editable: false,
    symlinked: false,
    resource_count: 2,
    provider: null,
    content: '---\nname: pdf\ndescription: Extracts text.\n---\n\nRead the PDF.\n',
    files: [],
    bundle_truncated: false,
    ...overrides,
  }
}

vi.mock('@/queries', () => ({
  useSkillFileQuery: (_name: string, scope: { workspaces?: readonly string[] | null }) => {
    mocks.queryScope = scope
    return {
      data: mocks.skill,
      isLoading: false,
      isError: false,
      error: null,
      refetch: mocks.refetch,
    }
  },
  useUpdateSkillMutation: () => ({ isPending: false, mutateAsync: mocks.update }),
  useSetSkillEnabledMutation: () => ({ isPending: false, mutateAsync: mocks.setEnabled }),
  useDeleteSkillMutation: () => ({ isPending: false, mutateAsync: mocks.remove }),
}))

vi.mock('@/components/settings/EditorHeaderActions', () => ({
  EditorHeaderActions: () => null,
}))

vi.mock('@/components/settings/SettingsLayout', () => ({
  SettingsPage: ({ children }: { children: React.ReactNode }) => <main>{children}</main>,
  SettingsGroup: ({
    title,
    description,
    children,
  }: {
    title?: string
    description?: React.ReactNode
    children: React.ReactNode
  }) => (
    <section aria-label={title}>
      {description}
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

vi.mock('@/contexts/SettingsContext', () => ({
  useSettingsParams: () => ({ name: 'pdf' }),
  useSettingsNavigate: () => mocks.navigate,
}))

vi.mock('@/hooks/useActiveSkillDiscoveryScope', () => ({
  useActiveSkillDiscoveryScope: () => ({ workspaces: ['/repo/app'] }),
}))

vi.mock('@/lib/settings-dirty', () => ({
  useRegisterSettingsDirty: vi.fn(),
}))

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector: (state: { push: typeof mocks.push }) => unknown) =>
    selector({ push: mocks.push }),
}))

describe('SkillEditorPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.skill = builtinSkill()
    mocks.setEnabled.mockResolvedValue(builtinSkill({ enabled: false }))
  })

  it('queries the skill with workspace scope only', () => {
    render(<SkillEditorPage />)

    expect(mocks.queryScope).toEqual({ workspaces: ['/repo/app'] })
  })

  it('keeps a built-in bundle read-only while the Enabled switch stays usable', async () => {
    render(<SkillEditorPage />)

    expect(screen.getByTestId('bundle-editor')).toHaveAttribute('data-read-only', 'true')
    expect(screen.getByText(/Built-in skills are read-only/)).toBeVisible()
    const enabled = screen.getByRole('switch', { name: 'Enabled' })
    expect(enabled).toBeChecked()
    expect(enabled).not.toHaveAttribute('aria-disabled', 'true')

    fireEvent.click(enabled)

    await waitFor(() =>
      expect(mocks.setEnabled).toHaveBeenCalledWith({ name: 'pdf', enabled: false }),
    )
    expect(mocks.update).not.toHaveBeenCalled()
  })

  it('shows frontmatter facts, invocation flags and shadowed skills', () => {
    render(<SkillEditorPage />)

    expect(screen.getByText(/^Hidden from model/)).toBeVisible()
    expect(screen.queryByText(/^Not user-invocable/)).toBeNull()
    expect(screen.getByText('Apache-2.0')).toBeVisible()
    expect(screen.getByText('Requires Python 3.12')).toBeVisible()
    expect(screen.getByText('read shell')).toBeVisible()
    expect(screen.getByText('author')).toBeVisible()
    expect(screen.getByText('evoflux')).toBeVisible()
    expect(screen.getByText('/app/agent/builtin_skills/pdf/SKILL.md')).toBeVisible()
    expect(screen.getByText('/home/u/.claude/skills/pdf/SKILL.md')).toBeVisible()
    expect(screen.queryByRole('button', { name: /Delete skill/ })).toBeNull()
  })

  it('offers delete and an editable bundle for a user skill', () => {
    mocks.skill = builtinSkill({ source: 'user', editable: true })
    render(<SkillEditorPage />)

    expect(screen.getByTestId('bundle-editor')).toHaveAttribute('data-read-only', 'false')
    expect(screen.getByRole('button', { name: /Delete skill/ })).toBeEnabled()
  })
})
