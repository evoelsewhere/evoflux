/**
 * SchedulerPanel — ``ModeWorkspaceFields`` subcomponent tests
 *
 * Covers the routing-control contract for scheduler task mode/workspace.
 * The workspace control is intentionally selection-only: coding tasks can
 * target saved coding workspaces, but the form does not expose raw path entry.
 */

import { describe, it, expect, beforeEach, mock } from 'bun:test'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import '@testing-library/jest-dom'
import { ModeWorkspaceFields } from '@/components/SchedulerPanel'
import type { ScheduledTaskMode } from '@/api/types'

interface State {
  mode: ScheduledTaskMode
  workspace: string | null
}

type Change = { mode: ScheduledTaskMode; workspace: string | null }

function renderFields(initial: State) {
  const onChangeSpy = mock(((_next: Change) => {}) as (
    ...args: unknown[]
  ) => unknown)

  function Harness() {
    const [state, setState] = React.useState<State>(initial)
    return (
      <>
        <div data-testid="mode-value">{state.mode}</div>
        <div data-testid="workspace-value">{state.workspace ?? '<null>'}</div>
        <ModeWorkspaceFields
          mode={state.mode}
          workspace={state.workspace}
          onChange={(next) => {
            onChangeSpy(next)
            setState((prev) => ({
              ...prev,
              mode: next.mode,
              workspace: next.workspace,
            }))
          }}
        />
      </>
    )
  }

  const utils = render(<Harness />)
  return { ...utils, onChangeSpy }
}

function readState() {
  return {
    mode: screen.getByTestId('mode-value').textContent,
    workspace: screen.getByTestId('workspace-value').textContent,
  }
}

beforeEach(() => {
  localStorage.clear()
})

describe('ModeWorkspaceFields — initial render', () => {
  it('hides the workspace selector when mode is normal', () => {
    renderFields({ mode: 'normal', workspace: null })

    expect(screen.queryByLabelText(/^Workspace$/i)).toBeNull()
    expect(screen.queryByLabelText(/Select workspace/i)).toBeNull()
    expect(screen.queryByPlaceholderText(/Absolute path/i)).toBeNull()
  })

  it('shows a workspace selector, not a path input, when mode is coding', () => {
    renderFields({ mode: 'coding', workspace: '/repo/app' })

    expect(screen.getByLabelText(/Select workspace/i)).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/Absolute path/i)).toBeNull()
  })

  it('reflects the active mode via aria-selected on the tab', () => {
    renderFields({ mode: 'coding', workspace: '/x' })

    const normalTab = screen.getByRole('tab', { name: 'Normal' })
    const codingTab = screen.getByRole('tab', { name: 'Coding' })

    expect(normalTab).toHaveAttribute('aria-selected', 'false')
    expect(codingTab).toHaveAttribute('aria-selected', 'true')
  })

  it('shows mode-specific helper text', () => {
    const { rerender } = renderFields({ mode: 'normal', workspace: null })
    expect(
      screen.getByText(/Delivers to the default team lead/i),
    ).toBeInTheDocument()

    rerender(
      <ModeWorkspaceFields
        mode="coding"
        workspace="/repo"
        onChange={() => {}}
      />,
    )
    expect(
      screen.getByText(/Delivers to the lead of the coding team/i),
    ).toBeInTheDocument()
  })
})

describe('ModeWorkspaceFields — mode toggle', () => {
  it('switches normal → coding without setting a workspace', async () => {
    const user = userEvent.setup()
    const { onChangeSpy } = renderFields({ mode: 'normal', workspace: null })

    await user.click(screen.getByRole('tab', { name: 'Coding' }))

    expect(onChangeSpy).toHaveBeenCalledTimes(1)
    expect(onChangeSpy.mock.calls[0][0]).toEqual({
      mode: 'coding',
      workspace: null,
    })
    expect(readState()).toEqual({ mode: 'coding', workspace: '<null>' })
  })

  it('switches coding → normal AND clears workspace in a single setState', async () => {
    const user = userEvent.setup()
    const { onChangeSpy } = renderFields({
      mode: 'coding',
      workspace: '/repo/app',
    })

    await user.click(screen.getByRole('tab', { name: 'Normal' }))

    expect(onChangeSpy).toHaveBeenCalledTimes(1)
    expect(onChangeSpy.mock.calls[0][0]).toEqual({
      mode: 'normal',
      workspace: null,
    })
    expect(readState()).toEqual({ mode: 'normal', workspace: '<null>' })
    expect(screen.queryByLabelText(/Select workspace/i)).toBeNull()
  })

  it('preserves selected workspace when re-tapping the active coding tab', async () => {
    const user = userEvent.setup()
    const { onChangeSpy } = renderFields({
      mode: 'coding',
      workspace: '/repo/app',
    })

    await user.click(screen.getByRole('tab', { name: 'Coding' }))

    expect(onChangeSpy).toHaveBeenCalledTimes(1)
    expect(onChangeSpy.mock.calls[0][0]).toEqual({
      mode: 'coding',
      workspace: '/repo/app',
    })
    expect(readState()).toEqual({
      mode: 'coding',
      workspace: '/repo/app',
    })
  })
})

describe('ModeWorkspaceFields — saved workspaces', () => {
  it('renders the workspace selector even when localStorage is empty', () => {
    renderFields({ mode: 'coding', workspace: null })

    expect(screen.getByLabelText(/Select workspace/i)).toBeInTheDocument()
    expect(screen.getByText(/Workspaces come from saved coding workspaces/i)).toBeInTheDocument()
  })

  it('shows the current workspace label even if it is not saved yet', () => {
    renderFields({ mode: 'coding', workspace: '/repo/current' })

    expect(screen.getByText('current')).toBeInTheDocument()
  })

  it('renders saved workspaces through a selector without exposing a path text field', () => {
    localStorage.setItem(
      'oa-coding-workspaces',
      JSON.stringify([
        { id: 'w1', path: '/repo/a', createdAt: '2024-01-01T00:00:00Z' },
        { id: 'w2', path: '/repo/b', createdAt: '2024-01-02T00:00:00Z' },
      ]),
    )

    renderFields({ mode: 'coding', workspace: null })

    expect(screen.getByLabelText(/Select workspace/i)).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/Absolute path/i)).toBeNull()
  })

  it('keeps the workspace selector hidden in normal mode', () => {
    localStorage.setItem(
      'oa-coding-workspaces',
      JSON.stringify([
        { id: 'w1', path: '/repo/a', createdAt: '2024-01-01T00:00:00Z' },
      ]),
    )

    renderFields({ mode: 'normal', workspace: null })

    expect(screen.queryByLabelText(/Select workspace/i)).toBeNull()
  })
})
