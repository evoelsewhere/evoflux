/**
 * Where the app's picture sits inside the preview card, and where on that
 * picture the agent's pointer is.
 *
 * Its own module so the arithmetic can be tested without a canvas: the frame
 * is letterboxed (`object-fit: contain`), and a cursor that ignores the bars
 * lands beside the button it is pressing.
 */

export interface Size {
  width: number
  height: number
}

export interface Rect extends Size {
  left: number
  top: number
}

/** The rectangle a `contain`-fitted image of `content` occupies in `box`. */
export function containRect(box: Size, content: Size): Rect {
  if (box.width <= 0 || box.height <= 0 || content.width <= 0 || content.height <= 0) {
    return { left: 0, top: 0, width: Math.max(0, box.width), height: Math.max(0, box.height) }
  }
  const scale = Math.min(box.width / content.width, box.height / content.height)
  const width = content.width * scale
  const height = content.height * scale
  return {
    left: (box.width - width) / 2,
    top: (box.height - height) / 2,
    width,
    height,
  }
}

/**
 * A pointer given as a fraction of the app window (0..1 on each axis) → CSS
 * pixels inside the card's viewport. Out-of-range fractions are clamped so
 * the cursor never leaves the picture.
 */
export function pointerPosition(
  box: Size,
  content: Size,
  fraction: { x: number; y: number },
): { x: number; y: number } {
  const rect = containRect(box, content)
  const clamp = (value: number) => (Number.isFinite(value) ? Math.min(Math.max(value, 0), 1) : 0.5)
  return {
    x: rect.left + clamp(fraction.x) * rect.width,
    y: rect.top + clamp(fraction.y) * rect.height,
  }
}
