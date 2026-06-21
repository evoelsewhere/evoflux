import { describe, expect, it, mock } from 'bun:test'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { SettingsListView } from '@/components/settings/SettingsListView'

mock.module('@tanstack/react-router', () => ({
  Link: ({ to, children, ...rest }: { to: string; children: ReactNode; [k: string]: unknown }) => (
    <a href={to} {...rest}>{children}</a>
  ),
}))

function renderList() {
  render(
    <SettingsListView
      title="Agents"
      description="Manage agents."
      newTo="/settings/agents/new"
      newLabel="New agent"
      filterPlaceholder="Filter agents"
      rows={[
        {
          key: 'lead',
          to: '/settings/agents/$name',
          params: { name: 'lead' },
          title: 'lead',
          description: 'Primary agent',
        },
      ]}
      isLoading={false}
      isError={false}
      emptyTitle="No agents"
      emptyBody="Create an agent."
    />,
  )
}

describe('SettingsListView', () => {
  it('keeps settings list rows touch-sized and keyboard-focusable', () => {
    renderList()

    const row = screen.getByRole('link', { name: /lead/i })
    expect(row.className).toContain('min-h-11')
    expect(row.className).toContain('focus-visible:ring-3')
  })
})
