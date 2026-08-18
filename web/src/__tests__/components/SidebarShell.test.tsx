import { render, screen } from '@testing-library/react'
import { CalendarClock } from 'lucide-react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  SidebarNavGroup,
  SidebarShell,
} from '@/components/shell/SidebarShell'
import { SidebarItem } from '@/components/ui/sidebar-item'
import { useUIStore } from '@/stores/useUIStore'

describe('SidebarShell', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
    useUIStore.getState().setSidebarWidth(320)
  })

  it('fully removes the sidebar footprint while collapsed', () => {
    const { container, rerender } = render(
      <SidebarShell collapsed>
        <div>Sidebar content</div>
      </SidebarShell>,
    )

    const shell = container.querySelector<HTMLElement>('[data-sidebar-shell]')
    expect(shell).toHaveStyle({ width: '0px', minWidth: '0px' })
    expect(shell).toHaveAttribute('aria-hidden', 'true')
    expect(screen.queryByText('Sidebar content')).not.toBeInTheDocument()

    rerender(
      <SidebarShell>
        <div>Sidebar content</div>
      </SidebarShell>,
    )

    expect(shell).toHaveStyle({ width: '320px', minWidth: '320px' })
    expect(shell).not.toHaveAttribute('aria-hidden')
    expect(screen.getByText('Sidebar content')).toBeInTheDocument()
  })

  it('keeps one deterministic rhythm for mode navigation items', () => {
    const { rerender } = render(
      <SidebarNavGroup ariaLabel="Primary" compact>
        <SidebarItem Icon={CalendarClock} label="Scheduler" compact />
        <SidebarItem Icon={CalendarClock} label="Plugins" compact />
      </SidebarNavGroup>,
    )

    expect(screen.getByRole('navigation', { name: 'Primary' })).toHaveClass(
      'gap-0.5',
    )
    expect(screen.getByRole('button', { name: 'Scheduler' })).toHaveClass(
      'h-8',
      'py-0',
    )

    rerender(
      <SidebarNavGroup ariaLabel="Primary">
        <SidebarItem Icon={CalendarClock} label="Scheduler" />
      </SidebarNavGroup>,
    )

    expect(screen.getByRole('navigation', { name: 'Primary' })).toHaveClass(
      'gap-1',
    )
    expect(screen.getByRole('button', { name: 'Scheduler' })).toHaveClass(
      'h-10',
      'py-0',
    )
  })
})
