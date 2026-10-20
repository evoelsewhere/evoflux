import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BackgroundTaskCard } from '@/routes/settings.agents'

const queryMock = vi.hoisted(() => ({
  wakeIdle: true,
  mutate: vi.fn(),
}))

vi.mock('@/queries', () => ({
  useBackgroundTaskSettingsQuery: () => ({ data: { wake_idle: queryMock.wakeIdle } }),
  useUpdateBackgroundTaskSettingsMutation: () => ({ mutate: queryMock.mutate }),
  // Unused siblings imported by the settings page module.
  useAgentFilesQuery: () => ({ data: [] }),
  useRegistryQuery: () => ({ data: { agents: [], skills: [] } }),
  useBulkUpdateAgentModelMutation: () => ({ mutate: vi.fn() }),
  useFollowUpSettingsQuery: () => ({ data: { delivery: 'queue' } }),
  useResponseStyleSettingsQuery: () => ({ data: { style: 'visual' } }),
  useTeamSpawnSettingsQuery: () => ({ data: { work: 'ask', coding: 'ask' } }),
  useUpdateFollowUpSettingsMutation: () => ({ mutate: vi.fn() }),
  useUpdateResponseStyleSettingsMutation: () => ({ mutate: vi.fn() }),
  useUpdateTeamSpawnSettingsMutation: () => ({ mutate: vi.fn() }),
}))

beforeEach(() => {
  queryMock.wakeIdle = true
  queryMock.mutate.mockClear()
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }))
})

describe('BackgroundTaskCard', () => {
  it('defaults to waking an idle agent', () => {
    render(<BackgroundTaskCard />)

    expect(screen.getByRole('tab', { name: 'Wake agent' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('tab', { name: 'Wait' }).getAttribute('aria-selected')).toBe('false')
    expect(screen.getByText(/starts a new turn to handle the result/)).toBeTruthy()
  })

  it('explains the waiting behaviour when it is off', () => {
    queryMock.wakeIdle = false
    render(<BackgroundTaskCard />)

    expect(screen.getByRole('tab', { name: 'Wait' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByText(/joins your next message/)).toBeTruthy()
  })

  it('saves the chosen behaviour', () => {
    render(<BackgroundTaskCard />)

    fireEvent.click(screen.getByRole('tab', { name: 'Wait' }))

    expect(queryMock.mutate).toHaveBeenCalledWith({ wake_idle: false })
  })
})
