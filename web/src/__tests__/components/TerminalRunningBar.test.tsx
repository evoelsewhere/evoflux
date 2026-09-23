/**
 * The Processes workbench tool folded into Terminal: each Terminal tab carries
 * a "Running" bar listing what the process manager keeps alive, minus the
 * tab's own PTY, with the current session's processes first.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ManagedProcess } from '@/api/types'
import { TerminalRunningBar } from '@/components/TerminalRunningBar'

const mocks = vi.hoisted(() => ({
  processes: vi.fn(),
  queryArgs: vi.fn(),
  terminate: vi.fn(),
}))

vi.mock('@/queries/useProcessesQuery', () => ({
  useProcessesQuery: (enabled: boolean) => {
    mocks.queryArgs(enabled)
    return {
      data: { processes: mocks.processes() },
      isPending: false,
      isError: false,
      isFetching: false,
      refetch: vi.fn(),
    }
  },
  useTerminateProcessMutation: () => ({
    mutate: mocks.terminate,
    isPending: false,
    variables: undefined,
  }),
}))

function process(overrides: Partial<ManagedProcess>): ManagedProcess {
  return {
    id: 'p',
    kind: 'command',
    label: 'Command',
    command: 'echo hi',
    session_id: 'session-1',
    session_title: 'Current chat',
    pid: 100,
    cwd: '/repo',
    elapsed_seconds: 5,
    killable: true,
    metadata: {},
    ...overrides,
  }
}

beforeEach(() => {
  mocks.terminate.mockReset()
  mocks.processes.mockReturnValue([
    process({ id: 'own', kind: 'terminal', label: 'Terminal tab-1', metadata: { terminal_id: 'tab-1' } }),
    process({ id: 'other-tab', kind: 'terminal', label: 'Terminal tab-2', metadata: { terminal_id: 'tab-2' } }),
    process({ id: 'dev', kind: 'preview', label: 'vite', command: 'bun dev', metadata: { url: 'http://localhost:5173' } }),
    process({ id: 'elsewhere', label: 'pytest', command: 'pytest', session_id: 'session-2', session_title: 'Other chat' }),
  ])
})

function bar(active = true) {
  return render(<TerminalRunningBar active={active} sessionId="session-1" terminalId="tab-1" />)
}

describe('Terminal running bar', () => {
  it('starts collapsed with a count that leaves out its own terminal', () => {
    bar()

    const toggle = screen.getByRole('button', { name: /Running/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle).toHaveTextContent('3')
    expect(screen.queryByText('vite')).not.toBeInTheDocument()
  })

  it('lists this session first, then other sessions', () => {
    bar()
    fireEvent.click(screen.getByRole('button', { name: /Running/ }))

    const headings = screen.getAllByRole('heading').map((heading) => heading.textContent)
    expect(headings).toEqual(['This session', 'Other chat'])
    expect(screen.queryByText('Terminal tab-1')).not.toBeInTheDocument()
    expect(screen.getByText('Terminal tab-2')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open http://localhost:5173' })).toBeInTheDocument()
  })

  it('stops a process from its row', () => {
    bar()
    fireEvent.click(screen.getByRole('button', { name: /Running/ }))

    fireEvent.click(screen.getByRole('button', { name: 'Stop pytest' }))
    expect(mocks.terminate).toHaveBeenCalledWith('elsewhere')
  })

  it('polls only while its tab is visible', () => {
    bar(false)
    expect(mocks.queryArgs).toHaveBeenLastCalledWith(false)
  })
})
