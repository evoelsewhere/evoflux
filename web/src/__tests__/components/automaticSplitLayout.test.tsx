import { act, render, renderHook, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  AUTOMATIC_SPLIT_TRANSITION_MS,
  AutomaticSplitTransition,
} from '@/components/TeamChatView/AutomaticSplitTransition'
import {
  shouldStartAutomaticSplit,
  shouldUseSidebarOverlay,
} from '@/components/TeamChatView/auto-layout'
import { useAdaptiveSidebarOverlay } from '@/components/TeamChatView/useAdaptiveSidebarOverlay'
import { MIN_PRIMARY_COLUMN_WIDTH, WORKSPACE_PANEL } from '@/lib/workspace-panel-layout'
import { useUIStore } from '@/stores/useUIStore'

describe('automatic Split layout', () => {
  it('starts when active agents cross from two to three', () => {
    expect(shouldStartAutomaticSplit({
      previousActiveCount: 2,
      activeCount: 3,
      viewMode: 'agent',
      isMobile: false,
    })).toBe(true)
  })

  it('does not repeatedly override a manual Agent selection', () => {
    expect(shouldStartAutomaticSplit({
      previousActiveCount: 3,
      activeCount: 3,
      viewMode: 'agent',
      isMobile: false,
    })).toBe(false)
  })

  it('does not override Monitor or mobile layouts', () => {
    expect(shouldStartAutomaticSplit({
      previousActiveCount: 2,
      activeCount: 3,
      viewMode: 'monitor',
      isMobile: false,
    })).toBe(false)
    expect(shouldStartAutomaticSplit({
      previousActiveCount: 2,
      activeCount: 3,
      viewMode: 'agent',
      isMobile: true,
    })).toBe(false)
  })

  it('does not start with only two active agents', () => {
    expect(shouldStartAutomaticSplit({
      previousActiveCount: 1,
      activeCount: 2,
      viewMode: 'agent',
      isMobile: false,
    })).toBe(false)
  })
})

describe('adaptive sidebar overlay', () => {
  it('uses a drawer when a docked sidebar would violate the primary-width contract', () => {
    expect(shouldUseSidebarOverlay({
      workbenchOpen: true,
      isMobile: false,
      sidebarMode: 'docked',
      sidebarCollapsed: false,
      mainWidth: MIN_PRIMARY_COLUMN_WIDTH - 1,
      sidebarWidth: 280,
    })).toBe(true)
  })

  it('keeps the sidebar docked at the primary-width boundary', () => {
    expect(shouldUseSidebarOverlay({
      workbenchOpen: true,
      isMobile: false,
      sidebarMode: 'docked',
      sidebarCollapsed: false,
      mainWidth: MIN_PRIMARY_COLUMN_WIDTH,
      sidebarWidth: 280,
    })).toBe(false)
  })

  it('estimates the expanded footprint when the docked sidebar is collapsed', () => {
    const sidebarWidth = 280
    expect(shouldUseSidebarOverlay({
      workbenchOpen: true,
      isMobile: false,
      sidebarMode: 'docked',
      sidebarCollapsed: true,
      mainWidth:
        MIN_PRIMARY_COLUMN_WIDTH
        + sidebarWidth
        - WORKSPACE_PANEL.collapsedRailWidth
        - 1,
      sidebarWidth,
    })).toBe(true)
  })

  it('stays stable after removing the sidebar from flex layout', () => {
    const sidebarWidth = 280
    expect(shouldUseSidebarOverlay({
      workbenchOpen: true,
      isMobile: false,
      sidebarMode: 'overlay',
      sidebarCollapsed: false,
      mainWidth:
        MIN_PRIMARY_COLUMN_WIDTH
        + sidebarWidth
        + WORKSPACE_PANEL.shellChromeWidth
        - 1,
      sidebarWidth,
    })).toBe(true)
  })

  it('does not use a desktop drawer on mobile or while the Workbench is closed', () => {
    const base = {
      workbenchOpen: true,
      isMobile: false,
      sidebarMode: 'docked' as const,
      sidebarCollapsed: false,
      mainWidth: MIN_PRIMARY_COLUMN_WIDTH - 1,
      sidebarWidth: 280,
    }

    expect(shouldUseSidebarOverlay({ ...base, isMobile: true })).toBe(false)
    expect(shouldUseSidebarOverlay({ ...base, workbenchOpen: false })).toBe(false)
  })
})

describe('adaptive sidebar overlay observer', () => {
  let observers: ResizeObserverMock[]

  class ResizeObserverMock {
    readonly callback: ResizeObserverCallback
    readonly observe = vi.fn()
    readonly unobserve = vi.fn()
    readonly disconnect = vi.fn()

    constructor(callback: ResizeObserverCallback) {
      this.callback = callback
      observers.push(this)
    }

    emit(width: number): void {
      this.callback(
        [{ contentRect: { width } } as ResizeObserverEntry],
        this as unknown as ResizeObserver,
      )
    }
  }

  beforeEach(() => {
    observers = []
    useUIStore.getState().setSidebarCollapsed(false)
    useUIStore.getState().setSidebarOverlay(false)
    useUIStore.getState().setSidebarWidth(280)
    vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('switches live without mutating the persisted collapse preference', () => {
    const mainColumn = document.createElement('main') as unknown as HTMLDivElement
    vi.spyOn(mainColumn, 'getBoundingClientRect').mockReturnValue({
      width: MIN_PRIMARY_COLUMN_WIDTH,
    } as DOMRect)
    const mainColumnRef = { current: mainColumn }
    const { result, unmount } = renderHook(() => useAdaptiveSidebarOverlay({
      mainColumnRef,
      workbenchOpen: true,
      isMobile: false,
    }))
    const observer = observers[0]

    expect(observer?.observe).toHaveBeenCalledWith(mainColumn)
    expect(result.current).toBe(false)

    act(() => observer?.emit(MIN_PRIMARY_COLUMN_WIDTH - 1))
    expect(result.current).toBe(true)
    expect(useUIStore.getState().sidebarCollapsed).toBe(false)
    expect(useUIStore.getState().sidebarOverlay).toBe(true)

    act(() => observer?.emit(
      MIN_PRIMARY_COLUMN_WIDTH
      + 280
      + WORKSPACE_PANEL.shellChromeWidth
      - 1,
    ))
    expect(result.current).toBe(true)

    act(() => observer?.emit(
      MIN_PRIMARY_COLUMN_WIDTH
      + 280
      + WORKSPACE_PANEL.shellChromeWidth,
    ))
    expect(result.current).toBe(false)
    expect(useUIStore.getState().sidebarCollapsed).toBe(false)
    expect(useUIStore.getState().sidebarOverlay).toBe(false)

    const activeObserver = observer
    unmount()
    expect(activeObserver?.disconnect).toHaveBeenCalledOnce()
    expect(useUIStore.getState().sidebarOverlay).toBe(false)
  })

  it('observes only while the desktop Workbench is open', () => {
    const mainColumnRef = {
      current: document.createElement('main') as unknown as HTMLDivElement,
    }
    const { rerender } = renderHook(
      ({ workbenchOpen, isMobile }) => useAdaptiveSidebarOverlay({
        mainColumnRef,
        workbenchOpen,
        isMobile,
      }),
      { initialProps: { workbenchOpen: false, isMobile: false } },
    )

    expect(observers).toHaveLength(0)
    rerender({ workbenchOpen: true, isMobile: true })
    expect(observers).toHaveLength(0)

    rerender({ workbenchOpen: true, isMobile: false })
    const activeObserver = observers[0]
    expect(activeObserver?.observe).toHaveBeenCalledWith(mainColumnRef.current)

    rerender({ workbenchOpen: false, isMobile: false })
    expect(activeObserver?.disconnect).toHaveBeenCalledOnce()
  })
})

describe('AutomaticSplitTransition', () => {
  it('announces the change and completes after the border orbit', () => {
    vi.useFakeTimers()
    const onComplete = vi.fn()
    const { container } = render(
      <AutomaticSplitTransition activeAgentCount={3} onComplete={onComplete} />,
    )

    expect(screen.getByRole('status')).toHaveAccessibleName(
      'Organizing 3 active agents into Split layout',
    )
    const rings = container.querySelectorAll('.oa-layout-switch-ring')
    expect(rings).toHaveLength(2)
    act(() => {
      vi.advanceTimersByTime(AUTOMATIC_SPLIT_TRANSITION_MS)
    })
    expect(onComplete).toHaveBeenCalledOnce()
    vi.useRealTimers()
  })
})
