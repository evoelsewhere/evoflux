import type { ReactNode } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { SkillsListPage } from '@/routes/settings.skills'

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  setEnabled: vi.fn(),
  push: vi.fn(),
}))

vi.mock('@/queries', () => ({
  useSkillFilesQuery: () => ({
    data: { skills: [] },
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useSetSkillEnabledMutation: () => ({ mutate: mocks.setEnabled, isPending: false }),
}))
vi.mock('@/contexts/SettingsContext', () => ({
  useSettingsNavigate: () => mocks.navigate,
  useSettingsParams: () => ({}),
}))
vi.mock('@/hooks/useActiveSkillDiscoveryScope', () => ({
  useActiveSkillDiscoveryScope: () => 'user',
}))
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector: (state: { push: typeof mocks.push }) => unknown) =>
    selector({ push: mocks.push }),
}))
vi.mock('@/components/settings/SettingsListView', () => ({
  SettingsListView: ({ newAction }: { newAction?: ReactNode }) => <main>{newAction}</main>,
}))
vi.mock('@/components/settings/SkillRecordingWizard', () => ({
  SkillRecordingWizard: ({ open, onOpenChange }: {
    open: boolean
    onOpenChange: (open: boolean) => void
  }) => open ? (
    <div role="dialog">
      <button onClick={() => onOpenChange(false)}>Close popup</button>
    </div>
  ) : null,
}))

describe('SkillsListPage recording entry', () => {
  beforeEach(() => vi.clearAllMocks())

  it('opens the recording popup without navigating to another settings screen', () => {
    render(<SkillsListPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Create from recording' }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(mocks.navigate).not.toHaveBeenCalled()
  })

  it('opens the popup for the legacy recording route and returns to Skills when dismissed', () => {
    render(<SkillsListPage initialRecordingOpen />)

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Close popup' }))
    expect(mocks.navigate).toHaveBeenCalledWith('/settings/skills', { force: true })
  })
})
