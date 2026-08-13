import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { MacTitleBar } from '@/components/MacTitleBar'
import { AppShell } from '@/components/shell/AppShell'
import { useUIStore } from '@/stores/useUIStore'

const navigation = vi.hoisted(() => {
  type Location = {
    pathname: string
    state: { __TSR_index: number }
  }
  type Action = { type: 'PUSH' | 'REPLACE' | 'BACK' | 'FORWARD' | 'GO' }
  type Subscriber = (value: { location: Location; action: Action }) => void

  const subscribers = new Set<Subscriber>()
  const history = {
    location: { pathname: '/', state: { __TSR_index: 0 } } as Location,
    subscribe: vi.fn((subscriber: Subscriber) => {
      subscribers.add(subscriber)
      return () => subscribers.delete(subscriber)
    }),
    back: vi.fn(),
    forward: vi.fn(),
  }

  return {
    history,
    subscribers,
    location: history.location,
    visit(index: number, action: Action['type']) {
      const location = { pathname: '/', state: { __TSR_index: index } }
      this.location = location
      history.location = location
      subscribers.forEach((subscriber) => subscriber({
        location,
        action: { type: action },
      }))
    },
  }
})

vi.mock('@tanstack/react-router', () => ({
  useLocation: () => navigation.location,
  useRouter: () => ({ history: navigation.history }),
}))

vi.mock('@/hooks/use-platform', () => ({
  usePlatform: () => ({ isTauri: true, os: 'macos', isMacOverlay: true }),
}))

vi.mock('@/hooks/use-tauri-drag', () => ({
  useTauriDrag: () => ({}),
}))

describe('MacTitleBar', () => {
  beforeEach(() => {
    navigation.subscribers.clear()
    navigation.location = { pathname: '/', state: { __TSR_index: 0 } }
    navigation.history.location = navigation.location
    navigation.history.subscribe.mockClear()
    navigation.history.back.mockReset()
    navigation.history.forward.mockReset()
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
    useUIStore.getState().closeSettings()
    useUIStore.getState().setSidebarCollapsed(false)
  })

  it('enables Back and Forward as the application history changes', () => {
    const { rerender } = render(<MacTitleBar />)
    const back = screen.getByRole('button', { name: 'Back' })
    const forward = screen.getByRole('button', { name: 'Forward' })

    expect(back).toBeDisabled()
    expect(forward).toBeDisabled()

    act(() => navigation.visit(1, 'PUSH'))
    rerender(<MacTitleBar />)
    expect(back).toBeEnabled()
    expect(forward).toBeDisabled()

    act(() => navigation.visit(0, 'BACK'))
    rerender(<MacTitleBar />)
    expect(back).toBeDisabled()
    expect(forward).toBeEnabled()

    fireEvent.click(forward)
    expect(navigation.history.forward).toHaveBeenCalledOnce()
  })

  it('clears the forward branch when navigation pushes a new entry', () => {
    const { rerender } = render(<MacTitleBar />)

    act(() => navigation.visit(1, 'PUSH'))
    rerender(<MacTitleBar />)
    act(() => navigation.visit(0, 'BACK'))
    rerender(<MacTitleBar />)
    expect(screen.getByRole('button', { name: 'Forward' })).toBeEnabled()

    act(() => navigation.visit(1, 'PUSH'))
    rerender(<MacTitleBar />)
    expect(screen.getByRole('button', { name: 'Forward' })).toBeDisabled()
  })

  it('routes the sidebar control to the active AppShell', () => {
    render(
      <>
        <MacTitleBar />
        <AppShell sidebar={<div>Sidebar</div>}>
          <div>Main</div>
        </AppShell>
      </>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(useUIStore.getState().sidebarCollapsed).toBe(true)
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeVisible()
  })
})
