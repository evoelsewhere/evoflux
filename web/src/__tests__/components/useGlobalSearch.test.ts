/**
 * The command palette's content search: what it asks for, what it does with
 * the answer, and what happens when one of its two sources fails.
 */
import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useGlobalSearch } from '@/components/TeamChatView/useGlobalSearch'
import { useUIStore } from '@/stores/useUIStore'
import type { AppSearchItem } from '@/api/types'

const searchApp = vi.fn()
const searchEverywhere = vi.fn()

vi.mock('@/api/client', () => ({
  searchApp: (...args: unknown[]) => searchApp(...args),
  searchEverywhere: (...args: unknown[]) => searchEverywhere(...args),
}))

function appItem(overrides: Partial<AppSearchItem> & Pick<AppSearchItem, 'kind'>): AppSearchItem {
  return {
    id: `${overrides.kind}:1`,
    label: 'label',
    description: 'description',
    session_id: null,
    path: null,
    metadata: null,
    ...overrides,
  }
}

function search(args: Partial<Parameters<typeof useGlobalSearch>[0]> = {}) {
  const navigate = vi.fn()
  const openFile = vi.fn()
  const fillComposer = vi.fn()
  const { result } = renderHook(() =>
    useGlobalSearch({
      mode: 'work',
      workspace: null,
      turnChanges: null,
      navigate: navigate as never,
      openFile,
      fillComposer,
      ...args,
    }),
  )
  return { run: result.current, navigate, openFile, fillComposer }
}

beforeEach(() => {
  searchApp.mockReset().mockResolvedValue({ items: [] })
  searchEverywhere.mockReset().mockResolvedValue({ items: [] })
})

it('searches the application in Work mode, without a repository call', async () => {
  searchApp.mockResolvedValue({
    items: [appItem({ kind: 'session', id: 'session:7', label: 'Billing rewrite', session_id: '7' })],
  })
  const { run, navigate } = search()

  const commands = await run('billing', new AbortController().signal)

  expect(searchEverywhere).not.toHaveBeenCalled()
  expect(commands.map((command) => command.group)).toEqual(['Chats'])
  commands[0].action()
  expect(navigate).toHaveBeenCalledWith({ to: '/$sessionId', params: { sessionId: '7' } })
})

it('adds repository results once a Coding workspace is open', async () => {
  searchEverywhere.mockResolvedValue({
    items: [{
      id: 'file:app.py',
      kind: 'file',
      label: 'app.py',
      description: 'Repository file',
      path: 'app.py',
      line: null,
      metadata: { size: 12, mtime: 34, mime: 'text/x-python' },
    }],
  })
  const { run, openFile } = search({ mode: 'coding', workspace: '/repo' })

  const commands = await run('app', new AbortController().signal)

  expect(searchEverywhere).toHaveBeenCalledWith('/repo', 'app', 50, expect.any(AbortSignal))
  expect(commands.map((command) => command.group)).toEqual(['Files'])
  commands[0].action()
  expect(openFile).toHaveBeenCalledWith({
    path: 'app.py',
    name: 'app.py',
    size: 12,
    mtime: 34,
    mime: 'text/x-python',
  })
})

it('keeps one source when the other fails', async () => {
  searchApp.mockRejectedValue(new Error('offline'))
  searchEverywhere.mockResolvedValue({
    items: [{
      id: 'git-branch:main',
      kind: 'git_branch',
      label: 'main',
      description: 'Git branch',
      path: null,
      line: null,
      metadata: null,
    }],
  })
  const { run } = search({ mode: 'coding', workspace: '/repo' })

  const commands = await run('main', new AbortController().signal)

  expect(commands.map((command) => command.group)).toEqual(['Git'])
})

it('shows a result date the way sidebar rows do', async () => {
  searchApp.mockResolvedValue({
    items: [appItem({
      kind: 'session',
      id: 'session:7',
      session_id: '7',
      metadata: { mode: 'work', updated_at: '2026-09-19T08:30:00Z' },
    })],
  })
  const { run } = search()

  const [command] = await run('atlas', new AbortController().signal)

  expect(command.meta).toBeTruthy()
})

it('opens the session that owns a matched message', async () => {
  searchApp.mockResolvedValue({
    items: [appItem({
      kind: 'message',
      id: 'message:9',
      label: '…the refund webhook retries…',
      session_id: 'lead-1',
    })],
  })
  const { run, navigate } = search()

  const [command] = await run('refund', new AbortController().signal)
  command.action()

  expect(navigate).toHaveBeenCalledWith({ to: '/$sessionId', params: { sessionId: 'lead-1' } })
})

describe('a session opens under the shell that owns it', () => {
  it('sends a Coding session anchored to a repository to its focus route', async () => {
    searchApp.mockResolvedValue({
      items: [appItem({
        kind: 'session',
        id: 'session:7',
        session_id: '7',
        metadata: { mode: 'coding', workspace: '/repos/atlas', project_id: null },
      })],
    })
    const { run, navigate } = search()

    const [command] = await run('atlas', new AbortController().signal)
    command.action()

    expect(navigate).toHaveBeenCalledWith({
      to: '/coding/$focusId/$sessionId',
      params: { focusId: '/repos/atlas', sessionId: '7' },
    })
  })

  it('prefers the project over the repository for a project session', async () => {
    searchApp.mockResolvedValue({
      items: [appItem({
        kind: 'message',
        id: 'message:9',
        session_id: 'lead-1',
        metadata: { mode: 'coding', workspace: '/repos/atlas', project_id: 'proj-1' },
      })],
    })
    const { run, navigate } = search()

    const [command] = await run('atlas', new AbortController().signal)
    command.action()

    expect(navigate).toHaveBeenCalledWith({
      to: '/coding/$focusId/$sessionId',
      params: { focusId: 'proj-1', sessionId: 'lead-1' },
    })
  })

  it('keeps a Coding session with no workspace on the Work route', async () => {
    searchApp.mockResolvedValue({
      items: [appItem({
        kind: 'session',
        id: 'session:8',
        session_id: '8',
        metadata: { mode: 'coding', workspace: null, project_id: null },
      })],
    })
    const { run, navigate } = search()

    const [command] = await run('atlas', new AbortController().signal)
    command.action()

    expect(navigate).toHaveBeenCalledWith({ to: '/$sessionId', params: { sessionId: '8' } })
  })
})

describe('application rows route to the surface that owns them', () => {
  it('opens a Memory page in the Memory panel', async () => {
    searchApp.mockResolvedValue({
      items: [appItem({ kind: 'memory', id: 'memory:topics/atlas.md', path: 'topics/atlas.md' })],
    })
    const { run } = search()

    const [command] = await run('atlas', new AbortController().signal)
    command.action()

    expect(useUIStore.getState().wikiFileRequest?.path).toBe('topics/atlas.md')
  })

  it('scopes the Coding sidebar to a matched repository', async () => {
    searchApp.mockResolvedValue({
      items: [appItem({ kind: 'workspace', id: 'workspace:1', path: '/repos/atlas' })],
    })
    const { run, navigate } = search()

    const [command] = await run('atlas', new AbortController().signal)
    command.action()

    expect(useUIStore.getState().codingScopeRequest?.workspace).toBe('/repos/atlas')
    // Same anchor the sidebar's own repository row navigates to.
    expect(navigate).toHaveBeenCalledWith({
      to: '/coding/$focusId',
      params: { focusId: '/repos/atlas' },
    })
  })

  it('opens an agent definition in Settings', async () => {
    searchApp.mockResolvedValue({
      items: [appItem({ kind: 'agent', id: 'agent:reviewer', metadata: { name: 'reviewer' } })],
    })
    const { run } = search()

    const [command] = await run('reviewer', new AbortController().signal)
    command.action()

    expect(useUIStore.getState().settingsPath).toBe('agents/reviewer')
  })
})

it('offers files the latest turn changed before anything is fetched', async () => {
  const { run, openFile } = search({
    turnChanges: { files: [{ path: 'app/auth.py' }, { path: 'web/main.ts' }] } as never,
  })

  const commands = await run('auth', new AbortController().signal)

  expect(commands.map((command) => command.label)).toEqual(['app/auth.py'])
  commands[0].action()
  expect(openFile).toHaveBeenCalledWith(expect.objectContaining({ path: 'app/auth.py' }))
})
