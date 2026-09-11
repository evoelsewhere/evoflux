/**
 * Quoted composer context must not disable slash commands.
 *
 * The composer prepends "Selected from chat" as ``> `` lines, so a command
 * the user typed stops being the message's first token. Every interceptor in
 * ``useSlashCommandRegistry`` matches on that first token, which used to send
 * "> quoted\n\n/goal ship it" to the model as ordinary prose.
 */
import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({
  renderCommand: vi.fn(),
  renderSnippet: vi.fn(),
  resolveApiUrl: vi.fn(),
  runWorkflow: vi.fn(),
  postTeamChat: vi.fn(),
  getTeamGoal: vi.fn(),
  cancelQueuedTeamMessage: vi.fn(),
  getRegistry: vi.fn(),
  listTeamAgents: vi.fn(),
  postTeamCommand: vi.fn(),
  teamHistory: vi.fn(),
  teamStream: vi.fn(),
}))

vi.mock('@/api/client', () => apiMocks)
vi.mock('@/queries/useCommandsQuery', () => ({
  useCommandsQuery: () => ({
    data: { commands: [{ name: 'triage', description: 'Triage a bug', source: 'user' }] },
  }),
}))
vi.mock('@/queries/useSkillFilesQuery', () => ({
  useSkillFilesQuery: () => ({ data: { skills: [] } }),
}))
vi.mock('@/queries/useSnippetsQuery', () => ({
  useSnippetsQuery: () => ({ data: { snippets: [] } }),
}))
vi.mock('@/queries/useWorkflowsQuery', () => ({
  useWorkflowsQuery: () => ({
    data: {
      workflows: [
        {
          name: 'bug-triage',
          description: 'Triage inbound bugs',
          approved: true,
          valid: true,
          scope: 'work',
          inputs: [],
        },
      ],
    },
  }),
}))

import { useSlashCommandRegistry } from '@/components/TeamChatView/useSlashCommandRegistry'
import { useTeamStore } from '@/stores/useTeamStore'
import { useToastStore } from '@/stores/useToastStore'

const QUOTE = '> the retry loop never backs off\n\n'

function setup() {
  return renderHook(() =>
    useSlashCommandRegistry({
      mode: 'work',
      workspace: null,
      agentWorkspace: null,
      sessionId: 'session-1',
      sessionIdState: 'session-1',
      selectedModel: '',
      selectedThinkingLevel: null,
      inputRef: { current: null },
      handleNewSession: vi.fn(),
    }),
  )
}

type SendGoalCommand = NonNullable<
  ReturnType<typeof useTeamStore.getState>['sendGoalCommand']
>
let sendGoalCommand: ReturnType<typeof vi.fn<SendGoalCommand>>

beforeEach(() => {
  vi.clearAllMocks()
  useToastStore.setState({ toasts: [] })
  sendGoalCommand = vi.fn<SendGoalCommand>().mockResolvedValue(undefined)
  useTeamStore.setState({ sendGoalCommand })
})

describe('slash commands sent with quoted chat context', () => {
  it('starts the goal and carries the quote into the objective', async () => {
    const { result } = setup()

    expect(
      await result.current.tryHandleBuiltinGoalCommand(`${QUOTE}/goal fix the backoff`),
    ).toBe(true)

    const [command, objective] = sendGoalCommand.mock.calls[0]
    expect(command).toBe('/goal fix the backoff\n\n> the retry loop never backs off')
    expect(objective).toBe('fix the backoff\n\n> the retry loop never backs off')
  })

  it('runs a workflow and says the quote could not come along', async () => {
    const { result } = setup()

    expect(await result.current.tryHandleWorkflowCommand(`${QUOTE}/workflow bug-triage`)).toBe(true)

    expect(apiMocks.runWorkflow).toHaveBeenCalledWith('bug-triage', 'session-1', {}, null)
    expect(useToastStore.getState().toasts.map((t) => t.title)).toContain(
      'Quoted context was not included',
    )
  })

  it('expands a custom command and keeps the quote in front of the body', async () => {
    apiMocks.renderCommand.mockResolvedValue({ content: 'Triage checklist:\n1. reproduce' })
    const { result } = setup()

    const expanded = await result.current.expandUserCommand(`${QUOTE}/triage now`)

    expect(apiMocks.renderCommand).toHaveBeenCalledWith('triage', 'now', null)
    expect(expanded).toBe(`${QUOTE}Triage checklist:\n1. reproduce`)
  })

  it('leaves an ordinary quoted message untouched', async () => {
    const { result } = setup()
    const message = `${QUOTE}what causes this?`

    expect(await result.current.tryHandleBuiltinGoalCommand(message)).toBe(false)
    expect(await result.current.tryHandleWorkflowCommand(message)).toBe(false)
    expect(await result.current.expandUserCommand(message)).toBe(message)
    expect(apiMocks.renderCommand).not.toHaveBeenCalled()
  })
})
