import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SidePanel } from './SidePanel'

vi.mock('@/hooks/use-mobile', () => ({ useIsMobile: () => false }))
vi.mock('@/hooks/useReducedMotion', () => ({ useReducedMotion: () => false }))

describe('SidePanel forced overlay mode', () => {
  it('covers the viewport and disables resize independently of the mobile breakpoint', () => {
    render(
      <SidePanel
        storageKey="test-panel"
        defaultWidth={520}
        minWidth={480}
        maxWidth={720}
        mobileOverlay
        mobile
        forceOverlay
        ariaLabel="Workspace files"
      >
        Workspace
      </SidePanel>,
    )

    const panel = screen.getByRole('complementary', { name: 'Workspace files' })
    expect(panel).toHaveClass('fixed', 'inset-0', 'w-full')
    expect(panel).not.toHaveClass('mobile-safe-top')
    expect(screen.queryByRole('separator')).not.toBeInTheDocument()
  })

  it('clears the persisted docked width when switching into an overlay', async () => {
    const { rerender } = render(
      <SidePanel
        storageKey="responsive-panel"
        defaultWidth={520}
        minWidth={480}
        maxWidth={720}
        mobileOverlay
        animated={false}
        ariaLabel="Responsive workspace"
      >
        Workspace
      </SidePanel>,
    )

    rerender(
      <SidePanel
        storageKey="responsive-panel"
        defaultWidth={520}
        minWidth={480}
        maxWidth={720}
        mobileOverlay
        forceOverlay
        animated={false}
        ariaLabel="Responsive workspace"
      >
        Workspace
      </SidePanel>,
    )

    await waitFor(() => {
      expect(screen.getByRole('complementary', { name: 'Responsive workspace' })).toHaveStyle({ width: '100%' })
    })
  })
})
