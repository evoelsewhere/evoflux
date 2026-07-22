import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AppShell } from './AppShell'

describe('AppShell full-height trailing slot', () => {
  it('renders the full-height panel beside the entire header/body column', () => {
    render(
      <AppShell
        sidebar={<aside data-testid="sidebar">Sidebar</aside>}
        header={<header data-testid="header">Header</header>}
        trailing={<aside data-testid="body-trailing">Body trailing</aside>}
        fullHeightTrailing={<aside data-testid="full-height-trailing">Workspace</aside>}
      >
        Main
      </AppShell>,
    )

    const header = screen.getByTestId('header')
    const workspace = screen.getByTestId('full-height-trailing')
    const bodyTrailing = screen.getByTestId('body-trailing')

    expect(workspace.parentElement).toBe(header.parentElement?.parentElement)
    expect(workspace.parentElement).not.toBe(bodyTrailing.parentElement)
  })
})
