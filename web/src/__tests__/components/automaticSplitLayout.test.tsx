import { act, render, renderHook, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  AUTOMATIC_SPLIT_TRANSITION_MS,
  AutomaticSplitTransition,
} from '@/components/TeamChatView/AutomaticSplitTransition'
import {
  shouldAutoCollapseSidebar,
  shouldStartAutomaticSplit,
} from '@/components/TeamChatView/auto-layout'
import { useAutoCollapseSidebar } from '@/components/TeamChatView/useAutoCollapseSidebar'
import { MIN_PRIMARY_COLUMN_WIDTH } from '@/lib/workspace-panel-layout'
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

describe('automatic sidebar collapse', () => {
  it('collapses when the open Workbench leaves less than the primary-width contract', () => {
    expect(shouldAutoCollapseSidebar({
      workbenchOpen: true,
      isMobile: false,
      sidebarCollapsed: false,
      mainWidth: MIN_PRIMARY_COLUMN_WIDTH - 1,
    })).toBe(true)
  })

  it('keeps the sidebar open at the primary-width boundary', () => {
    expect(shouldAutoCollapseSidebar({
      workbenchOpen: true,
      isMobile: false,
      sidebarCollapsed: false,
      mainWidth: MIN_PRIMARY_COLUMN_WIDTH,
    })).toBe(false)
  })

  it('does not override mobile, closed-panel, or already-collapsed layouts', () => {
    const base = {
      workbenchOpen: true,
      isMobile: false,
      sidebarCollapsed: false,
      mainWidth: MIN_PRIMARY_COLUMN_WIDTH - 1,
    }

    expect(shouldAutoCollapseSidebar({ ...base, isMobile: true })).toBe(false)
    expect(shouldAutoCollapseSidebar({ ...base, workbenchOpen: false })).toBe(false)
    expect(shouldAutoCollapseSidebar({ ...base, sidebarCollapsed: true })).toBe(false)
  })
})

describe('automatic sidebar collapse observer', () => {
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
    vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses the untransformed content width and collapses live below the boundary', () => {
    const mainColumn = document.createElement('main') as unknown as HTMLDivElement
    vi.spyOn(mainColumn, 'getBoundingClientRect').mockReturnValue({
      width: MIN_PRIMARY_COLUMN_WIDTH - 3,
    } as DOMRect)
    const mainColumnRef = { current: mainColumn }
    const { unmount } = renderHook(() => useAutoCollapseSidebar({
      mainColumnRef,
      workbenchOpen: true,
      isMobile: false,
    }))
    const observer = observers[0]

    expect(observer?.observe).toHaveBeenCalledWith(mainColumn)
    act(() => observer?.emit(MIN_PRIMARY_COLUMN_WIDTH))
    expect(useUIStore.getState().sidebarCollapsed).toBe(false)

    act(() => observer?.emit(MIN_PRIMARY_COLUMN_WIDTH - 1))
    expect(useUIStore.getState().sidebarCollapsed).toBe(true)

    act(() => observer?.emit(MIN_PRIMARY_COLUMN_WIDTH + 100))
    expect(useUIStore.getState().sidebarCollapsed).toBe(true)

    const activeObserver = observer
    unmount()
    expect(activeObserver?.disconnect).toHaveBeenCalledOnce()
  })

  it('observes only while the desktop Workbench is open', () => {
    const mainColumnRef = {
      current: document.createElement('main') as unknown as HTMLDivElement,
    }
    const { rerender } = renderHook(
      ({ workbenchOpen, isMobile }) => useAutoCollapseSidebar({
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
