/**
 * Thumbnails built from a backend document preview: every page, slide or
 * sheet of the preview HTML is a `[data-preview-item]`, and a thumbnail is
 * one of them re-hosted in its own inert document (no scripts, only inline
 * styles and embedded images), shown in a sandboxed iframe.
 */

const THUMBNAIL_CSP = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; font-src data:">`

export function previewItems(document: Document): HTMLElement[] {
  const items = Array.from(document.querySelectorAll<HTMLElement>('[data-preview-item]'))
  return items.length > 0 ? items : document.body ? [document.body] : []
}

function documentStyles(document: Document): string {
  return Array.from(document.querySelectorAll('style'))
    .filter((style) => style.dataset.evofluxViewer !== 'true')
    .map((style) => style.outerHTML)
    .join('')
}

function standalone(element: HTMLElement): HTMLElement {
  const clone = element.cloneNode(true) as HTMLElement
  clone.removeAttribute('hidden')
  clone.querySelectorAll('[data-preview-notes]').forEach((notes) => notes.remove())
  return clone
}

/** A slide filling its frame: slides size themselves from their container. */
export function slideThumbnailDocument(document: Document, element: HTMLElement): string {
  return `<!doctype html><html><head>
    ${THUMBNAIL_CSP}
    ${documentStyles(document)}
    <style>
      html,body{width:100%;height:100%;margin:0!important;padding:0!important;overflow:hidden!important;background:#fff!important}
      body{display:block!important;min-width:0!important;min-height:0!important}
      [data-preview-item]{position:absolute!important;inset:0!important;display:block!important;width:100%!important;max-width:none!important;height:100%!important;margin:0!important;padding:0!important}
      [data-preview-item]>.slide{width:100%!important;height:100%!important;box-shadow:none!important}
      .slide-number,[data-preview-notes]:not([data-preview-item]){display:none!important}
    </style>
  </head><body>${standalone(element).outerHTML}</body></html>`
}

/** A page or sheet at its natural width; the frame is scaled to fit. */
export function pageThumbnailDocument(document: Document, element: HTMLElement): string {
  return `<!doctype html><html><head>
    ${THUMBNAIL_CSP}
    ${documentStyles(document)}
    <style>
      html,body{margin:0!important;padding:0!important;overflow:hidden!important;background:#fff!important}
      body{display:block!important;min-width:0!important}
      [data-preview-item]{margin:0 auto!important;box-shadow:none!important}
      [data-preview-notes]:not([data-preview-item]){display:none!important}
    </style>
  </head><body>${standalone(element).outerHTML}</body></html>`
}

/** The first page or slide of a preview document, as a thumbnail document. */
export function firstItemThumbnail(html: string, kind: string): string | null {
  const document = new DOMParser().parseFromString(html, 'text/html')
  const first = previewItems(document)[0]
  if (!first || first === document.body) return null
  return kind === 'pptx' ? slideThumbnailDocument(document, first) : pageThumbnailDocument(document, first)
}
