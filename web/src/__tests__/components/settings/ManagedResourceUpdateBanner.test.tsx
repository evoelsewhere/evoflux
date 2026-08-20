import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ManagedResourceProvider } from '@/api/types'
import { ManagedResourceUpdateBanner } from '@/components/settings/ManagedResourceUpdateBanner'

const mocks = vi.hoisted(() => ({ pull: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  pullConductorResource: mocks.pull,
}))

const provider: ManagedResourceProvider = {
  project_id: 'project-1',
  project_name: 'Platform Core',
  resource_id: 'resource-1',
  modes: ['work', 'coding'],
  version_id: 'version-3',
  version: '2.0.0',
  applied_version_id: 'version-1',
  applied_version: '1.2.0',
  description: 'Audits releases before deployment.',
  changelog: 'Adds policy checks.',
  version_history: [
    {
      version_id: 'version-1',
      version: '1.2.0',
      status: 'deprecated',
      release_channel: 'published',
      changelog: 'Initial policy checks.',
      published_at: null,
      deprecation_reason: 'Known policy bypass.',
    },
    {
      version_id: 'version-2',
      version: '1.3.0',
      status: 'published',
      release_channel: 'published',
      changelog: 'Adds approval checks.',
      published_at: null,
      deprecation_reason: null,
    },
    {
      version_id: 'version-3',
      version: '2.0.0',
      status: 'published',
      release_channel: 'published',
      changelog: 'Adds policy checks.',
      published_at: null,
      deprecation_reason: null,
    },
  ],
  update_available: true,
  update_required: true,
  version_gap: 'major',
  current_version_deprecation_reason: 'Known policy bypass.',
  release_channel: 'published',
  observed_state: 'update_pending',
}

describe('ManagedResourceUpdateBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.pull.mockResolvedValue({
      ...provider,
      applied_version_id: provider.version_id,
      applied_version: provider.version,
      update_available: false,
      update_required: false,
      observed_state: 'applied',
      kind: 'agent',
      slug: 'release-auditor',
    })
  })

  it('requires change review before an explicit pull', async () => {
    const onPulled = vi.fn()
    render(
      <ManagedResourceUpdateBanner
        provider={provider}
        resourceName="Release auditor"
        onPulled={onPulled}
      />,
    )

    expect(screen.getByText(/Update required · v1.2.0 → v2.0.0/)).toBeVisible()
    expect(screen.getByText(/Known policy bypass/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Pull v2.0.0' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Review changes for Release auditor' }))

    expect(await screen.findByRole('dialog')).toBeVisible()
    expect(screen.getByText('Adds approval checks.')).toBeVisible()
    expect(screen.getByText('Adds policy checks.')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Pull v2.0.0' }))

    await waitFor(() => expect(mocks.pull).toHaveBeenCalledWith('resource-1'))
    expect(onPulled).toHaveBeenCalledTimes(1)
  })
})
