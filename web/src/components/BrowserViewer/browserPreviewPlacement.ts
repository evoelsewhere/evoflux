/**
 * Where the corner preview sits, how big it is, and the rule that keeps it
 * reachable.
 *
 * Its own module because the card is a component and these are not: sharing
 * a file would cost the component its fast refresh, and the clamp is the one
 * piece of this worth testing on its own.
 */

import { STORAGE_KEYS } from '@/lib/storage-keys'

/** Quick sizes for the toggle: beside the conversation, or big enough to read. */
export const PREVIEW_SIZES = {
  small: { width: 384, height: 240 },
  large: { width: 640, height: 400 },
} as const

export const HEADER_HEIGHT = 32
/** The resize strip under the page — the only edge of the card a pointer can
 *  take, since the page itself is a native view this document cannot see. */
export const FOOTER_HEIGHT = 12
export const CHROME_HEIGHT = HEADER_HEIGHT + FOOTER_HEIGHT

/** Below this the page is a smudge; above it the "preview" is a window. */
export const PREVIEW_MIN_SIZE = { width: 260, height: 160 }
export const PREVIEW_MAX_SIZE = { width: 1600, height: 1000 }

const EDGE_MARGIN = 16
/** Offset older previews up and left so their headers remain reachable. */
export const PREVIEW_STACK_OFFSET = 28

export interface PreviewPlacement {
  /** Distance from the viewport's left and top edges, in CSS pixels. */
  x: number
  y: number
  /** The page area, excluding the card's own chrome. */
  width: number
  height: number
}

export function defaultPreviewPlacement(): PreviewPlacement {
  const { width, height } = PREVIEW_SIZES.small
  return clampPreviewPlacement({
    width,
    height,
    x: window.innerWidth - width - EDGE_MARGIN,
    y: window.innerHeight - height - CHROME_HEIGHT - EDGE_MARGIN,
  })
}

/** The preset a size toggle should move to from here. */
export function nextPreviewSize(
  placement: PreviewPlacement,
): { width: number; height: number } {
  return placement.width < PREVIEW_SIZES.large.width
    ? PREVIEW_SIZES.large
    : PREVIEW_SIZES.small
}

/**
 * Offset an older preview behind newer previews while keeping its header on
 * screen. The newest preview uses depth 0 and stays at the saved placement.
 */
export function stackPreviewPlacement(
  placement: PreviewPlacement,
  depth: number,
  viewport?: { width: number; height: number },
): PreviewPlacement {
  if (depth <= 0) return placement
  return clampPreviewPlacement(
    {
      ...placement,
      x: placement.x - depth * PREVIEW_STACK_OFFSET,
      y: placement.y - depth * PREVIEW_STACK_OFFSET,
    },
    viewport,
  )
}

/**
 * Keep the card on screen and a usable size, including after the window is
 * resized smaller. A card whose header is off screen cannot be dragged back:
 * the header is the only part of it a pointer can reach.
 */
export function clampPreviewPlacement(
  placement: PreviewPlacement,
  viewport: { width: number; height: number } = {
    width: window.innerWidth,
    height: window.innerHeight,
  },
): PreviewPlacement {
  const width = clamp(
    placement.width,
    PREVIEW_MIN_SIZE.width,
    Math.max(PREVIEW_MIN_SIZE.width, Math.min(PREVIEW_MAX_SIZE.width, viewport.width)),
  )
  const height = clamp(
    placement.height,
    PREVIEW_MIN_SIZE.height,
    Math.max(
      PREVIEW_MIN_SIZE.height,
      Math.min(PREVIEW_MAX_SIZE.height, viewport.height - CHROME_HEIGHT),
    ),
  )
  return {
    width,
    height,
    x: clamp(placement.x, 0, Math.max(0, viewport.width - width)),
    y: clamp(placement.y, 0, Math.max(0, viewport.height - height - CHROME_HEIGHT)),
  }
}

export function loadPreviewPlacement(): PreviewPlacement {
  try {
    const raw = JSON.parse(
      localStorage.getItem(STORAGE_KEYS.browser.previewPlacement) ?? 'null',
    ) as Partial<PreviewPlacement> & { size?: string } | null
    if (!raw || typeof raw.x !== 'number' || typeof raw.y !== 'number') {
      return defaultPreviewPlacement()
    }
    // Cards saved before the preview could be resized freely stored the name
    // of a preset instead of a size.
    const preset = raw.size === 'large' ? PREVIEW_SIZES.large : PREVIEW_SIZES.small
    return clampPreviewPlacement({
      x: raw.x,
      y: raw.y,
      width: typeof raw.width === 'number' ? raw.width : preset.width,
      height: typeof raw.height === 'number' ? raw.height : preset.height,
    })
  } catch {
    return defaultPreviewPlacement()
  }
}

export function savePreviewPlacement(placement: PreviewPlacement): void {
  try {
    localStorage.setItem(STORAGE_KEYS.browser.previewPlacement, JSON.stringify(placement))
  } catch {
    // Storage can be unavailable in hardened WebViews.
  }
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min
  return Math.round(Math.min(Math.max(value, min), max))
}
