/**
 * The preview is a card someone drags around. Everything below is about the
 * one way that goes wrong: a card left where it cannot be reached, because
 * its header — the only part of it that takes a pointer — is off screen.
 */

import { describe, expect, it } from 'vitest'

import {
  clampPreviewPlacement,
  PREVIEW_SIZES,
} from '@/components/BrowserViewer/browserPreviewPlacement'

const viewport = { width: 1280, height: 800 }

describe('browser preview placement', () => {
  it('leaves a card that already fits where it is', () => {
    expect(clampPreviewPlacement({ size: 'small', x: 400, y: 300 }, viewport))
      .toEqual({ size: 'small', x: 400, y: 300 })
  })

  it('pulls a card back when it is dragged past the right or bottom edge', () => {
    const placement = clampPreviewPlacement(
      { size: 'small', x: 5000, y: 5000 },
      viewport,
    )
    expect(placement.x).toBe(viewport.width - PREVIEW_SIZES.small.width)
    // The header has to stay on screen, so the bottom limit accounts for it.
    expect(placement.y).toBe(viewport.height - PREVIEW_SIZES.small.height - 32)
  })

  it('never lets the header leave the top or left edge', () => {
    expect(clampPreviewPlacement({ size: 'large', x: -900, y: -900 }, viewport))
      .toEqual({ size: 'large', x: 0, y: 0 })
  })

  it('keeps a card visible in a window too small for it', () => {
    const placement = clampPreviewPlacement(
      { size: 'large', x: 300, y: 300 },
      { width: 320, height: 200 },
    )
    expect(placement).toEqual({ size: 'large', x: 0, y: 0 })
  })
})
