import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { NEW_SKILL_TEMPLATE, NewSkillPage } from '@/routes/settings.skills.new'
import { validateSkillDraft } from '@/components/settings/schema'

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  navigate: vi.fn(),
  push: vi.fn(),
  registerDirty: vi.fn(),
  nextContent: '',
}))

vi.mock('@/queries', () => ({
  useCreateSkillMutation: () => ({ isPending: false, mutateAsync: mocks.create }),
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
    children,
  }: {
    title?: string
    children: React.ReactNode
  }) => <section aria-label={title}>{children}</section>,
}))

vi.mock('@/components/settings/SkillBundleEditor', () => ({
  SkillBundleEditor: ({
    skillContent,
    files,
    onSkillContentChange,
  }: {
    skillContent: string
    files: unknown[]
    onSkillContentChange: (value: string) => void
  }) => (
    <div>
      <pre data-testid="skill-md">{skillContent}</pre>
      <span data-testid="file-count">{files.length}</span>
      <button type="button" onClick={() => onSkillContentChange(mocks.nextContent)}>
        Edit draft
      </button>
    </div>
  ),
}))

vi.mock('@/contexts/SettingsContext', () => ({
  useSettingsNavigate: () => mocks.navigate,
}))

vi.mock('@/lib/settings-dirty', () => ({
  useRegisterSettingsDirty: mocks.registerDirty,
}))

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector: (state: { push: typeof mocks.push }) => unknown) =>
    selector({ push: mocks.push }),
}))

describe('NewSkillPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.create.mockResolvedValue({})
  })

  it('scaffolds only a spec-compliant SKILL.md', () => {
    render(<NewSkillPage />)

    expect(screen.getByTestId('file-count')).toHaveTextContent('0')
    expect(validateSkillDraft(NEW_SKILL_TEMPLATE)).toBeNull()
    expect(NEW_SKILL_TEMPLATE).toMatch(/^---\nname: new-skill\ndescription: Describes /)
    expect(NEW_SKILL_TEMPLATE).not.toMatch(/agents\/|evals\/|display_name|default_prompt/)
  })

  it('is not dirty until the template changes', () => {
    mocks.nextContent = NEW_SKILL_TEMPLATE.replace('name: new-skill', 'name: pdf-tools')
    render(<NewSkillPage />)

    expect(mocks.registerDirty).toHaveBeenLastCalledWith(false)
    fireEvent.click(screen.getByRole('button', { name: 'Edit draft' }))
    expect(mocks.registerDirty).toHaveBeenLastCalledWith(true)
  })

  it('creates the skill under the frontmatter name with no scaffold files', async () => {
    mocks.nextContent = NEW_SKILL_TEMPLATE.replace('name: new-skill', 'name: pdf-tools')
    render(<NewSkillPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Edit draft' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1))
    expect(mocks.create).toHaveBeenCalledWith({
      name: 'pdf-tools',
      content: mocks.nextContent,
      files: [],
    })
    expect(mocks.navigate).toHaveBeenCalledWith('/settings/skills/$name', {
      params: { name: 'pdf-tools' },
      force: true,
    })
  })

  it('blocks names that break the Agent Skills rules', () => {
    mocks.nextContent = NEW_SKILL_TEMPLATE.replace('name: new-skill', 'name: claude-tools')
    render(<NewSkillPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Edit draft' }))

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })
})
