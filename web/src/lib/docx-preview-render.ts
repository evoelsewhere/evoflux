/**
 * Client-side DOCX rendering for the document viewer.
 *
 * The backend's python-docx renderer only understands a small subset of
 * WordprocessingML (first section, style-name lists, simple tables). This
 * module renders the original bytes with `docx-preview` instead, then
 * serializes the result into the same inert, self-contained HTML contract the
 * backend emits: a strict CSP, no scripts, no network, and one
 * `[data-preview-item]` per page so search, zoom and the page navigator keep
 * working unchanged.
 */

/** Mirrors `app/services/document_preview/contract.py::DOCUMENT_PREVIEW_CSP`. */
export const DOCUMENT_PREVIEW_CSP = [
  "default-src 'none'",
  "base-uri 'none'",
  "connect-src 'none'",
  'font-src data:',
  "form-action 'none'",
  "frame-src 'none'",
  'img-src data: blob:',
  'media-src data: blob:',
  "object-src 'none'",
  "script-src 'none'",
  "style-src 'unsafe-inline'",
].join('; ')

/** Mirrors the backend `MAX_DOCUMENT_PREVIEW_BYTES` source-size ceiling. */
export const MAX_DOCX_SOURCE_BYTES = 100 * 1024 * 1024

const BLOCKED_ELEMENTS = 'script,iframe,frame,object,embed,link,meta,base,form,input,button,textarea,select'
const SAFE_URL = /^(data:|blob:|#)/i

const VIEWER_CSS = `
html,body{margin:0;padding:0;background:#e8eaed}
.docx-wrapper{background:#e8eaed!important;padding:32px 16px!important;gap:24px;display:flex;flex-direction:column;align-items:center}
.docx-wrapper>section.docx{margin:0!important;box-shadow:0 2px 12px #0002!important}
a[data-href]{color:#1a56c4;text-decoration:underline;cursor:default}
`

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * Strip anything active from docx-preview output. The iframe sandbox and CSP
 * already block scripts; this also prevents in-frame navigation through
 * document hyperlinks and remote resource references.
 */
export function neutralizeRenderedDocx(root: Element): void {
  root.querySelectorAll(BLOCKED_ELEMENTS).forEach((element) => element.remove())
  const elements = [root, ...Array.from(root.querySelectorAll('*'))]
  for (const element of elements) {
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase()
      if (name.startsWith('on')) {
        element.removeAttribute(attribute.name)
      } else if (name === 'href' || name === 'xlink:href') {
        const value = attribute.value.trim()
        element.removeAttribute(attribute.name)
        if (value && !value.startsWith('#')) element.setAttribute('data-href', value)
      } else if ((name === 'src' || name === 'srcset' || name === 'poster') && !SAFE_URL.test(attribute.value.trim())) {
        element.removeAttribute(attribute.name)
      }
    }
  }
}

const SVG_CONTAINERS = new Set(['svg', 'g'])
const VML_THEME_SUFFIX = /\s*\[\d+\]\s*$/

/**
 * Repair docx-preview's legacy VML fallback output: theme-indexed colours such
 * as `#156082 [3204]` are invalid SVG paints, and text boxes are emitted as a
 * `<foreignObject>` nested inside `<rect>`/`<ellipse>`, which browsers never
 * paint. Hoist the text next to its shape and normalise the paints.
 */
export function repairRenderedVml(root: Element): void {
  root.querySelectorAll('svg [fill], svg [stroke]').forEach((element) => {
    for (const name of ['fill', 'stroke']) {
      const value = element.getAttribute(name)
      if (value == null) continue
      const cleaned = value.replace(VML_THEME_SUFFIX, '')
      if (!cleaned || cleaned === 'null') element.removeAttribute(name)
      else if (cleaned !== value) element.setAttribute(name, cleaned)
    }
    if (element.getAttribute('stroke-width') && !element.hasAttribute('stroke')) {
      element.removeAttribute('stroke-width')
    }
  })
  root.querySelectorAll('svg foreignObject').forEach((foreign) => {
    const parent = foreign.parentElement
    if (parent && !SVG_CONTAINERS.has(parent.localName)) parent.after(foreign)
  })
}

/** Tag pages and paragraphs with the anchors the host viewer relies on. */
export function annotateRenderedDocx(root: Element): number {
  const pages = Array.from(root.querySelectorAll<HTMLElement>('section.docx'))
  pages.forEach((page, index) => {
    page.setAttribute('data-preview-item', '')
    page.setAttribute('data-preview-label', `Page ${index + 1}`)
    page.setAttribute('data-page-index', String(index))
  })
  root.querySelectorAll<HTMLElement>('section.docx p').forEach((paragraph) => {
    const label = (paragraph.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 80)
    if (label) paragraph.setAttribute('data-qa-label', label)
  })
  root.querySelectorAll<HTMLElement>('section.docx table').forEach((table, index) => {
    table.setAttribute('data-qa-label', `Table ${index + 1}`)
  })
  return pages.length
}

/** Render DOCX bytes into a self-contained, inert preview document. */
export async function renderDocxPreviewHtml(data: ArrayBuffer, title: string): Promise<string> {
  if (data.byteLength > MAX_DOCX_SOURCE_BYTES) {
    throw new Error('This document is too large for the in-app viewer. Download the file to inspect it externally.')
  }
  const { renderAsync } = await import('docx-preview')
  const body = document.createElement('div')
  const styles = document.createElement('div')
  await renderAsync(data, body, styles, {
    className: 'docx',
    inWrapper: true,
    breakPages: true,
    ignoreLastRenderedPageBreak: false,
    experimental: true,
    renderHeaders: true,
    renderFooters: true,
    renderFootnotes: true,
    renderEndnotes: true,
    renderChanges: true,
    // Comment highlights use the CSS Custom Highlight API, which cannot be
    // serialized into the inert iframe document.
    renderComments: false,
    renderAltChunks: false,
    useBase64URL: true,
  })
  neutralizeRenderedDocx(body)
  neutralizeRenderedDocx(styles)
  repairRenderedVml(body)
  if (annotateRenderedDocx(body) === 0) {
    throw new Error('The document renderer produced no pages.')
  }
  const styleMarkup = Array.from(styles.querySelectorAll('style'))
    .map((style) => `<style>${style.textContent ?? ''}</style>`)
    .join('')
  return '<!doctype html><html><head><meta charset="utf-8">'
    + `<meta http-equiv="Content-Security-Policy" content="${escapeHtml(DOCUMENT_PREVIEW_CSP)}">`
    + '<meta name="referrer" content="no-referrer">'
    + `<title>${escapeHtml(title)}</title>${styleMarkup}<style>${VIEWER_CSS}</style></head>`
    + `<body>${body.innerHTML}</body></html>`
}
