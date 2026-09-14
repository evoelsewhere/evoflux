/**
 * Where the corner preview sits, and the rule that keeps it reachable.
 *
 * Its own module because the card is a component and these are not: sharing
 * a file would cost the component its fast refresh, and the clamp is the one
 * piece of this worth testing on its own.
 */

import { STORAGE_KEYS } from '@/lib/storage-keys'

/** Small enough to sit beside the conversation, big enough to read a layout. */
export const PREVIEW_SIZES = {
  small: { width: 384, height: 240 },
  large: { width: 640, height: 400 },
} as const

type PreviewSize = keyof typeof PREVIEW_SIZES
export const HEADER_HEIGHT = 32
const EDGE_MARGIN = 16

export interface PreviewPlacement {
  size: PreviewSize
  /** Distance from the viewport's left and top edges, in CSS pixels. */
  x: number
  y: number
}

export function defaultPreviewPlacement(size: PreviewSize): PreviewPlacement {
  const { width, height } = PREVIEW_SIZES[size]
  return {
    size,
    x: Math.max(EDGE_MARGIN, window.innerWidth - width - EDGE_MARGIN),
    y: Math.max(EDGE_MARGIN, window.innerHeight - height - HEADER_HEIGHT - EDGE_MARGIN),
  }
}

/** Keep the card on screen, including after the window is resized smaller. */
export function clampPreviewPlacement(
  placement: PreviewPlacement,
  viewport: { width: number; height: number } = {
    width: window.innerWidth,
    height: window.innerHeight,
  },
): PreviewPlacement {
  const { width, height } = PREVIEW_SIZES[placement.size]
  const maxX = Math.max(0, viewport.width - width)
  const maxY = Math.max(0, viewport.height - height - HEADER_HEIGHT)
  return {
    size: placement.size,
    x: Math.min(Math.max(0, placement.x), maxX),
    y: Math.min(Math.max(0, placement.y), maxY),
  }
}

export function loadPreviewPlacement(): PreviewPlacement {
  try {
    const raw = JSON.parse(
      localStorage.getItem(STORAGE_KEYS.browser.previewPlacement) ?? 'null',
    ) as Partial<PreviewPlacement> | null
    if (!raw) return defaultPreviewPlacement('small')
    const size: PreviewSize = raw.size === 'large' ? 'large' : 'small'
    if (typeof raw.x !== 'number' || typeof raw.y !== 'number') return defaultPreviewPlacement(size)
    return clampPreviewPlacement({ size, x: raw.x, y: raw.y })
  } catch {
    return defaultPreviewPlacement('small')
  }
}

export function savePreviewPlacement(placement: PreviewPlacement): void {
  try {
    localStorage.setItem(STORAGE_KEYS.browser.previewPlacement, JSON.stringify(placement))
  } catch {
    // Storage can be unavailable in hardened WebViews.
  }
}
