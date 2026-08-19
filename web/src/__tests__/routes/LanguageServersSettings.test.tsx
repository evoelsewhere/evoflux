import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import { LanguageServersSettingsPage } from '@/routes/settings.language-servers'

const mocks = vi.hoisted(() => ({
  mutate: vi.fn(),
  refetch: vi.fn(),
  useStatus: vi.fn(),
}))

vi.mock('@/stores/useTeamStore', () => ({
  useTeamStore: (selector: (state: { _workspace: string; projectId: string }) => unknown) =>
    selector({ _workspace: '/repo/api', projectId: 'project-1' }),
}))

vi.mock('@/queries/useProjectsQuery', () => ({
  useCodingOverviewQuery: () => ({
    data: {
      projects: [
        {
          id: 'project-1',
          workspaces: [
            { path: '/repo/web' },
            { path: '/repo/api' },
          ],
        },
      ],
    },
  }),
}))

vi.mock('@/queries', () => ({
  useLanguageServersQuery: (workspaces: readonly string[]) => mocks.useStatus(workspaces),
  useInstallLanguageServerMutation: () => ({
    mutate: mocks.mutate,
    isPending: false,
    variables: undefined,
    error: null,
  }),
}))

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
  mocks.mutate.mockReset()
  mocks.refetch.mockReset()
  mocks.useStatus.mockReset()
  mocks.useStatus.mockReturnValue({
    data: {
      workspaces: ['/repo/web', '/repo/api'],
      cache_dir: '/cache/language-servers',
      servers: [
        {
          language_id: 'typescript',
          display_name: 'TypeScript & JavaScript',
          extensions: ['.js', '.ts', '.tsx'],
          detected: true,
          file_count: 12,
          repositories: [
            { workspace: '/repo/web', name: 'web', file_count: 12 },
          ],
          state: 'missing',
          source: 'missing',
          command: null,
          installed_version: null,
          expected_version: '5.3.0',
          installable: true,
          installer: 'npm',
          installer_available: true,
          install_hint: 'Downloads pinned packages from https://registry.npmjs.org/.',
        },
      ],
    },
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: mocks.refetch,
  })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

it('aggregates project repositories and confirms a pinned install', () => {
  render(<LanguageServersSettingsPage />)

  expect(mocks.useStatus).toHaveBeenCalledWith(['/repo/web', '/repo/api'])
  expect(screen.getByText('TypeScript & JavaScript')).toBeInTheDocument()
  expect(screen.getByText(/12 matching files across web/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Install' }))
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('v5.3.0'))
  expect(mocks.mutate).toHaveBeenCalledWith('typescript')
})
