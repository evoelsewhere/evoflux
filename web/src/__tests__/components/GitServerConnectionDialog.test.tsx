import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ConnectionDialog } from '@/components/PullRequestsPanel'
import type { GitServerConnection, RepositoryCodeReviews } from '@/api/types'

const target: RepositoryCodeReviews = {
  workspace_id: 'workspace-1',
  project_id: 'project-1',
  workspace: '/work/evoflux',
  name: 'evoflux',
  remote_url: 'https://github.com/khuonghung/evoflux.git',
  repository: 'khuonghung/evoflux',
  detected_provider: 'github',
  suggested_domain: 'https://github.com',
  suggested_base_url: 'https://api.github.com',
  connection_id: 'connection-1',
  provider: 'github',
  items: [],
  error: null,
}

const connection: GitServerConnection = {
  id: 'connection-1',
  name: 'evoflux connection',
  provider: 'github',
  domain: 'https://github.com',
  base_url: 'https://api.github.com',
  token_url: 'https://github.com/settings/tokens/new',
  host: 'github.com',
  scope: 'repository',
  workspace_id: 'workspace-1',
  token_env_var: 'EVOFLUX_GIT_TOKEN_CONNECTION_1',
  has_token: true,
  username: null,
  verify_ssl: true,
  created_at: '2026-08-12T08:00:00Z',
  updated_at: '2026-08-13T08:00:00Z',
}

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
})

function renderDialog(savedConnection: GitServerConnection | null) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ConnectionDialog
        target={target}
        connection={savedConnection}
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  )
}

describe('Git server connection dialog', () => {
  it('shows saved configuration details before exposing the edit form', () => {
    renderDialog(connection)

    expect(screen.getByRole('heading', { name: 'Git server connection' })).toBeVisible()
    expect(screen.getByRole('region', { name: 'Saved Git server connection' })).toHaveTextContent(
      'evoflux connection',
    )
    expect(screen.getByText('GitHub / Enterprise')).toBeVisible()
    expect(screen.getByText('https://api.github.com')).toBeVisible()
    expect(screen.getByText('Saved securely')).toBeVisible()
    expect(screen.queryByLabelText('Connection name')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Edit connection' }))

    expect(screen.getByRole('heading', { name: 'Edit Git server connection' })).toBeVisible()
    expect(screen.getByText('Connection name')).toBeVisible()
    expect(screen.getByDisplayValue('evoflux connection')).toBeVisible()
  })

  it('does not fall back to a blank form while saved metadata is loading', () => {
    renderDialog(null)

    expect(screen.getByText('Saved connection details are unavailable. Refresh connections and try again.')).toBeVisible()
    expect(screen.queryByText('Connection name')).not.toBeInTheDocument()
  })
})
