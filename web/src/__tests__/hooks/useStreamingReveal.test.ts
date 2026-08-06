import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  nextStreamingRevealLength,
  streamingRevealBoundary,
  useStreamingReveal,
} from '@/hooks/useStreamingReveal'

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({ matches: false }),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('nextStreamingRevealLength', () => {
  it('shows small provider chunks on the next visual frame', () => {
    expect(nextStreamingRevealLength(20, 27)).toBe(27)
  })

  it('smooths a medium burst across a few frames', () => {
    expect(nextStreamingRevealLength(0, 100)).toBe(30)
    expect(nextStreamingRevealLength(30, 100)).toBe(51)
  })

  it('catches up large buffered responses without overshooting', () => {
    expect(nextStreamingRevealLength(0, 1_000)).toBe(96)
    expect(nextStreamingRevealLength(995, 1_000)).toBe(1_000)
    expect(nextStreamingRevealLength(20, 10)).toBe(10)
  })
})

describe('streamingRevealBoundary', () => {
  it('keeps combining marks with their base glyph', () => {
    expect(streamingRevealBoundary('a\u0301b', 1)).toBe(2)
  })

  it('does not split surrogate pairs', () => {
    expect(streamingRevealBoundary('a😀b', 2)).toBe(3)
  })
})

describe('useStreamingReveal', () => {
  it('reveals a burst over visual frames and flushes the final text immediately', () => {
    const frames = new Map<number, FrameRequestCallback>()
    let frameId = 0
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frameId += 1
      frames.set(frameId, callback)
      return frameId
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => {
      frames.delete(id)
    })

    const burst = 'x'.repeat(100)
    const { result, rerender } = renderHook(
      ({ content, isStreaming }) => useStreamingReveal(content, isStreaming),
      { initialProps: { content: burst, isStreaming: true } },
    )
    expect(result.current).toBe('')

    act(() => {
      const [id, callback] = frames.entries().next().value as [number, FrameRequestCallback]
      frames.delete(id)
      callback(40)
    })
    expect(result.current).toHaveLength(30)

    act(() => {
      const [id, callback] = frames.entries().next().value as [number, FrameRequestCallback]
      frames.delete(id)
      callback(80)
    })
    expect(result.current).toHaveLength(51)

    rerender({ content: burst, isStreaming: false })
    expect(result.current).toBe(burst)
  })

  it('holds an offscreen stream and catches up when rendering becomes active', () => {
    const frames = new Map<number, FrameRequestCallback>()
    let frameId = 0
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frameId += 1
      frames.set(frameId, callback)
      return frameId
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => {
      frames.delete(id)
    })

    const burst = 'x'.repeat(100)
    const { result, rerender } = renderHook(
      ({ active }) => useStreamingReveal(burst, true, active),
      { initialProps: { active: false } },
    )

    expect(result.current).toBe('')
    expect(frames).toHaveLength(0)

    rerender({ active: true })
    expect(frames).toHaveLength(1)

    act(() => {
      const [id, callback] = frames.entries().next().value as [number, FrameRequestCallback]
      frames.delete(id)
      callback(40)
    })
    expect(result.current).toHaveLength(30)
  })
})
