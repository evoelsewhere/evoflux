import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ManagedResourceProviderBadge } from '@/components/settings/ManagedResourceProviderBadge'

const provider = {
  project_id: 'project-1',
  project_name: 'Platform Core',
  resource_id: 'resource-1',
  version_id: 'version-2',
  version: '0.2.0',
  applied_version_id: 'version-1',
  applied_version: '0.1.0',
  release_channel: 'published' as const,
  observed_state: 'update_pending' as const,
}

describe('ManagedResourceProviderBadge', () => {
  it('shows the Conductor project as the provider', () => {
    render(<ManagedResourceProviderBadge provider={provider} />)

    expect(screen.getByText('provider: Platform Core')).toBeVisible()
    expect(screen.getByLabelText('Update available')).toBeVisible()
  })

  it('can disclose the managed lifecycle state on detail pages', () => {
    render(<ManagedResourceProviderBadge provider={provider} showState />)

    expect(screen.getByText('Update available')).toBeVisible()
  })
})
