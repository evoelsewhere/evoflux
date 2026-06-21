import { describe, it, expect, afterEach, mock } from "bun:test"
import { render, cleanup } from "@testing-library/react"
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts"

afterEach(cleanup)

/** Build a keyboard event with the requested modifier flags. */
function buildEvent(
  key: string,
  opts: { ctrlKey?: boolean; metaKey?: boolean } = {},
): KeyboardEvent {
  return new KeyboardEvent("keydown", {
    key,
    ctrlKey: opts.ctrlKey ?? false,
    metaKey: opts.metaKey ?? false,
    bubbles: true,
    cancelable: true,
  })
}

function Harness({ shortcuts }: { shortcuts: Partial<Record<string, () => void>> }) {
  useKeyboardShortcuts(shortcuts)
  return null
}

describe("useKeyboardShortcuts", () => {
  it("fires on Ctrl+<key>", () => {
    const onDot = mock(() => {})
    render(<Harness shortcuts={{ ".": onDot }} />)

    const event = buildEvent(".", { ctrlKey: true })
    window.dispatchEvent(event)

    expect(onDot).toHaveBeenCalledTimes(1)
    expect(event.defaultPrevented).toBe(true)
  })

  it("ignores Cmd-only press (we never bind to ⌘)", () => {
    const onDot = mock(() => {})
    render(<Harness shortcuts={{ ".": onDot }} />)

    window.dispatchEvent(buildEvent(".", { metaKey: true }))

    expect(onDot).not.toHaveBeenCalled()
  })

  it("ignores Ctrl+Meta combo to avoid OS shortcut clashes", () => {
    const onDot = mock(() => {})
    render(<Harness shortcuts={{ ".": onDot }} />)

    window.dispatchEvent(buildEvent(".", { ctrlKey: true, metaKey: true }))

    expect(onDot).not.toHaveBeenCalled()
  })

  it("ignores unregistered keys", () => {
    const onDot = mock(() => {})
    render(<Harness shortcuts={{ ".": onDot }} />)

    const event = buildEvent("k", { ctrlKey: true })
    window.dispatchEvent(event)

    expect(onDot).not.toHaveBeenCalled()
    expect(event.defaultPrevented).toBe(false)
  })

  it("lowercases the key before lookup (Shift gives upper-case key)", () => {
    const onA = mock(() => {})
    render(<Harness shortcuts={{ a: onA }} />)

    window.dispatchEvent(buildEvent("A", { ctrlKey: true }))

    expect(onA).toHaveBeenCalledTimes(1)
  })

  it("removes the listener on unmount", () => {
    const onDot = mock(() => {})
    const view = render(<Harness shortcuts={{ ".": onDot }} />)

    view.unmount()
    window.dispatchEvent(buildEvent(".", { ctrlKey: true }))

    expect(onDot).not.toHaveBeenCalled()
  })

  it("uses the latest shortcut map without re-subscribing", () => {
    const first = mock(() => {})
    const second = mock(() => {})
    const view = render(<Harness shortcuts={{ ".": first }} />)

    window.dispatchEvent(buildEvent(".", { ctrlKey: true }))
    expect(first).toHaveBeenCalledTimes(1)

    view.rerender(<Harness shortcuts={{ ".": second }} />)

    window.dispatchEvent(buildEvent(".", { ctrlKey: true }))
    expect(first).toHaveBeenCalledTimes(1)
    expect(second).toHaveBeenCalledTimes(1)
  })

  it("Ctrl+I fires a 'focus-chat-input' CustomEvent", () => {
    const listener = mock(() => {})
    window.addEventListener("focus-chat-input", listener)

    render(
      <Harness
        shortcuts={{
          i: () => window.dispatchEvent(new CustomEvent("focus-chat-input")),
        }}
      />,
    )

    window.dispatchEvent(buildEvent("i", { ctrlKey: true }))

    expect(listener).toHaveBeenCalledTimes(1)
    window.removeEventListener("focus-chat-input", listener)
  })
})
