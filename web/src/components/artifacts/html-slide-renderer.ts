import { collectEditableElements, type RenderIssue, type RenderRequest } from './slide-editable'
import slideRuntimeCss from './slide-runtime.css?inline'

const sleep = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds))

function pngPayload(dataUrl: string): string {
  const marker = 'base64,'
  const index = dataUrl.indexOf(marker)
  if (index < 0) throw new Error('WebView renderer did not produce a base64 PNG.')
  return dataUrl.slice(index + marker.length)
}

async function waitForAssets(document: Document): Promise<RenderIssue[]> {
  const issues: RenderIssue[] = []
  await document.fonts?.ready
  const images = Array.from(document.images)
  await Promise.all(images.map(async (image) => {
    if (!image.complete) {
      await Promise.race([
        new Promise<void>((resolve) => {
          image.addEventListener('load', () => resolve(), { once: true })
          image.addEventListener('error', () => resolve(), { once: true })
        }),
        sleep(10_000),
      ])
    }
    if (!image.complete || image.naturalWidth === 0) {
      issues.push({ severity: 'error', code: 'broken-slide-image', message: `Image ${image.alt || image.src.slice(0, 80)} did not load.` })
    }
  }))
  return issues
}

export async function renderHtmlSlide(request: RenderRequest) {
  const iframe = document.createElement('iframe')
  iframe.setAttribute('aria-hidden', 'true')
  iframe.setAttribute('sandbox', 'allow-same-origin')
  Object.assign(iframe.style, {
    position: 'fixed',
    left: '-10000px',
    top: '0',
    width: `${request.width}px`,
    height: `${request.height}px`,
    border: '0',
    opacity: '0',
    pointerEvents: 'none',
  })
  const shellRules = `
    [data-evoflux-shell-text], [data-evoflux-shell-text] * {
      color: transparent !important;
      -webkit-text-fill-color: transparent !important;
      text-shadow: none !important;
    }
    [data-evoflux-shell-image] { visibility: hidden !important; }
  `
  iframe.srcdoc = `<!doctype html><html><head>
    <meta charset="utf-8">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline';">
    <style>${slideRuntimeCss}</style>
    <style>${request.css}</style>
    <style>${shellRules}</style>
    <style>html,body{margin:0;width:${request.width}px;height:${request.height}px;overflow:hidden;background:transparent}*{box-sizing:border-box}[data-slide-root]{width:${request.width}px;height:${request.height}px;overflow:hidden}</style>
  </head><body>${request.html}</body></html>`
  document.body.appendChild(iframe)
  try {
    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error('Slide iframe timed out.')), 15_000)
      iframe.addEventListener('load', () => {
        window.clearTimeout(timeout)
        resolve()
      }, { once: true })
    })
    const frameDocument = iframe.contentDocument
    if (!frameDocument) throw new Error('Slide iframe document is unavailable.')
    const roots = frameDocument.querySelectorAll<HTMLElement>('[data-slide-root]')
    if (roots.length !== 1) throw new Error('Slide HTML must contain exactly one data-slide-root element.')
    const root = roots[0]
    const issues = await waitForAssets(frameDocument)
    if (root.scrollWidth > request.width + 1 || root.scrollHeight > request.height + 1) {
      issues.push({ severity: 'error', code: 'slide-content-overflow', message: `Slide content exceeds the ${request.width}×${request.height} canvas.` })
    }
    const editable = collectEditableElements(root, request)
    issues.push(...editable.issues)
    const { toPng } = await import('html-to-image')
    const captureOptions = {
      width: request.width,
      height: request.height,
      pixelRatio: 1,
      cacheBust: false,
      skipAutoScale: true,
    }
    const preview = await toPng(root, captureOptions)
    editable.hidden.forEach((element) => {
      element.setAttribute(
        element.getAttribute('data-pptx-editable') === 'image'
          ? 'data-evoflux-shell-image'
          : 'data-evoflux-shell-text',
        '',
      )
    })
    const shell = await toPng(root, { ...captureOptions, pixelRatio: 2 })
    return {
      preview_png_base64: pngPayload(preview),
      shell_png_base64: pngPayload(shell),
      editable_elements: editable.elements,
      issues,
    }
  } finally {
    iframe.remove()
  }
}
