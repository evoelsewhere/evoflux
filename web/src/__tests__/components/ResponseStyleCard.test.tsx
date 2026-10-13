import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ResponseStyleCard } from '@/routes/settings.agents'

const queryMock = vi.hoisted(() => ({
  style: 'visual' as 'simple' | 'visual',
  mutate: vi.fn(),
}))

vi.mock('@/queries', () => ({
  useResponseStyleSettingsQuery: () => ({ data: { style: queryMock.style } }),
  useUpdateResponseStyleSettingsMutation: () => ({ mutate: queryMock.mutate }),
  // Unused siblings imported by the settings page module — stubbed so the
  // page module's import graph stays light under jsdom.
  useAgentFilesQuery: () => ({ data: [] }),
  useRegistryQuery: () => ({ data: { agents: [], skills: [] } }),
  useBulkUpdateAgentModelMutation: () => ({ mutate: vi.fn() }),
  useFollowUpSettingsQuery: () => ({ data: { delivery: 'queue' } }),
  useTeamSpawnSettingsQuery: () => ({ data: { work: 'ask', coding: 'ask' } }),
  useUpdateFollowUpSettingsMutation: () => ({ mutate: vi.fn() }),
  useUpdateTeamSpawnSettingsMutation: () => ({ mutate: vi.fn() }),
}))

beforeEach(() => {
  queryMock.style = 'visual'
  queryMock.mutate.mockClear()
  // SegmentedControl's motion reads prefers-reduced-motion via matchMedia,
  // which jsdom does not implement.
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

describe('ResponseStyleCard', () => {
  it('renders both style options with the saved one active', () => {
    render(<ResponseStyleCard />)

    const simple = screen.getByRole('tab', { name: 'Simple' })
    const visual = screen.getByRole('tab', { name: 'Visual' })
    expect(simple).toBeTruthy()
    expect(visual).toBeTruthy()
    expect(simple.getAttribute('aria-selected')).toBe('false')
    expect(visual.getAttribute('aria-selected')).toBe('true')
  })

  it('shows the visual lede by default and the simple lede when simple', () => {
    const { rerender } = render(<ResponseStyleCard />)
    expect(screen.getByText(/Replies may use headings/)).toBeTruthy()

    queryMock.style = 'simple'
    rerender(<ResponseStyleCard />)
    expect(screen.getByText(/Replies default to plain prose/)).toBeTruthy()
  })

  it('mutates with the chosen style when Simple is clicked', () => {
    render(<ResponseStyleCard />)

    fireEvent.click(screen.getByRole('tab', { name: 'Simple' }))

    expect(queryMock.mutate).toHaveBeenCalledWith({ style: 'simple' })
  })
})
