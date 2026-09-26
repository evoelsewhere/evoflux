/**
 * The preview is a card someone drags and resizes. Most of what follows is
 * about the one way that goes wrong: a card left where it cannot be reached,
 * because the header and the resize strip — the only parts of it that take a
 * pointer — are off screen.
 */

import { beforeEach, describe, expect, it } from 'vitest'

import {
  CHROME_HEIGHT,
  clampPreviewPlacement,
  loadPreviewPlacement,
  nextPreviewSize,
  PREVIEW_MIN_SIZE,
  PREVIEW_SIZES,
  PREVIEW_STACK_OFFSET,
  stackPreviewPlacement,
} from '@/components/BrowserViewer/browserPreviewPlacement'
import { STORAGE_KEYS } from '@/lib/storage-keys'

const viewport = { width: 1280, height: 800 }
const small = { x: 400, y: 300, ...PREVIEW_SIZES.small }

describe('browser preview placement', () => {
  it('leaves a card that already fits where it is', () => {
    expect(clampPreviewPlacement(small, viewport)).toEqual(small)
  })

  it('pulls a card back when it is dragged past the right or bottom edge', () => {
    const placement = clampPreviewPlacement({ ...small, x: 5000, y: 5000 }, viewport)
    expect(placement.x).toBe(viewport.width - PREVIEW_SIZES.small.width)
    // The chrome has to stay on screen, so the bottom limit accounts for it.
    expect(placement.y).toBe(viewport.height - PREVIEW_SIZES.small.height - CHROME_HEIGHT)
  })

  it('never lets the header leave the top or left edge', () => {
    const placement = clampPreviewPlacement({ ...small, x: -900, y: -900 }, viewport)
    expect(placement.x).toBe(0)
    expect(placement.y).toBe(0)
  })

  it('keeps a card visible in a window too small for it', () => {
    const placement = clampPreviewPlacement(
      { x: 300, y: 300, ...PREVIEW_SIZES.large },
      { width: 320, height: 200 },
    )
    // Width shrinks to the window; height stops at the minimum, because a
    // card too short to show anything is worse than one that overhangs.
    expect(placement).toEqual({
      x: 0,
      y: 0,
      width: 320,
      height: PREVIEW_MIN_SIZE.height,
    })
    expect(200 - CHROME_HEIGHT).toBeLessThan(PREVIEW_MIN_SIZE.height)
  })

  it('refuses a size too small to show a page in', () => {
    const placement = clampPreviewPlacement({ x: 0, y: 0, width: 10, height: 10 }, viewport)
    expect(placement.width).toBe(PREVIEW_MIN_SIZE.width)
    expect(placement.height).toBe(PREVIEW_MIN_SIZE.height)
  })

  it('toggles between the two quick sizes', () => {
    expect(nextPreviewSize(small)).toEqual(PREVIEW_SIZES.large)
    expect(nextPreviewSize({ x: 0, y: 0, ...PREVIEW_SIZES.large })).toEqual(PREVIEW_SIZES.small)
  })

  it('stacks older previews up and left while keeping the newest at the saved placement', () => {
    expect(stackPreviewPlacement(small, 0, viewport)).toEqual(small)
    expect(stackPreviewPlacement(small, 1, viewport)).toEqual({
      ...small,
      x: small.x - PREVIEW_STACK_OFFSET,
      y: small.y - PREVIEW_STACK_OFFSET,
    })
  })

  it('clamps a deep stack back into the viewport', () => {
    const stacked = stackPreviewPlacement(
      { ...small, x: 10, y: 10 },
      3,
      viewport,
    )
    expect(stacked.x).toBe(0)
    expect(stacked.y).toBe(0)
  })
})

describe('loading a stored placement', () => {
  beforeEach(() => localStorage.clear())

  it('reads back what was saved', () => {
    const stored = { x: 120, y: 80, width: 500, height: 320 }
    localStorage.setItem(STORAGE_KEYS.browser.previewPlacement, JSON.stringify(stored))
    expect(loadPreviewPlacement()).toEqual(stored)
  })

  it('migrates a card saved when the size was a preset name', () => {
    localStorage.setItem(
      STORAGE_KEYS.browser.previewPlacement,
      JSON.stringify({ size: 'large', x: 40, y: 60 }),
    )
    expect(loadPreviewPlacement()).toEqual({ x: 40, y: 60, ...PREVIEW_SIZES.large })
  })

  it('falls back to a corner when the stored value is nonsense', () => {
    localStorage.setItem(STORAGE_KEYS.browser.previewPlacement, '{"x":"left"}')
    const placement = loadPreviewPlacement()
    expect(placement.width).toBe(PREVIEW_SIZES.small.width)
    expect(placement.x).toBeGreaterThan(0)
  })

  it('opens a card with nothing saved at its own default size, left of a small card', () => {
    const placement = loadPreviewPlacement(
      STORAGE_KEYS.computerApp.previewPlacement,
      1,
      PREVIEW_SIZES.large,
    )
    expect(placement.width).toBe(PREVIEW_SIZES.large.width)
    expect(placement.height).toBe(PREVIEW_SIZES.large.height)
    const right = placement.x + placement.width
    expect(right).toBeLessThanOrEqual(window.innerWidth - PREVIEW_SIZES.small.width)
  })
})
