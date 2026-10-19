import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DirectBrowserShell } from '@/components/BrowserViewer/DirectBrowserShell'
import {
  getDirectBrowserSession,
  setDirectBrowserActiveTab,
} from '@/components/BrowserViewer/directBrowserSessionStore'

const browser = vi.hoisted(() => ({
  tabs: [] as Array<{ id: string; label: string; url: string }>,
  activeTabId: null as string | null,
  selectTab: vi.fn(),
  closeTab: vi.fn(),
}))

vi.mock('@/components/BrowserViewer/useDirectBrowserTabs', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('@/components/BrowserViewer/useDirectBrowserTabs')>()
  return {
    ...actual,
    useDirectBrowserTabs: () => ({
      supported: true,
      creating: false,
      loading: false,
      pageError: null,
      pageDialog: null,
      pagePermission: null,
      downloads: [],
      viewportOverride: null,
      tabs: browser.tabs,
      activeTabId: browser.activeTabId,
      activeTab:
        browser.tabs.find((tab) => tab.id === browser.activeTabId)
          ?? browser.tabs[0]
          ?? null,
      selectTab: browser.selectTab,
      closeTab: browser.closeTab,
      find: vi.fn(),
      navigate: vi.fn(),
      command: vi.fn(),
      closeAll: vi.fn(),
      setViewportPreset: vi.fn(),
      dismissPageDialog: vi.fn(),
      resolvePagePermission: vi.fn(),
      readSitePermissions: vi.fn(),
      clearDownloads: vi.fn(),
      clearBrowsingData: vi.fn(),
    }),
  }
})

function renderShell() {
  return render(
    <DirectBrowserShell
      sessionId="session-tabs"
      workspace={null}
      tabId="panel-tab-1"
      open
      visible
      onClose={() => {}}
    />,
  )
}

describe('DirectBrowserShell session tab strip', () => {
  beforeEach(() => {
    Object.defineProperty(window, '__TAURI_INTERNALS__', {
      configurable: true,
      value: {
        transformCallback: vi.fn(() => 0),
        invoke: vi.fn().mockResolvedValue(null),
      },
    })
    Object.defineProperty(window, '__TAURI_EVENT_PLUGIN_INTERNALS__', {
      configurable: true,
      value: {
        registerListener: vi.fn(),
        unregisterListener: vi.fn(),
      },
    })
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
      }),
    })
    browser.tabs = [
      { id: 'tab-1', label: 'tab-1', url: 'https://alpha.example/one' },
      { id: 'tab-2', label: 'tab-2', url: 'https://beta.example/two' },
      { id: 'tab-3', label: 'tab-3', url: 'https://gamma.example/three' },
    ]
    browser.activeTabId = 'tab-2'
    browser.selectTab.mockReset()
    browser.closeTab.mockReset()
  })

  it('renders every session tab and marks the shared active tab', () => {
    renderShell()

    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'alpha.example',
      'beta.example',
      'gamma.example',
    ])
    expect(tabs[0]).toHaveAttribute('aria-selected', 'false')
    expect(tabs[1]).toHaveAttribute('aria-selected', 'true')
    expect(tabs[2]).toHaveAttribute('aria-selected', 'false')
  })

  it('switches the shared active tab through the session store selection when a tab is clicked', () => {
    const session = getDirectBrowserSession('session-tabs')
    session.tabs = browser.tabs
    setDirectBrowserActiveTab('session-tabs', 'tab-1')
    browser.selectTab.mockImplementation((tabId: string) => {
      setDirectBrowserActiveTab('session-tabs', tabId)
    })

    renderShell()
    fireEvent.click(screen.getByRole('tab', { name: 'gamma.example' }))

    expect(browser.selectTab).toHaveBeenCalledWith('tab-3')
    expect(getDirectBrowserSession('session-tabs').activeTabId).toBe('tab-3')
  })

  it('closes a tab through the session store closeTab without selecting it', () => {
    renderShell()

    const tabs = screen.getAllByRole('tab')
    fireEvent.click(
      within(tabs[2].parentElement as HTMLElement).getByRole('button', {
        name: 'Close tab',
      }),
    )

    expect(browser.closeTab).toHaveBeenCalledWith('tab-3')
    expect(browser.selectTab).not.toHaveBeenCalled()
  })

  it('wires each tab close button to its own tab', () => {
    renderShell()

    const tabs = screen.getAllByRole('tab')
    tabs.forEach((tab, index) => {
      fireEvent.click(
        within(tab.parentElement as HTMLElement).getByRole('button', {
          name: 'Close tab',
        }),
      )
      expect(browser.closeTab).toHaveBeenNthCalledWith(
        index + 1,
        browser.tabs[index].id,
      )
    })
  })
})
