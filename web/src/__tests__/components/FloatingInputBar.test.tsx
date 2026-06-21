import { describe, it, expect, afterEach, beforeEach } from 'bun:test'
import { createRef, useRef } from 'react'
import { render, screen, cleanup, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FloatingInputBar } from '@/components/FloatingInputBar'
import { useTeamStore } from '@/stores/useTeamStore'
import type { InputBarHandle } from '@/components/InputBar'

afterEach(cleanup)
beforeEach(() => {
  useTeamStore.setState({ _pendingMessages: [] })
})

// Test harness — provides a bounds container.
function Harness(props: {
  onSubmit?: (message: string, files?: File[]) => void
  onStop?: () => void
  placeholder?: string
  exposeFocus?: boolean
  isStreaming?: boolean
}) {
  const boundsRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<InputBarHandle>(null)
  return (
    <div
      ref={boundsRef}
      data-testid="bounds"
      style={{ position: 'relative', width: 1200, height: 800 }}
    >
      {props.exposeFocus && (
        <button type="button" onClick={() => inputRef.current?.focus()}>
          Focus input
        </button>
      )}
      <FloatingInputBar
        ref={inputRef}
        boundsRef={boundsRef}
        onSubmit={props.onSubmit ?? (() => {})}
        onStop={props.onStop}
        isStreaming={props.isStreaming}
        placeholder={props.placeholder ?? 'Message…'}
      />
    </div>
  )
}

describe('FloatingInputBar', () => {
  it('renders the textarea as always visible (no minimize)', () => {
    render(<Harness />)
    const textarea = screen.getByLabelText('Message input')
    expect(textarea).toBeTruthy()
    // The bar is always expanded — textarea is never disabled
    expect(textarea.getAttribute('disabled')).toBeNull()
  })

  it('forwards the placeholder prop to the inner InputBar', () => {
    render(<Harness placeholder="Ask the team…" />)
    const textarea = screen.getByRole('textbox', { name: 'Message input' })
    expect(textarea.getAttribute('placeholder')).toBe('Ask the team…')
  })

  it('does not render queued messages inside the composer', () => {
    useTeamStore.setState({
      sessionId: 'session-a',
      _pendingMessages: [
        { id: 'pm-1', sessionId: 'session-a', content: 'first queued message' },
        { id: 'pm-2', sessionId: 'session-a', content: 'second queued message' },
      ],
    })

    render(<Harness />)

    expect(screen.queryByText('first queued message')).toBeNull()
  })

  it('focuses the textarea through its imperative focus handle', async () => {
    const user = userEvent.setup()
    render(<Harness exposeFocus />)

    const textarea = screen.getByLabelText('Message input')
    await user.click(screen.getByRole('button', { name: 'Focus input' }))

    expect(document.activeElement).toBe(textarea)
  })

  it('inserts text through its imperative insertText handle', () => {
    const ref = createRef<InputBarHandle>()
    function InsertHarness() {
      const boundsRef = useRef<HTMLDivElement>(null)
      return (
        <div ref={boundsRef} style={{ position: 'relative', width: 1200, height: 800 }}>
          <FloatingInputBar ref={ref} boundsRef={boundsRef} onSubmit={() => {}} />
        </div>
      )
    }

    render(<InsertHarness />)

    const textarea = screen.getByLabelText('Message input') as HTMLTextAreaElement
    act(() => {
      ref.current?.insertText('hello')
    })
    expect(textarea.value).toBe('hello')
  })

  it('submits a message on send button click', async () => {
    let submitted = ''
    const user = userEvent.setup()
    render(<Harness onSubmit={(msg) => { submitted = msg }} />)

    const textarea = screen.getByRole('textbox', { name: 'Message input' })
    await user.type(textarea, 'hello')
    await user.click(screen.getByRole('button', { name: 'Send message' }))

    expect(submitted).toBe('hello')
  })

  it('shows stop button while streaming', () => {
    render(<Harness isStreaming onStop={() => {}} />)
    expect(screen.getByRole('button', { name: 'Stop generation' })).toBeTruthy()
  })
})
