import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { workPreviewUrl, codingPreviewUrl } = vi.hoisted(() => ({
  workPreviewUrl: vi.fn((sessionId: string, path: string) => `/work/${sessionId}/${path}`),
  codingPreviewUrl: vi.fn((workspace: string, path: string) => `/coding/${workspace}/${path}`),
}))

vi.mock('@/api/client', () => ({
  workspaceDocumentPreviewUrl: workPreviewUrl,
  codingWorkspaceDocumentPreviewUrl: codingPreviewUrl,
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
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    text: () => Promise.resolve(workbookHtml),
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
    },
  ])('reveals the hidden $name containing a search result', async ({ file, html, query, activeControl }) => {
    render(<WorkspaceDocumentPreview sessionId="session-1" file={file} />)

    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const frame = hydrateFrame(html)
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

  it('navigates PowerPoint slides with arrows, Home, End, and Space', async () => {
    render(
      <WorkspaceDocumentPreview
        sessionId="session-1"
        file={{ path: 'roadmap.pptx', name: 'roadmap.pptx', mime: '', size: 10, mtime: 2 }}
      />,
    )

    await waitFor(() => expect(fetch).toHaveBeenCalled())
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
