import { describe, expect, it, vi } from 'vitest'

import { useTeamCommands } from '@/components/TeamChatView/useTeamCommands'

type Args = Parameters<typeof useTeamCommands>[0]

function args(overrides: Partial<Args> = {}): Args {
  return {
    viewMode: 'agent',
    cycleViewMode: vi.fn(),
    setViewMode: vi.fn(),
    handleWorkspaceFiles: vi.fn(),
    handleCodingSidebarToggle: vi.fn(),
    mode: 'coding',
    workspace: null,
    handleNewSession: vi.fn(),
    handleDreamRun: vi.fn(),
    agentNames: [],
    leadName: null,
    cycleActiveAgent: vi.fn(),
    setActiveAgent: vi.fn(),
    navigate: vi.fn() as Args['navigate'],
    ...overrides,
  }
}

describe('Git AI command availability', () => {
  it('does not expose a no-op review command without a workspace', () => {
    const commands = useTeamCommands(args())

    expect(commands.some((command) => command.id === 'ai-review-changes')).toBe(false)
  })

  it('exposes review when a coding workspace can receive the action', () => {
    const commands = useTeamCommands(args({ workspace: '/work/evoflux' }))

    expect(commands.some((command) => command.id === 'ai-review-changes')).toBe(true)
  })
})
