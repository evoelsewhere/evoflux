import { render } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { BrowserPipHost } from '@/components/BrowserViewer/BrowserPipHost'

const hook = vi.hoisted(() => ({
  calls: [] as Array<{ sessionId: string; visible: boolean }>,
}))

vi.mock('@/components/BrowserViewer/useDirectBrowserTabs', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('@/components/BrowserViewer/useDirectBrowserTabs')>()
  return {
    ...actual,
    useDirectBrowserTabs: (options: { sessionId: string; visible: boolean }) => {
      hook.calls.push({ sessionId: options.sessionId, visible: options.visible })
      return {
        supported: true,
        creating: false,
        loading: false,
        pageError: null,
        pageDialog: null,
        pagePermission: null,
        downloads: [],
        viewportOverride: null,
        tabs: [{ id: 't1', label: 'db-1', url: 'https://example.test/' }],
        activeTabId: 't1',
        activeTab: { id: 't1', label: 'db-1', url: 'https://example.test/' },
        resolvePagePermission: vi.fn(),
        dismissPageDialog: vi.fn(),
        closeAll: vi.fn(),
      }
    },
  }
})

beforeEach(() => {
  hook.calls.length = 0
  document.body.innerHTML = ''
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
})

function card(sessionId: string): HTMLElement {
  const element = document.querySelector<HTMLElement>(
    `[data-browser-pip-session="${sessionId}"]`,
  )
  if (!element) throw new Error(`no preview card for ${sessionId}`)
  return element
}

describe('BrowserPipHost belongs to its own chat', () => {
  it('shows the card and the native view for the chat on screen', () => {
    render(<BrowserPipHost sessionId="chat-a" stackDepth={0} stackOrder={0} active />)

    expect(card('chat-a').style.display).not.toBe('none')
    expect(card('chat-a').getAttribute('aria-hidden')).toBeNull()
    expect(hook.calls.at(-1)).toEqual({ sessionId: 'chat-a', visible: true })
  })

  it('hides the card and the native view for another chat, but keeps it mounted', () => {
    render(
      <>
        <BrowserPipHost sessionId="chat-a" stackDepth={0} stackOrder={0} active />
        <BrowserPipHost sessionId="chat-b" stackDepth={0} stackOrder={1} active={false} />
      </>,
    )

    expect(card('chat-b').style.display).toBe('none')
    expect(card('chat-b').getAttribute('aria-hidden')).toBe('true')
    expect(card('chat-a').style.display).not.toBe('none')
    expect(hook.calls.filter((call) => call.sessionId === 'chat-b').at(-1)?.visible).toBe(false)
    expect(hook.calls.filter((call) => call.sessionId === 'chat-a').at(-1)?.visible).toBe(true)
  })

  it('shows the card again when its chat comes back', () => {
    const { rerender } = render(
      <BrowserPipHost sessionId="chat-b" stackDepth={0} stackOrder={0} active={false} />,
    )
    expect(card('chat-b').style.display).toBe('none')

    rerender(<BrowserPipHost sessionId="chat-b" stackDepth={0} stackOrder={0} active />)

    expect(card('chat-b').style.display).not.toBe('none')
    expect(hook.calls.at(-1)).toEqual({ sessionId: 'chat-b', visible: true })
  })
})
