import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const {
  workPreviewUrl,
  codingPreviewUrl,
  renderDocx,
  runtime,
  installRuntime,
  cancelRuntime,
  versions,
  changeVersion,
  checkpoint,
} = vi.hoisted(() => ({
  workPreviewUrl: vi.fn((sessionId: string, path: string) => `/work/${sessionId}/${path}`),
  codingPreviewUrl: vi.fn((workspace: string, path: string) => `/coding/${workspace}/${path}`),
  renderDocx: vi.fn(),
  runtime: { status: undefined as unknown, installError: null as Error | null },
  installRuntime: vi.fn(),
  cancelRuntime: vi.fn(),
  versions: { data: undefined as unknown },
  changeVersion: vi.fn(),
  checkpoint: vi.fn(() => Promise.resolve({})),
}))

vi.mock('@/queries/useDocumentVersionsQuery', () => ({
  useDocumentVersionsQuery: () => ({ data: versions.data }),
  useDocumentVersionMutation: () => ({ mutate: changeVersion, isPending: false, error: null }),
}))

vi.mock('@/queries/useOfficeRuntimeQuery', () => ({
  useOfficeRuntimeQuery: () => ({ data: runtime.status }),
  useInstallOfficeRuntimeMutation: () => ({
    mutate: installRuntime,
    isPending: false,
    error: runtime.installError,
    reset: vi.fn(),
  }),
  useDismissOfficeRuntimeErrorMutation: () => ({ mutate: vi.fn(), isPending: false }),
  useCancelOfficeRuntimeInstallMutation: () => ({
    mutate: cancelRuntime,
    isPending: false,
    error: null,
    reset: vi.fn(),
  }),
}))

const availableRuntime = {
  available: true,
  platform: 'win32-x64',
  version: '26.8.0',
  download_bytes: 191_184_974,
  install_bytes: 635_851_559,
  installed_version: null,
  job: null,
}

vi.mock('@/api/client', () => ({
  workspaceDocumentPreviewUrl: workPreviewUrl,
  codingWorkspaceDocumentPreviewUrl: codingPreviewUrl,
  workspaceMediaUrl: (sessionId: string, path: string) => `/media/${sessionId}/${path}`,
  codingWorkspaceFileUrl: (workspace: string, path: string) => `/raw/${workspace}/${path}`,
  changeDocumentVersion: checkpoint,
}))

vi.mock('@/lib/docx-preview-render', () => ({
  MAX_DOCX_SOURCE_BYTES: 100 * 1024 * 1024,
  renderDocxPreviewHtml: renderDocx,
}))

import { WorkspaceDocumentPreview } from '@/components/workspace-document-preview'

const workbookHtml = `<!doctype html><html><head></head><body>
  <section data-preview-item data-preview-label="Forecast" data-preview-fit-width="800" data-preview-fit-height="400">
    <span class="column-header" data-column="A">A</span>
    <span class="column-header" data-column="B">B</span>
    <span class="row-number" data-row="1">1</span>
    <span class="row-number" data-row="2">2</span>
    <div class="cell" data-cell="A1">Revenue</div>
    <div class="cell" data-cell="B1">Plan</div>
    <div class="cell formula" data-cell="B2" data-formula="=SUM(B3:B4)" data-display-value="42">42</div>
  </section>
  <section data-preview-item data-preview-label="Assumptions" data-preview-fit-width="800" data-preview-fit-height="400">
    <div class="cell" data-cell="A1">Growth</div>
  </section>
</body></html>`

const slideDeckHtml = `<!doctype html><html><head><style>
  body { margin: 0; background: #e8eaed; }
  .slide-wrap { width: 800px; }
  .slide { position: relative; width: 100%; background: white; }
</style></head><body>
  <article class="slide-wrap" data-preview-item data-preview-label="Opening" data-preview-notes="Set the context before presenting the result.">
    <section class="slide" style="aspect-ratio:16 / 9"><h1>Overview</h1></section>
  </article>
  <article class="slide-wrap" data-preview-item data-preview-label="Roadmap">
    <section class="slide" style="aspect-ratio:16 / 9"><h1>Roadmap</h1><aside data-preview-notes>Emphasize the Q4 launch milestone.</aside></section>
  </article>
</body></html>`

const documentHtml = `<!doctype html><html><head></head><body>
  <article data-preview-item data-preview-label="Page 1"><h1>Summary</h1></article>
  <article data-preview-item data-preview-label="Page 2"><h2>Details</h2></article>
</body></html>`

function hydrateFrame(html = workbookHtml): HTMLIFrameElement {
  const frame = screen.getByTestId('document-preview-frame') as HTMLIFrameElement
  const document = frame.contentDocument
  if (!document) throw new Error('Test iframe document is unavailable')
  const parsed = new DOMParser().parseFromString(html, 'text/html')
  document.head.innerHTML = parsed.head.innerHTML
  document.body.innerHTML = parsed.body.innerHTML
  Object.defineProperty(frame, 'clientWidth', { configurable: true, value: 832 })
  Object.defineProperty(frame, 'clientHeight', { configurable: true, value: 600 })
  document.querySelectorAll<HTMLElement>('[data-preview-item]').forEach((item) => {
    Object.defineProperty(item, 'scrollWidth', { configurable: true, value: 400 })
    Object.defineProperty(item, 'scrollHeight', { configurable: true, value: 400 })
    item.getBoundingClientRect = () => new DOMRect(0, 0, 400, 400)
  })
  fireEvent.load(frame)
  return frame
}

beforeEach(() => {
  workPreviewUrl.mockClear()
  codingPreviewUrl.mockClear()
  renderDocx.mockReset()
  renderDocx.mockResolvedValue(documentHtml)
  runtime.status = undefined
  runtime.installError = null
  installRuntime.mockReset()
  cancelRuntime.mockReset()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    text: () => Promise.resolve(workbookHtml),
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)),
  }))
  if (!HTMLElement.prototype.scrollIntoView) {
    HTMLElement.prototype.scrollIntoView = vi.fn()
  }
})

describe('WorkspaceDocumentPreview', () => {
  it('uses the Work endpoint and exposes a shared Office-like reader shell', async () => {
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{
          path: 'models/forecast.xlsx',
          name: 'forecast.xlsx',
          mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          size: 10,
          mtime: 2,
        }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/work/session-1/models/forecast.xlsx', expect.any(Object)))
    hydrateFrame()

    expect(await screen.findByRole('navigation', { name: 'Workbook sheets' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Search document' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Fit width' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Fit page' })).toBeInTheDocument()
    expect(screen.getByLabelText('Zoom 100 percent')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open sheet 2: Assumptions' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Document navigator' })).not.toBeInTheDocument()
    expect(screen.queryByText('Read only')).not.toBeInTheDocument()
    expect(screen.getByText('Forecast')).toBeInTheDocument()
    expect(screen.getByText('Assumptions')).toBeInTheDocument()
  })

  it('updates the Excel name/formula bars when a rendered cell is selected', async () => {
    render(
      <WorkspaceDocumentPreview
        workspace="/repo"
        file={{
          path: 'forecast.xlsx',
          name: 'forecast.xlsx',
          mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          size: 10,
          mtime: 2,
        }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const frame = hydrateFrame()
    const formulaCell = frame.contentDocument?.querySelector<HTMLElement>('[data-cell="B2"]')
    if (!formulaCell) throw new Error('Formula cell was not rendered')
    fireEvent.click(formulaCell)

    expect(screen.getByLabelText('Selected cell')).toHaveTextContent('B2')
    expect(screen.getByLabelText('Formula bar')).toHaveTextContent('=SUM(B3:B4)')
    expect(frame.contentDocument?.querySelector('[data-column="B"]')).toHaveAttribute('data-evoflux-selected-header', 'true')
    expect(frame.contentDocument?.querySelector('[data-row="2"]')).toHaveAttribute('data-evoflux-selected-header', 'true')
    expect(codingPreviewUrl).toHaveBeenCalledWith('/repo', 'forecast.xlsx')
  })

  it('keeps DOCX content full-width until the page navigator is requested', async () => {
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'report.docx', name: 'report.docx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    hydrateFrame(documentHtml)

    expect(screen.queryByRole('navigation', { name: 'Document navigator' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show navigator' }))
    expect(screen.getByRole('navigation', { name: 'Document navigator' })).toBeInTheDocument()
    expect(screen.queryByText('Read only')).not.toBeInTheDocument()
  })

  it('renders DOCX from the raw file on the client instead of the backend preview', async () => {
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'report.docx', name: 'report.docx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    await waitFor(() => expect(renderDocx).toHaveBeenCalledWith(expect.any(ArrayBuffer), 'report.docx'))
    expect(fetch).toHaveBeenCalledWith('/media/session-1/report.docx', expect.any(Object))
    expect(fetch).not.toHaveBeenCalledWith('/work/session-1/report.docx', expect.any(Object))
    await waitFor(() => expect(screen.getByTestId('document-preview-frame')).toHaveAttribute('srcdoc', documentHtml))
  })

  it('offers the exact renderer and starts its download only on request', async () => {
    runtime.status = availableRuntime
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'deck.pptx', name: 'deck.pptx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    hydrateFrame(slideDeckHtml)

    expect(screen.getByText(/This preview is approximate/)).not.toHaveTextContent(/MB/)
    expect(installRuntime).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Install renderer' }))
    expect(installRuntime).toHaveBeenCalledTimes(1)
  })

  it('reports download progress while the renderer installs', async () => {
    runtime.status = {
      ...availableRuntime,
      job: {
        phase: 'downloading',
        version: '26.8.0',
        bytes_done: 95_592_487,
        bytes_total: 191_184_974,
        started_at: '2026-09-23T00:00:00Z',
        error: null,
      },
    }
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'forecast.xlsx', name: 'forecast.xlsx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    hydrateFrame()

    const progress = screen.getByRole('status', { name: '' })
    expect(progress).toHaveTextContent('Downloading the exact renderer')
    expect(progress).toHaveTextContent('50% · 91 MB / 182 MB')
  })

  it('renders DOCX through the backend once the exact renderer is installed', async () => {
    runtime.status = { ...availableRuntime, installed_version: '26.8.0' }
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'report.docx', name: 'report.docx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/work/session-1/report.docx', expect.any(Object)))
    expect(renderDocx).not.toHaveBeenCalled()
    expect(screen.queryByText(/This preview is approximate/)).not.toBeInTheDocument()
  })

  it('falls back to the backend DOCX preview when client rendering fails', async () => {
    renderDocx.mockRejectedValue(new Error('corrupt'))
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    render(
      <WorkspaceDocumentPreview
        workspace="/repo"
        file={{ path: 'report.docx', name: 'report.docx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/coding//repo/report.docx', expect.any(Object)))
    expect(fetch).toHaveBeenCalledWith('/raw//repo/report.docx', expect.any(Object))
  })

  it('searches rendered content and navigates between preview items', async () => {
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'forecast.xlsx', name: 'forecast.xlsx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const frame = hydrateFrame()
    fireEvent.click(screen.getByRole('button', { name: 'Search document' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Find in document' }), { target: { value: 'Revenue' } })

    expect(frame.contentDocument?.querySelectorAll('mark[data-evoflux-search]')).toHaveLength(1)
    expect(screen.getByText('1/1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open sheet 2: Assumptions' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Open sheet 2: Assumptions' })).toHaveAttribute('aria-current', 'page'))
    expect(frame.contentDocument?.querySelectorAll('[data-preview-item]')[0]).toHaveAttribute('hidden')
    expect(frame.contentDocument?.querySelectorAll('[data-preview-item]')[1]).not.toHaveAttribute('hidden')
  })

  it.each([
    {
      name: 'sheet',
      file: { path: 'forecast.xlsx', name: 'forecast.xlsx', mime: '', size: 10, mtime: 2 },
      html: workbookHtml,
      query: 'Growth',
      activeControl: 'Open sheet 2: Assumptions',
    },
    {
      name: 'slide',
      file: { path: 'roadmap.pptx', name: 'roadmap.pptx', mime: '', size: 10, mtime: 2 },
      html: `<!doctype html><html><head></head><body>
        <article data-preview-item data-preview-label="Slide 1"><h1>Overview</h1></article>
        <article data-preview-item data-preview-label="Slide 2"><h1>Roadmap</h1></article>
      </body></html>`,
      query: 'Roadmap',
      activeControl: 'Go to slide 2: Slide 2',
      // One slide at a time only with the thumbnails shown.
      thumbnails: true,
    },
  ])('reveals the hidden $name containing a search result', async ({ file, html, query, activeControl, thumbnails }) => {
    render(<WorkspaceDocumentPreview sessionId="session-1" file={file} />)

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    let frame = hydrateFrame(html)
    if (thumbnails) {
      fireEvent.click(await screen.findByRole('button', { name: 'Show slide thumbnails' }))
      frame = hydrateFrame(html)
    }
    fireEvent.click(screen.getByRole('button', { name: 'Search document' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Find in document' }), { target: { value: query } })

    const items = frame.contentDocument?.querySelectorAll('[data-preview-item]')
    await waitFor(() => expect(screen.getByRole('button', { name: activeControl })).toHaveAttribute('aria-current', 'page'))
    expect(items?.[0]).toHaveAttribute('hidden')
    expect(items?.[1]).not.toHaveAttribute('hidden')
    expect(items?.[1].querySelector('mark[data-evoflux-search]')).toHaveTextContent(query)
  })

  it('keeps cell arrow keys in the grid while frame arrows navigate sheets', async () => {
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'forecast.xlsx', name: 'forecast.xlsx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const frame = hydrateFrame()
    const document = frame.contentDocument
    const firstCell = document?.querySelector<HTMLElement>('[data-cell="A1"]')
    if (!document || !firstCell || !frame.contentWindow) throw new Error('Workbook frame was not hydrated')

    fireEvent.click(firstCell)
    fireEvent.keyDown(firstCell, { key: 'ArrowRight' })
    expect(screen.getByLabelText('Selected cell')).toHaveTextContent('B1')
    expect(document.querySelectorAll('[data-preview-item]')[0]).not.toHaveAttribute('hidden')
    expect(document.querySelectorAll('[data-preview-item]')[1]).toHaveAttribute('hidden')

    fireEvent.keyDown(frame.contentWindow, { key: 'ArrowRight' })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Open sheet 2: Assumptions' })).toHaveAttribute('aria-current', 'page'))
    expect(document.querySelectorAll('[data-preview-item]')[1]).not.toHaveAttribute('hidden')
  })

  it('uses the latest zoom state for repeated iframe keyboard shortcuts', async () => {
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'roadmap.pptx', name: 'roadmap.pptx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const frame = hydrateFrame(`<!doctype html><html><head></head><body>
      <article data-preview-item data-preview-label="Slide 1">Overview</article>
    </body></html>`)
    if (!frame.contentWindow) throw new Error('Slide frame window is unavailable')
    await waitFor(() => expect(screen.getByLabelText('Zoom 142 percent')).toBeInTheDocument())

    fireEvent.keyDown(frame.contentWindow, { key: '+' })
    await waitFor(() => expect(screen.getByLabelText('Zoom 152 percent')).toBeInTheDocument())
    fireEvent.keyDown(frame.contentWindow, { key: '+' })
    await waitFor(() => expect(screen.getByLabelText('Zoom 162 percent')).toBeInTheDocument())
  })

  it('provides PowerPoint thumbnails, slide sorter, and speaker notes views', async () => {
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'roadmap.pptx', name: 'roadmap.pptx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    hydrateFrame(slideDeckHtml)

    const normalView = await screen.findByRole('button', { name: 'Normal view' })
    expect(normalView).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('toolbar', { name: 'PowerPoint View controls' })).toBeInTheDocument()
    // Thumbnails start hidden and open from the toolbar.
    expect(screen.queryByRole('navigation', { name: 'Slide thumbnails' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show slide thumbnails' }))
    expect(screen.getByRole('navigation', { name: 'Slide thumbnails' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Go to slide 1: Opening' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getAllByTitle(/Thumbnail for slide/)).toHaveLength(2)

    fireEvent.click(screen.getByRole('button', { name: 'Slide sorter view' }))
    expect(screen.getByRole('button', { name: 'Slide sorter view' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('region', { name: 'Slide sorter' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Slide thumbnails' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Open slide 2: Roadmap' }))
    await waitFor(() => expect(screen.getAllByText('Slide 2 of 2').length).toBeGreaterThan(0))
    expect(normalView).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Go to slide 2: Roadmap' })).toHaveAttribute('aria-current', 'page')

    fireEvent.click(screen.getByRole('button', { name: 'Show speaker notes' }))
    expect(screen.getByRole('region', { name: 'Speaker notes' })).toHaveTextContent('Emphasize the Q4 launch milestone.')
    expect(screen.getByRole('button', { name: 'Hide speaker notes' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('gives a deck under construction the whole surface until it is finished', async () => {
    const liveDeckHtml = slideDeckHtml
      .replace('<body>', '<body><main data-deck-live="true">')
      .replace('</body>', '</main></body>')
    const respond = (html: string) => ({ ok: true, status: 200, text: () => Promise.resolve(html) })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(slideDeckHtml)))
    const onLiveDeckChange = vi.fn()
    const deck = { path: 'deck.pptx', name: 'deck.pptx', mime: '', size: 10, mtime: 2 }
    const view = (mtime: number) => (
      <WorkspaceDocumentPreview sessionId="session-1" file={{ ...deck, mtime }} onLiveDeckChange={onLiveDeckChange} />
    )
    const { rerender } = render(view(2))
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    hydrateFrame(slideDeckHtml)
    fireEvent.click(await screen.findByRole('button', { name: 'Show slide thumbnails' }))
    expect(screen.getByRole('navigation', { name: 'Slide thumbnails' })).toBeInTheDocument()

    // The agent starts rebuilding the deck: the thumbnails step aside…
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(liveDeckHtml)))
    rerender(view(3))
    await waitFor(() => expect(onLiveDeckChange).toHaveBeenLastCalledWith(true))
    hydrateFrame(liveDeckHtml)
    expect(screen.queryByRole('navigation', { name: 'Slide thumbnails' })).not.toBeInTheDocument()

    // …and come back once it is finished.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(slideDeckHtml)))
    rerender(view(4))
    await waitFor(() => expect(onLiveDeckChange).toHaveBeenLastCalledWith(false))
    hydrateFrame(slideDeckHtml)
    expect(await screen.findByRole('navigation', { name: 'Slide thumbnails' })).toBeInTheDocument()
    expect(onLiveDeckChange).toHaveBeenCalledTimes(2)
  })

  it('follows the slide being built until the user scrolls away, and again once they scroll back', async () => {
    const liveDeckOf = (statuses: string[]) => `<!doctype html><html><head></head><body><main data-deck-live="true">${
      statuses.map((status, index) => (
        `<article data-preview-item data-preview-label="Slide ${index + 1}" data-slide-status="${status}"><section class="slide"></section></article>`
      )).join('')
    }</main></body></html>`
    const deck = { path: 'deck.pptx', name: 'deck.pptx', mime: '', size: 10, mtime: 1 }
    const view = (mtime: number) => (
      <WorkspaceDocumentPreview sessionId="session-1" file={{ ...deck, mtime }} agentWorking />
    )
    const { rerender } = render(view(0))
    const nextFrame = (frame: HTMLIFrameElement) => new Promise<void>((resolve) => {
      frame.contentWindow?.requestAnimationFrame(() => resolve())
    })
    // The agent saves the deck: the viewer re-renders it in place.
    const save = async (mtime: number, statuses: string[]) => {
      const html = liveDeckOf(statuses)
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, text: () => Promise.resolve(html) }))
      rerender(view(mtime))
      await waitFor(() => expect(screen.getByTestId('document-preview-frame')).toHaveAttribute('srcdoc', html))
      const frame = hydrateFrame(html)
      const slides = Array.from(frame.contentDocument?.querySelectorAll<HTMLElement>('[data-preview-item]') ?? [])
      slides.forEach((slide) => { slide.scrollIntoView = vi.fn() })
      await nextFrame(frame)
      return { frame, slides }
    }
    const followed = { block: 'center', behavior: 'smooth' }

    let { frame, slides } = await save(1, ['done', 'building', 'pending', 'pending'])
    expect(slides[1].scrollIntoView).toHaveBeenCalledWith(followed)

    // Scrolling away hands the viewer to the user…
    fireEvent.wheel(frame.contentWindow as Window)
    ;({ frame, slides } = await save(2, ['done', 'done', 'building', 'pending']))
    expect(slides[2].scrollIntoView).not.toHaveBeenCalled()

    // …and scrolling back to the slide being built follows it again.
    fireEvent.scroll(frame.contentWindow as Window)
    await nextFrame(frame)
    ;({ frame, slides } = await save(3, ['done', 'done', 'done', 'building']))
    expect(slides[3].scrollIntoView).toHaveBeenCalledWith(followed)
  })

  it('keeps the current slide, not the pixel offset, when the exact render replaces the native one', async () => {
    const deckOf = (renderer: string | null) => `<!doctype html><html><head></head><body>${
      renderer ? `<main data-preview-renderer="${renderer}">` : '<main>'
    }${[1, 2, 3, 4].map((n) => `<article data-preview-item data-preview-label="Slide ${n}"><section class="slide"></section></article>`).join('')
    }</main></body></html>`
    const deck = { path: 'deck.pptx', name: 'deck.pptx', mime: '', size: 10, mtime: 1 }
    const respond = (html: string) => ({ ok: true, status: 200, text: () => Promise.resolve(html) })
    const native = deckOf(null)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(native)))
    const { rerender } = render(<WorkspaceDocumentPreview sessionId="session-1" file={deck} />)
    await waitFor(() => expect(screen.getByTestId('document-preview-frame')).toHaveAttribute('srcdoc', native))
    let frame = hydrateFrame(native)
    const frameWindow = frame.contentWindow as Window
    await new Promise<void>((resolve) => frameWindow.requestAnimationFrame(() => resolve()))

    // Scrolled to the end: the last slide is current even though its top
    // never reaches the top of the view.
    Object.defineProperty(frameWindow, 'scrollY', { configurable: true, value: 500 })
    Object.defineProperty(frameWindow.document.documentElement, 'scrollHeight', { configurable: true, value: frameWindow.innerHeight + 500 })
    fireEvent.scroll(frameWindow)
    expect(await screen.findByText(/Slide 4 of 4/)).toBeInTheDocument()

    // The exact render lays slides out differently: land on slide 4 again.
    const exact = deckOf('libreoffice-26.8.0')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(exact)))
    rerender(<WorkspaceDocumentPreview sessionId="session-1" file={{ ...deck, mtime: 2 }} />)
    await waitFor(() => expect(screen.getByTestId('document-preview-frame')).toHaveAttribute('srcdoc', exact))
    frame = hydrateFrame(exact)
    const slides = Array.from(frame.contentDocument?.querySelectorAll<HTMLElement>('[data-preview-item]') ?? [])
    slides.forEach((slide) => { slide.scrollIntoView = vi.fn() })
    const scrollTo = vi.spyOn(frame.contentWindow as Window, 'scrollTo').mockImplementation(() => undefined)
    await new Promise<void>((resolve) => frame.contentWindow?.requestAnimationFrame(() => resolve()))

    expect(slides[3].scrollIntoView).toHaveBeenCalledWith({ block: 'start' })
    expect(scrollTo).not.toHaveBeenCalled()
    expect(screen.getByText(/Slide 4 of 4/)).toBeInTheDocument()
  })

  it('re-renders a deck when the agent turn ends, since only a running build is shown live', async () => {
    const deck = { path: 'deck.pptx', name: 'deck.pptx', mime: '', size: 10, mtime: 2 }
    const { rerender } = render(<WorkspaceDocumentPreview sessionId="session-1" file={deck} agentWorking />)
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))

    rerender(<WorkspaceDocumentPreview sessionId="session-1" file={deck} agentWorking={false} />)
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
  })

  it('navigates PowerPoint slides with arrows, Home, End, and Space', async () => {
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'roadmap.pptx', name: 'roadmap.pptx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    hydrateFrame(slideDeckHtml)
    fireEvent.click(await screen.findByRole('button', { name: 'Show slide thumbnails' }))
    const frame = hydrateFrame(slideDeckHtml)
    if (!frame.contentWindow) throw new Error('Slide frame window is unavailable')

    fireEvent.keyDown(frame.contentWindow, { key: 'End' })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Go to slide 2: Roadmap' })).toHaveAttribute('aria-current', 'page'))
    fireEvent.keyDown(frame.contentWindow, { key: 'Home' })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Go to slide 1: Opening' })).toHaveAttribute('aria-current', 'page'))
    fireEvent.keyDown(frame.contentWindow, { key: ' ' })
    await waitFor(() => expect(screen.getAllByText('Slide 2 of 2').length).toBeGreaterThan(0))
  })

  it('uses a dark, distraction-free Reading View with overlay navigation and Escape exit', async () => {
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'roadmap.pptx', name: 'roadmap.pptx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const frame = hydrateFrame(slideDeckHtml)
    if (!frame.contentWindow) throw new Error('Slide frame window is unavailable')

    fireEvent.click(screen.getByRole('button', { name: 'Show speaker notes' }))
    expect(screen.getByRole('region', { name: 'Speaker notes' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Start Reading View slide show' }))
    const readingView = screen.getByRole('region', { name: 'PowerPoint reading view' })

    expect(screen.getByTestId('workspace-document-preview')).toHaveAttribute('data-presentation-view', 'reading')
    expect(screen.queryByRole('toolbar', { name: 'PowerPoint View controls' })).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Slide thumbnails' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Speaker notes' })).not.toBeInTheDocument()
    expect(frame.contentDocument?.documentElement.style.getPropertyValue('--evoflux-stage-background')).toBe('#111111')
    expect(within(readingView).getByRole('button', { name: 'Previous slide in Reading View' })).toBeDisabled()
    expect(within(readingView).getByRole('status')).toHaveTextContent('Slide 1 of 2')

    fireEvent.click(within(readingView).getByRole('button', { name: 'Next slide in Reading View' }))
    await waitFor(() => expect(within(readingView).getByRole('status')).toHaveTextContent('Slide 2 of 2'))
    expect(frame.contentDocument?.querySelectorAll('[data-preview-item]')[1]).not.toHaveAttribute('hidden')

    fireEvent.keyDown(frame.contentWindow, { key: 'Escape' })
    await waitFor(() => expect(screen.getByRole('toolbar', { name: 'PowerPoint View controls' })).toBeInTheDocument())
    expect(screen.queryByRole('region', { name: 'PowerPoint reading view' })).not.toBeInTheDocument()
    expect(screen.getByTestId('workspace-document-preview')).toHaveAttribute('data-presentation-view', 'normal')
  })

  it('keeps Reading View active when optional fullscreen is denied by the host', async () => {
    const originalFullscreen = Object.getOwnPropertyDescriptor(Element.prototype, 'requestFullscreen')
    const requestFullscreen = vi.fn().mockRejectedValue(new Error('Fullscreen denied'))
    Object.defineProperty(Element.prototype, 'requestFullscreen', {
      configurable: true,
      value: requestFullscreen,
    })

    const view = render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'roadmap.pptx', name: 'roadmap.pptx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    try {
      await waitFor(() => expect(fetch).toHaveBeenCalled())
      hydrateFrame(slideDeckHtml)
      fireEvent.click(screen.getByRole('button', { name: 'Start Reading View slide show' }))

      const fullscreenButton = await screen.findByRole('button', { name: 'Enter full screen' })
      fireEvent.click(fullscreenButton)
      await waitFor(() => expect(requestFullscreen).toHaveBeenCalledTimes(1))
      expect(screen.getByRole('region', { name: 'PowerPoint reading view' })).toBeInTheDocument()
    } finally {
      view.unmount()
      if (originalFullscreen) {
        Object.defineProperty(Element.prototype, 'requestFullscreen', originalFullscreen)
      } else {
        Reflect.deleteProperty(Element.prototype, 'requestFullscreen')
      }
    }
  })
})

describe('WorkspaceDocumentPreview exact renderer banner', () => {
  const pptx = { path: 'deck.pptx', name: 'deck.pptx', mime: '', size: 10, mtime: 2 }
  const downloadingJob = {
    phase: 'downloading' as const,
    version: '26.8.0',
    bytes_done: 1,
    bytes_total: 2,
    started_at: '2026-09-23T00:00:00Z',
    error: null,
  }

  it('lets the user cancel a running download', async () => {
    runtime.status = { ...availableRuntime, job: downloadingJob }
    render(<WorkspaceDocumentPreview sessionId="session-1" file={pptx} />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    hydrateFrame(slideDeckHtml)

    expect(screen.getByRole('progressbar', { name: 'Exact renderer download' })).toHaveAttribute('aria-valuenow', '50')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(cancelRuntime).toHaveBeenCalledTimes(1)
  })

  it('surfaces a rejected install request instead of failing silently', async () => {
    runtime.status = { ...availableRuntime, available: false }
    runtime.installError = new Error('No verified LibreOffice runtime is published for this platform.')
    render(<WorkspaceDocumentPreview sessionId="session-1" file={pptx} />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    hydrateFrame(slideDeckHtml)

    expect(screen.getByRole('alert')).toHaveTextContent('No verified LibreOffice runtime is published')
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
  })

  it('offers an update when a newer renderer is pinned', async () => {
    runtime.status = { ...availableRuntime, version: '26.8.1', installed_version: '26.8.0' }
    render(<WorkspaceDocumentPreview sessionId="session-1" file={pptx} />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    hydrateFrame(slideDeckHtml)

    expect(screen.getByText(/A newer exact renderer \(LibreOffice 26.8.1\)/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Update renderer' }))
    expect(installRuntime).toHaveBeenCalledTimes(1)
  })

  it('says so when the installed renderer fell back to the approximate preview', async () => {
    runtime.status = { ...availableRuntime, installed_version: '26.8.0' }
    render(<WorkspaceDocumentPreview sessionId="session-1" file={pptx} />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    hydrateFrame(slideDeckHtml)

    expect(screen.getByText(/could not render this file/)).toBeInTheDocument()
  })

  it('remembers a hidden install offer per renderer version', async () => {
    window.localStorage.clear()
    runtime.status = availableRuntime
    const { unmount } = render(<WorkspaceDocumentPreview sessionId="session-1" file={pptx} />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    hydrateFrame(slideDeckHtml)
    fireEvent.click(screen.getByRole('button', { name: 'Hide renderer suggestion' }))
    unmount()

    render(<WorkspaceDocumentPreview sessionId="session-1" file={pptx} />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    hydrateFrame(slideDeckHtml)
    expect(screen.queryByText(/This preview is approximate/)).not.toBeInTheDocument()
    window.localStorage.clear()
  })
})

describe('WorkspaceDocumentPreview loading skeleton', () => {
  it.each([
    ['deck.pptx', 'PowerPoint'],
    ['model.xlsx', 'Excel'],
    ['report.docx', 'Word'],
  ])('shows a %s-shaped skeleton while the preview renders', async (name, label) => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => undefined)))
    renderDocx.mockReturnValue(new Promise(() => undefined))
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: name, name, mime: '', size: 10, mtime: 2 }}
      />,
    )

    expect(await screen.findByTestId('document-preview-skeleton')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(`Rendering ${label} document…`)
    expect(screen.queryByTestId('document-preview-frame')).not.toBeInTheDocument()
  })

  it('tells the user the first exact render can take a while', async () => {
    runtime.status = { ...availableRuntime, installed_version: '26.8.0' }
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => undefined)))
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'deck.pptx', name: 'deck.pptx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    expect(await screen.findByRole('status')).toHaveTextContent('first exact render can take up to a minute')
  })
})

describe('WorkspaceDocumentPreview annotations', () => {
  const annotatableDeckHtml = `<!doctype html><html><head></head><body>
    <article class="slide-wrap" data-preview-item data-preview-label="Slide 1 — Revenue">
      <section class="slide" style="aspect-ratio:16/9">
        <div class="shape chart" data-shape-id="12" data-shape-name="Chart 3" data-source-layer="slide"><span>Quarterly P&amp;L</span></div>
        <div class="shape" data-shape-id="2" data-shape-name="Logo" data-source-layer="master">Brand</div>
      </section>
    </article>
  </body></html>`
  const deck = { path: 'deck.pptx', name: 'deck.pptx', mime: '', size: 10, mtime: 2 }

  function pointer(frame: HTMLIFrameElement, type: string, target: Element, x: number, y: number) {
    const FrameMouseEvent = (frame.contentWindow as unknown as typeof globalThis).MouseEvent
    target.dispatchEvent(new FrameMouseEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0 }))
  }

  async function openAnnotatableDeck() {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve(annotatableDeckHtml),
    }))
    render(<WorkspaceDocumentPreview sessionId="session-a" file={deck} />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const frame = hydrateFrame(annotatableDeckHtml)
    const doc = frame.contentDocument as Document
    const slide = doc.querySelector('.slide') as HTMLElement
    const chart = doc.querySelector('[data-shape-id="12"]') as HTMLElement
    const logo = doc.querySelector('[data-shape-id="2"]') as HTMLElement
    slide.getBoundingClientRect = () => new DOMRect(0, 0, 800, 450)
    chart.getBoundingClientRect = () => new DOMRect(80, 90, 400, 180)
    logo.getBoundingClientRect = () => new DOMRect(700, 10, 80, 40)
    fireEvent.click(await screen.findByRole('button', { name: 'Select an area to edit' }))
    return { frame, slide, chart }
  }

  beforeEach(async () => {
    const { useDocumentAnnotationsStore } = await import('@/stores/useDocumentAnnotationsStore')
    useDocumentAnnotationsStore.setState({ pending: {}, submitRequest: null })
    checkpoint.mockClear()
  })

  it('selects a clicked shape and adds it to the batch with its instruction', async () => {
    const { useDocumentAnnotationsStore } = await import('@/stores/useDocumentAnnotationsStore')
    const { frame, chart } = await openAnnotatableDeck()

    pointer(frame, 'pointerdown', chart, 100, 100)
    pointer(frame, 'pointerup', chart, 100, 100)

    const popover = await screen.findByTestId('annotation-popover')
    expect(popover).toHaveTextContent('Slide 1 · Chart 3')
    fireEvent.change(within(popover).getByLabelText('Instruction for the selection'), {
      target: { value: 'Keep the colors in a unified tone.' },
    })
    fireEvent.click(within(popover).getByRole('button', { name: 'Add annotation to batch' }))

    const [annotation] = useDocumentAnnotationsStore.getState().pending['session-a']
    expect(annotation).toMatchObject({
      file: 'deck.pptx',
      slide: 1,
      shapes: [{ id: 12, name: 'Chart 3' }],
      area: { x: 10, y: 20, w: 50, h: 40 },
      text: 'Quarterly P&L',
      instruction: 'Keep the colors in a unified tone.',
    })
    expect(checkpoint).toHaveBeenCalledWith('session-a', 'deck.pptx', {
      action: 'checkpoint',
      label: 'Keep the colors in a unified tone.',
    })
    expect(useDocumentAnnotationsStore.getState().submitRequest).toBeNull()
    // The batched selection stays pinned on the slide with its number.
    expect(frame.contentDocument?.querySelector('[data-evoflux-anno="pin"]')).toHaveAttribute('data-n', '1')
  })

  it('selects a dragged area, skips master shapes, and sends at once', async () => {
    const { useDocumentAnnotationsStore } = await import('@/stores/useDocumentAnnotationsStore')
    const { frame, slide } = await openAnnotatableDeck()

    pointer(frame, 'pointerdown', slide, 0, 0)
    pointer(frame, 'pointermove', slide, 800, 450)
    pointer(frame, 'pointerup', slide, 800, 450)

    const popover = await screen.findByTestId('annotation-popover')
    fireEvent.click(within(popover).getByRole('button', { name: 'Send annotation now' }))

    const state = useDocumentAnnotationsStore.getState()
    expect(state.pending['session-a'][0].shapes).toEqual([{ id: 12, name: 'Chart 3' }])
    expect(state.pending['session-a'][0].area).toEqual({ x: 0, y: 0, w: 100, h: 100 })
    expect(state.submitRequest).toMatchObject({ sessionId: 'session-a' })
    expect(screen.queryByTestId('annotation-popover')).not.toBeInTheDocument()
  })

  it('offers no annotation or history controls outside a session workspace', async () => {
    render(<WorkspaceDocumentPreview workspace="C:/repo" file={deck} />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Select an area to edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Document versions' })).not.toBeInTheDocument()
  })
})
