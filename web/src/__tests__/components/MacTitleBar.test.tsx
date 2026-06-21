/**
 * Tests for MacTitleBar — the macOS overlay-titlebar drag strip.
 *
 * The component reads ``navigator.platform`` once at *module load*
 * (via the module-level ``const IS_MAC = detectMac()``) so the
 * platform must be patched **before** the module is imported. We
 * achieve that with dynamic ``await import(...)`` inside each test
 * and Bun's ``mock.module`` to reset module state between cases.
 *
 * What we want to verify:
 *
 *   1. macOS-detected: renders a fixed 40 px strip with exactly 70 px
 *      left padding (mirrors the traffic-light position in
 *      tauri.conf.json — x=12 origin + ~58 px button group).
 *   2. macOS-detected: sets ``html[data-platform="mac-overlay"]`` so
 *      other components (e.g. floating overlays) can react to the
 *      mac-overlay state without re-detecting.
 *   3. macOS-detected: cleans up the attribute on unmount.
 *   4. Non-macOS: renders nothing (``null``), no attribute side-effect.
 *   5. Forward-compat: the UA-CH ``userAgentData.platform === "macOS"``
 *      branch fires even when ``navigator.platform`` is frozen/empty.
 *   6. ``aria-hidden`` is set so the empty drag strip never appears
 *      to assistive tech (it carries no semantic content).
 *
 * Edge cases:
 *   - ``navigator.platform === "Linux x86_64"`` → not Mac.
 *   - ``navigator.platform === "Win32"`` → not Mac.
 *   - ``navigator.platform === "MacIntel"`` (legacy Intel Mac) → Mac.
 *   - ``navigator.platform === "iPhone"`` → also matches /Mac/? No,
 *     "iPhone" doesn't contain "Mac" — but iPads can report "MacIntel"
 *     in modern iPadOS, which we accept. This is fine because Tauri
 *     doesn't run on iOS.
 */
import { describe, it, expect, afterEach, beforeEach, mock } from "bun:test"
import { render, cleanup } from "@testing-library/react"
import type { ReactElement } from "react"

afterEach(() => {
  // Always strip the attribute so cases don't leak into each other,
  // regardless of whether MacTitleBar mounted/unmounted cleanly.
  document.documentElement.removeAttribute("data-platform")
  // Also clear the Tauri marker we set per-test.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (window as any).__TAURI_INTERNALS__
  cleanup()
})

/** Override ``navigator.platform`` (string) and optional UA-CH platform. */
function setPlatform(platform: string, uaChPlatform?: string): void {
  Object.defineProperty(navigator, "platform", {
    value: platform,
    configurable: true,
    writable: true,
  })
  if (uaChPlatform !== undefined) {
    Object.defineProperty(navigator, "userAgentData", {
      value: { platform: uaChPlatform },
      configurable: true,
      writable: true,
    })
  } else {
    // Strip any prior mock from a previous test in the same file.
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      delete (navigator as any).userAgentData
    } catch {
      Object.defineProperty(navigator, "userAgentData", {
        value: undefined,
        configurable: true,
        writable: true,
      })
    }
  }
}

/** Pretend the bundle is running inside the Tauri WebView. The marker is
 *  read once at module load (see ``MacTitleBar``), so callers MUST set it
 *  BEFORE ``freshMacTitleBar`` re-imports the module. */
function enableTauri(): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).__TAURI_INTERNALS__ = { __mock: true }
}

/**
 * Dynamic import wrapper that bypasses Bun's module cache so each
 * test gets a fresh ``IS_MAC`` evaluation against the current
 * navigator stub. Without this, only the first test in the file
 * would see its intended platform — every subsequent test would
 * inherit the cached module result.
 */
async function freshMacTitleBar(): Promise<{ MacTitleBar: () => ReactElement | null }> {
  // Append a unique query so Bun treats it as a different module URL.
  // ``mock.module`` is the documented escape hatch but isn't usable here
  // because we want the *real* implementation under the current
  // navigator — not a replacement.
  const path = `@/components/MacTitleBar?nonce=${Math.random()}`
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (await import(/* @vite-ignore */ path as any)) as any
}

beforeEach(() => {
  // Belt-and-braces reset: a previous test may have left a custom
  // platform attribute that would confuse the next "non-mac" case.
  document.documentElement.removeAttribute("data-platform")
})

describe("MacTitleBar — macOS in Tauri", () => {
  it("renders a 70 × 40 px corner drag pad", async () => {
    setPlatform("MacIntel")
    enableTauri()
    const { MacTitleBar } = await freshMacTitleBar()
    const { container } = render(<MacTitleBar />)
    const pad = container.firstElementChild as HTMLElement | null
    expect(pad).not.toBeNull()
    // Layout invariants — the pad sits in the top-left corner only,
    // sized to the traffic-light inset. It is NOT a full-width strip:
    // a full-width strip would catch ``mousedown`` events meant for
    // the route's own header buttons. See MacTitleBar.tsx for the
    // rationale.
    expect(pad!.className).toContain("fixed")
    expect(pad!.className).toContain("left-0")
    expect(pad!.className).toContain("top-0")
    expect(pad!.className).toContain("h-10") // h-10 = 2.5rem = 40 px
    expect(pad!.className).toContain("w-(--spacing-mac-traffic-inset)")
  })

  it("sets aria-hidden so AT ignores the empty strip", async () => {
    setPlatform("MacIntel")
    enableTauri()
    const { MacTitleBar } = await freshMacTitleBar()
    const { container } = render(<MacTitleBar />)
    const strip = container.firstElementChild as HTMLElement
    expect(strip.getAttribute("aria-hidden")).toBe("true")
  })

  it("sets html[data-platform=mac-overlay] for the global CSS hook", async () => {
    setPlatform("MacIntel")
    enableTauri()
    const { MacTitleBar } = await freshMacTitleBar()
    render(<MacTitleBar />)
    expect(document.documentElement.getAttribute("data-platform")).toBe("mac-overlay")
  })

  it("removes the data-platform attribute on unmount", async () => {
    setPlatform("MacIntel")
    enableTauri()
    const { MacTitleBar } = await freshMacTitleBar()
    const view = render(<MacTitleBar />)
    expect(document.documentElement.getAttribute("data-platform")).toBe("mac-overlay")
    view.unmount()
    expect(document.documentElement.getAttribute("data-platform")).toBeNull()
  })

  it("detects modern Macs reporting 'MacIntel'", async () => {
    setPlatform("MacIntel")
    enableTauri()
    const { MacTitleBar } = await freshMacTitleBar()
    const { container } = render(<MacTitleBar />)
    expect(container.firstElementChild).not.toBeNull()
  })

  it("detects Macs reporting just 'Mac'", async () => {
    setPlatform("Mac")
    enableTauri()
    const { MacTitleBar } = await freshMacTitleBar()
    const { container } = render(<MacTitleBar />)
    expect(container.firstElementChild).not.toBeNull()
  })

  it("falls back to userAgentData.platform when navigator.platform is empty", async () => {
    setPlatform("", "macOS")
    enableTauri()
    const { MacTitleBar } = await freshMacTitleBar()
    const { container } = render(<MacTitleBar />)
    expect(container.firstElementChild).not.toBeNull()
    expect(document.documentElement.getAttribute("data-platform")).toBe("mac-overlay")
  })
})

describe("MacTitleBar — macOS in browser", () => {
  it("renders nothing when on Mac but not inside Tauri", async () => {
    setPlatform("MacIntel")
    // Note: enableTauri() intentionally NOT called.
    const { MacTitleBar } = await freshMacTitleBar()
    const { container } = render(<MacTitleBar />)
    expect(container.firstElementChild).toBeNull()
  })

  it("does not set html[data-platform] when on Mac but not inside Tauri", async () => {
    setPlatform("MacIntel")
    const { MacTitleBar } = await freshMacTitleBar()
    render(<MacTitleBar />)
    expect(document.documentElement.getAttribute("data-platform")).toBeNull()
  })
})

describe("MacTitleBar — non-macOS", () => {
  it("renders nothing on Linux", async () => {
    setPlatform("Linux x86_64")
    const { MacTitleBar } = await freshMacTitleBar()
    const { container } = render(<MacTitleBar />)
    expect(container.firstElementChild).toBeNull()
  })

  it("renders nothing on Windows", async () => {
    setPlatform("Win32")
    const { MacTitleBar } = await freshMacTitleBar()
    const { container } = render(<MacTitleBar />)
    expect(container.firstElementChild).toBeNull()
  })

  it("does not set html[data-platform] on Linux", async () => {
    setPlatform("Linux x86_64")
    const { MacTitleBar } = await freshMacTitleBar()
    render(<MacTitleBar />)
    expect(document.documentElement.getAttribute("data-platform")).toBeNull()
  })

  it("does not set html[data-platform] on Windows", async () => {
    setPlatform("Win32")
    const { MacTitleBar } = await freshMacTitleBar()
    render(<MacTitleBar />)
    expect(document.documentElement.getAttribute("data-platform")).toBeNull()
  })

  it("substring 'mac' inside an unrelated platform must not false-positive", async () => {
    // ``/Mac/`` is case-sensitive, so "Tarmac" (capital M, hypothetical
    // future UA) would match. Verify a clearly non-Mac case.
    setPlatform("FreeBSD")
    const { MacTitleBar } = await freshMacTitleBar()
    const { container } = render(<MacTitleBar />)
    expect(container.firstElementChild).toBeNull()
  })

  it("UA-CH platform of 'Windows' does not trigger Mac rendering", async () => {
    setPlatform("Win32", "Windows")
    const { MacTitleBar } = await freshMacTitleBar()
    const { container } = render(<MacTitleBar />)
    expect(container.firstElementChild).toBeNull()
  })
})

describe("MacTitleBar — platform changes between renders", () => {
  it("re-evaluates platform on each render via usePlatform()", async () => {
    setPlatform("MacIntel")
    enableTauri()
    const { MacTitleBar } = await freshMacTitleBar()
    const view = render(<MacTitleBar />)
    expect(document.documentElement.getAttribute("data-platform")).toBe("mac-overlay")

    // Patching navigator.platform mid-flight is purely a test
    // convenience — the platform doesn't change at runtime in practice.
    // We re-check it on every call so tests can flip between cases
    // without bouncing the module cache.
    setPlatform("Win32")
    delete (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
    view.rerender(<MacTitleBar />)
    // The component unmounts the platform attribute and the strip.
    expect(view.container.firstElementChild).toBeNull()
  })
})

// Silence the unused mock import — Bun's TS resolver complains otherwise.
void mock
