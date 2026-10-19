import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const storeMock = vi.hoisted(() => ({
  sendMessage: vi.fn(async (_prompt: string) => true),
}))

vi.mock('@/stores/useTeamStore', () => ({
  useTeamStore: (
    selector: (state: { sendMessage: (prompt: string) => Promise<boolean> }) => unknown,
  ) => selector({ sendMessage: storeMock.sendMessage }),
}))

import { UiCustom } from '@/components/ui/UiCustom'

function getFrame(): HTMLIFrameElement {
  const frame = document.querySelector('iframe')
  if (!frame) throw new Error('expected a widget iframe')
  return frame
}

function frameHtml(frame: HTMLIFrameElement): string {
  // jsdom materializes srcdoc lazily: on first paint only the attribute is
  // set; after morphdom updates the live document, contentDocument wins.
  const doc = frame.contentDocument
  const live = doc?.body?.innerHTML ?? ''
  if (live) return doc?.documentElement?.outerHTML ?? ''
  return frame.getAttribute('srcdoc') ?? ''
}

describe('UiCustom', () => {
  beforeEach(() => {
    document.documentElement.classList.remove('dark')
  })

  afterEach(() => {
    document.documentElement.classList.remove('dark')
  })

  it('renders the block html through a WidgetRenderer iframe srcdoc', () => {
    render(<UiCustom block={{ type: 'custom', html: '<div id="agent-widget">hi</div>' }} />)
    const frame = getFrame()
    const html = frameHtml(frame)
    expect(html).toContain('agent-widget')
    expect(html).toContain('hi')
  })

  it('wraps the html in the WidgetRenderer CSP document', () => {
    render(<UiCustom block={{ type: 'custom', html: '<p>body</p>' }} />)
    const html = frameHtml(getFrame())
    expect(html).toContain('Content-Security-Policy')
    expect(html).toContain('window.sendPrompt')
  })

  it('forwards a widget sendPrompt action to the active chat', () => {
    render(<UiCustom block={{ type: 'custom', html: '<button>Continue</button>' }} />)
    const frame = getFrame()
    fireEvent(
      window,
      new MessageEvent('message', {
        data: { type: 'widget_send_prompt', prompt: 'continue the plan' },
        source: frame.contentWindow,
      }),
    )

    expect(storeMock.sendMessage).toHaveBeenCalledWith('continue the plan')
  })

  it('prepends the design-token style built from app tokens', () => {
    document.documentElement.classList.remove('dark')
    render(<UiCustom block={{ type: 'custom', html: '<span>x</span>' }} />)
    const html = frameHtml(getFrame())
    expect(html).toContain('id="evoflux-widget-tokens"')
    // Widget vocabulary vars resolve (app token or guideline fallback).
    expect(html).toContain('--color-text-primary')
    expect(html).toContain('--color-accent')
    expect(html).toContain('--color-success')
    expect(html).toContain('color-scheme:')
  })

  it('seeds the frame with the block height or the 320px default', () => {
    const { container, unmount } = render(
      <UiCustom block={{ type: 'custom', html: '<b>a</b>', height: 640 }} />,
    )
    expect(container.firstElementChild).toHaveStyle({ height: '640px' })
    unmount()

    const { container: defContainer } = render(
      <UiCustom block={{ type: 'custom', html: '<b>b</b>' }} />,
    )
    expect(defContainer.firstElementChild).toHaveStyle({ height: '320px' })
  })

  it('re-applies tokens on theme flip via the documentElement observer', async () => {
    render(<UiCustom block={{ type: 'custom', html: '<em>t</em>' }} />)
    const frame = getFrame()
    const before = frameHtml(frame)
    expect(before).toContain('color-scheme: light')

    act(() => {
      document.documentElement.classList.add('dark')
    })

    // MutationObserver fires on the class attribute; tokens recompute and the
    // html prop re-renders (ChartBlock.tsx:76 pattern).
    await act(async () => {
      await Promise.resolve()
    })
    const after = frameHtml(frame)
    expect(after).toContain('color-scheme: dark')
  })

  it('renders no chat chrome — custom blocks cannot send prompts', () => {
    render(<UiCustom block={{ type: 'custom', html: '<div>c</div>' }} />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
