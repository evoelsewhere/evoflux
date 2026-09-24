/**
 * Document annotations — parts of a document the user selected in the viewer
 * with an instruction each, sent to the agent as one message.
 *
 * The wire format is plain message text, so a message queues, replays and
 * survives undo/redo like any other: the user's own text, then a
 * `$office-annotation-edit` mention (activates the Skill) and a JSON block the
 * Skill documents. The chat hides the block and shows an "Annotations" chip.
 */

export interface AnnotationArea {
  /** Percent of the slide/page, origin top-left. */
  x: number
  y: number
  w: number
  h: number
}

export interface DocumentAnnotation {
  /** Client id, for removing one from a batch; not sent. */
  id: string
  /** Workspace-relative file path. */
  file: string
  /** 1-based slide (or, in a workbook, sheet) number. */
  slide: number
  /** Workbooks: the sheet's name and the selected cells, e.g. "B3:D8". */
  sheet?: string
  range?: string
  /** Shapes the user clicked; empty for a dragged box. */
  shapes: Array<{ id: number; name: string }>
  area: AnnotationArea
  /** Visible text inside the selection, for orientation. */
  text: string
  instruction: string
  /** Short human label, e.g. "Slide 7 · Chart 3". */
  label: string
}

export const ANNOTATION_SKILL = 'office-annotation-edit'
const OPEN_TAG = '<evoflux-annotations>'
const CLOSE_TAG = '</evoflux-annotations>'
const BLOCK_RE = /\n*\$office-annotation-edit\s*\n<evoflux-annotations>\n([\s\S]*?)\n<\/evoflux-annotations>\s*$/

const round = (value: number) => Math.round(value * 10) / 10

/** Append the annotation block to the user's message text. */
export function composeAnnotatedMessage(text: string, annotations: DocumentAnnotation[]): string {
  if (annotations.length === 0) return text
  const payload = annotations.map((annotation, index) => ({
    n: index + 1,
    file: annotation.file,
    slide: annotation.slide,
    ...(annotation.range ? { sheet: annotation.sheet ?? '', range: annotation.range } : {}),
    shapes: annotation.shapes,
    area: {
      x: round(annotation.area.x),
      y: round(annotation.area.y),
      w: round(annotation.area.w),
      h: round(annotation.area.h),
    },
    text: annotation.text.slice(0, 300),
    instruction: annotation.instruction,
  }))
  const block = `$${ANNOTATION_SKILL}\n${OPEN_TAG}\n${JSON.stringify(payload)}\n${CLOSE_TAG}`
  return text.trim() ? `${text.trim()}\n\n${block}` : block
}

export interface ParsedAnnotation {
  n: number
  file: string
  slide: number
  sheet?: string
  range?: string
  shapes: Array<{ id: number; name: string }>
  text: string
  instruction: string
}

/** Split a sent message into its visible text and its annotations. */
export function parseAnnotatedMessage(raw: string): { text: string; annotations: ParsedAnnotation[] } | null {
  if (!raw.includes(OPEN_TAG)) return null
  // multipart/form-data turns every line break into CRLF on the way in.
  const content = raw.replace(/\r\n?/g, '\n')
  const match = BLOCK_RE.exec(content)
  if (!match) return null
  try {
    const raw = JSON.parse(match[1]) as unknown
    if (!Array.isArray(raw)) return null
    const annotations = raw.flatMap((item: Partial<ParsedAnnotation>, index): ParsedAnnotation[] => (
      item && typeof item === 'object'
        ? [{
            n: typeof item.n === 'number' ? item.n : index + 1,
            file: String(item.file ?? ''),
            slide: Number(item.slide ?? 0),
            ...(typeof item.range === 'string' && item.range
              ? { sheet: String(item.sheet ?? ''), range: item.range }
              : {}),
            shapes: Array.isArray(item.shapes) ? item.shapes : [],
            text: String(item.text ?? ''),
            instruction: String(item.instruction ?? ''),
          }]
        : []
    ))
    return { text: content.slice(0, match.index).trim(), annotations }
  } catch {
    return null
  }
}

export function describeAnnotation(
  annotation: Pick<ParsedAnnotation, 'slide' | 'shapes' | 'sheet' | 'range'> & { text?: string },
): string {
  if (annotation.range) return `${annotation.sheet || `Sheet ${annotation.slide}`} · ${annotation.range}`
  const quoted = annotation.text?.trim()
  const target = annotation.shapes.length > 0
    ? annotation.shapes.map((shape) => shape.name).join(', ')
    : quoted
      ? `“${quoted.length > 40 ? `${quoted.slice(0, 40)}…` : quoted}”`
      : 'Selected area'
  return `Slide ${annotation.slide} · ${target}`
}
