import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { NewSkillPage } from '@/routes/settings.skills.new'

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  updateSettings: vi.fn(),
  navigate: vi.fn(),
  push: vi.fn(),
}))

vi.mock('@/queries', () => ({
  useCreateSkillMutation: () => ({ isPending: false, mutateAsync: mocks.create }),
  useUpdateSkillSettingsMutation: () => ({
    isPending: false,
    mutateAsync: mocks.updateSettings,
  }),
}))

vi.mock('@/components/settings/EditorHeaderActions', () => ({
  EditorHeaderActions: ({
    onSave,
    invalid,
    saving,
  }: {
    onSave: () => void
    invalid: boolean
    saving: boolean
  }) => (
    <button type="button" onClick={onSave} disabled={invalid || saving}>
      Save
    </button>
  ),
}))

vi.mock('@/components/settings/SettingsLayout', () => ({
  SettingsPage: ({
    actions,
    children,
  }: {
    actions?: React.ReactNode
    children: React.ReactNode
  }) => (
    <main>
      {actions}
      {children}
    </main>
  ),
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
}))

vi.mock('@/components/settings/SkillModeSelector', () => ({
  SkillModeSelector: () => <div>All modes</div>,
}))

vi.mock('@/components/settings/SkillBundleEditor', () => ({
  SkillBundleEditor: ({
    onSkillContentChange,
  }: {
    onSkillContentChange: (value: string) => void
  }) => (
    <button
      type="button"
      onClick={() =>
        onSkillContentChange(
          '---\nname: audit-runtime-skill\ndescription: Audit runtime settings.\n---\n',
        )
      }
    >
      Rename draft
    </button>
  ),
}))

vi.mock('@/contexts/SettingsContext', () => ({
  useSettingsNavigate: () => mocks.navigate,
}))

vi.mock('@/lib/settings-dirty', () => ({
  useRegisterSettingsDirty: vi.fn(),
}))

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector: (state: { push: typeof mocks.push }) => unknown) =>
    selector({ push: mocks.push }),
}))

function createdSkill() {
  return {
    settings_id: 'skill_0123456789abcdef0123456789abcdef',
    modes: ['work', 'coding', 'aim'],
    allow_implicit_invocation: true,
    user_invocable: true,
  }
}

describe('NewSkillPage runtime settings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.create.mockResolvedValue(createdSkill())
    mocks.updateSettings.mockResolvedValue(createdSkill())
  })

  it('shows discovery controls and persists changed values after creating the bundle', async () => {
    render(<NewSkillPage />)

    const discovery = screen.getByRole('switch', { name: 'Auto-discovery' })
    const invocation = screen.getByRole('switch', { name: 'Manual invocation' })
    expect(discovery).toBeChecked()
    expect(invocation).toBeChecked()

    fireEvent.click(discovery)
    fireEvent.click(invocation)
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1))
    expect(mocks.updateSettings).toHaveBeenCalledWith({
      name: 'new-skill',
      settings: {
        settings_id: 'skill_0123456789abcdef0123456789abcdef',
        modes: ['work', 'coding', 'aim'],
        allow_implicit_invocation: false,
        user_invocable: false,
      },
    })
    expect(mocks.navigate).toHaveBeenCalledWith('/settings/skills/$name', {
      params: { name: 'new-skill' },
      force: true,
    })
  })

  it('does not create a redundant runtime override for bundle defaults', async () => {
    render(<NewSkillPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1))
    expect(mocks.updateSettings).not.toHaveBeenCalled()
  })

  it('keeps generated bundle identities aligned with a renamed skill', async () => {
    render(<NewSkillPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Rename draft' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1))
    const request = mocks.create.mock.calls[0]?.[0]
    expect(request.name).toBe('audit-runtime-skill')
    expect(request.files).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          path: 'agents/evoflux.yaml',
          content: expect.stringContaining('display_name: Audit Runtime Skill'),
        }),
        expect.objectContaining({
          path: 'agents/evoflux.yaml',
          content: expect.stringContaining('default_prompt: Use $audit-runtime-skill'),
        }),
        expect.objectContaining({
          path: 'evals/trigger-cases.json',
          content: expect.stringContaining('"skill": "audit-runtime-skill"'),
        }),
      ]),
    )
  })

  it('reports a partial save and opens the created skill when settings fail', async () => {
    mocks.updateSettings.mockRejectedValue(new Error('settings store unavailable'))
    render(<NewSkillPage />)

    fireEvent.click(screen.getByRole('switch', { name: 'Auto-discovery' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(mocks.push).toHaveBeenCalledWith(
        expect.objectContaining({
          tone: 'info',
          title: 'Skill created; settings failed',
        }),
      ),
    )
    expect(mocks.navigate).toHaveBeenCalledWith('/settings/skills/$name', {
      params: { name: 'new-skill' },
      force: true,
    })
  })
})
