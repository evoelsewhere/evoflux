import { act, createElement } from 'react'
import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ArtifactSlideRenderBridge } from '@/components/artifacts/ArtifactSlideRenderBridge'
import {
  collectEditableElements,
  type RenderRequest,
} from '@/components/artifacts/slide-editable'

const renderer = vi.hoisted(() => ({
  renderHtmlSlide: vi.fn(),
}))

vi.mock('@/components/artifacts/html-slide-renderer', () => ({
  renderHtmlSlide: renderer.renderHtmlSlide,
}))

vi.mock('@/api/base-url', () => ({
  apiUrl: (path: string) => path,
}))

vi.mock('@/stores/useTeamStore', () => ({
  useTeamStore: (selector: (state: { sessionId: string }) => unknown) => (
    selector({ sessionId: 'session-1' })
  ),
}))

function request(): RenderRequest {
  return {
    request_id: 'request-1',
    slide_id: 'opening',
    width: 1280,
    height: 720,
    html: '',
    css: '',
    assets: {
      hero: { mime_type: 'image/png', suffix: '.png' },
    },
  }
}

function slideRoot(markup: string): HTMLElement {
  document.head.innerHTML = `<style>
    [data-slide-root], [data-slide-root] * {
      color: rgb(17, 24, 39);
      direction: ltr;
      font-family: Arial;
      font-size: 32px;
      font-style: normal;
      font-weight: 400;
      letter-spacing: 0px;
      line-height: 38.4px;
      mix-blend-mode: normal;
      opacity: 1;
      text-decoration-line: none;
      text-transform: none;
      visibility: visible;
      writing-mode: horizontal-tb;
    }
  </style>`
  const root = document.createElement('section')
  root.dataset.slideRoot = ''
  root.innerHTML = markup
  document.body.append(root)
  root.getBoundingClientRect = () => new DOMRect(0, 0, 1280, 720)
  Array.from(root.querySelectorAll<HTMLElement>('[data-box]')).forEach((node, index) => {
    const x = Number(node.dataset.x ?? 80)
    const y = Number(node.dataset.y ?? 60 + index * 100)
    const width = Number(node.dataset.width ?? 720)
    const height = Number(node.dataset.height ?? 72)
    node.getBoundingClientRect = () => new DOMRect(x, y, width, height)
  })
  return root
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document.head.innerHTML = ''
})

describe('HTML slide editable text extraction', () => {
  it('extracts ordinary semantic text and safe rich runs without an opt-in annotation', () => {
    const root = slideRoot(`
      <h1 id="decision-title" data-box style="padding: 4px 8px">
        A <strong style="font-weight: 700; color: rgb(37, 99, 235)">bold</strong> claim
      </h1>
      <p data-pptx-name="Evidence" data-box>Ordinary body copy</p>
    `)

    const result = collectEditableElements(root, request())
    const title = result.elements.find((element) => element.name === 'decision-title')

    expect(result.issues).toEqual([])
    expect(title).toMatchObject({
      kind: 'text',
      role: 'heading-1',
      padding: { left: 8, right: 8, top: 4, bottom: 4 },
      paragraphs: [{
        runs: [
          { text: 'A ', bold: false, color: '#111827' },
          { text: 'bold', bold: true, color: '#2563EB' },
          { text: ' claim', bold: false, color: '#111827' },
        ],
      }],
    })
    expect(result.elements.map((element) => element.name)).toEqual([
      'decision-title',
      'Evidence',
    ])
    expect(result.hidden).toEqual([
      root.querySelector('#decision-title'),
      root.querySelector('[data-pptx-name="Evidence"]'),
    ])
    expect(result.text_coverage).toEqual({
      visible_blocks: 2,
      visible_characters: 30,
      native_blocks: 2,
      native_characters: 30,
      flattened: [],
    })
  })

  it('preserves CSS tracking as editable run letter spacing', () => {
    const root = slideRoot(`
      <p data-box style="letter-spacing: 1.5px">Tracked label</p>
    `)

    const result = collectEditableElements(root, request())

    expect(result.issues).toEqual([])
    expect(result.elements[0]?.paragraphs?.[0]?.runs).toEqual([
      expect.objectContaining({ text: 'Tracked label', letter_spacing: 1.5 }),
    ])
    expect(result.text_coverage.flattened).toEqual([])
  })

  it('normalizes CSS font stacks to a PowerPoint typeface name', () => {
    const root = slideRoot(`
      <p data-box style='font-family: Arial, "Helvetica Neue", sans-serif'>Vietnamese copy</p>
    `)

    const result = collectEditableElements(root, request())

    expect(result.elements[0]?.paragraphs?.[0]?.runs).toEqual([
      expect.objectContaining({ text: 'Vietnamese copy', font_family: 'Arial' }),
    ])
  })

  it('keeps art text flattened while preserving lists and explicit legacy editability', () => {
    const root = slideRoot(`
      <ul>
        <li data-box style="list-style-type: square">Ship <em style="font-style: italic">now</em></li>
      </ul>
      <p data-box data-pptx-name="Chart label" data-pptx-text-mode="art">42%</p>
      <div data-box data-pptx-editable="text" data-pptx-name="Legacy text">Still editable</div>
      <img data-box data-pptx-editable="image" data-pptx-asset="hero" alt="Hero">
    `)

    const result = collectEditableElements(root, request())
    const listItem = result.elements.find((element) => element.role === 'list-item')

    expect(listItem?.paragraphs).toMatchObject([{
      level: 0,
      bullet: { kind: 'bullet', marker: '▪', level: 0 },
      runs: [
        { text: 'Ship ', italic: false },
        { text: 'now', italic: true },
      ],
    }])
    expect(result.elements).toEqual(expect.arrayContaining([
      expect.objectContaining({ kind: 'text', name: 'Legacy text', text: 'Still editable' }),
      expect.objectContaining({ kind: 'image', asset_id: 'hero', alt: 'Hero' }),
    ]))
    expect(result.text_coverage).toEqual({
      visible_blocks: 3,
      visible_characters: 25,
      native_blocks: 2,
      native_characters: 22,
      flattened: [{ name: 'Chart label', reason: 'explicit-art-mode', characters: 3 }],
    })
    expect(result.hidden).not.toContain(root.querySelector('[data-pptx-text-mode="art"]'))
  })

  it('preserves the effective ordinal for each editable ordered-list item', () => {
    const root = slideRoot(`
      <ol start="4">
        <li data-box>Fourth</li>
        <li data-box value="9">Ninth</li>
        <li data-box>Tenth</li>
      </ol>
    `)

    const result = collectEditableElements(root, request())

    expect(result.elements.map((element) => element.paragraphs?.[0]?.bullet)).toEqual([
      { kind: 'number', level: 0, start: 4 },
      { kind: 'number', level: 0, start: 9 },
      { kind: 'number', level: 0, start: 10 },
    ])
  })

  it('accounts for visible SVG text as shell-only text', () => {
    const root = slideRoot(`
      <svg aria-label="Chart">
        <text data-box data-pptx-name="Axis label">Revenue</text>
      </svg>
    `)

    const result = collectEditableElements(root, request())

    expect(result.elements).toEqual([])
    expect(result.hidden).toEqual([])
    expect(result.text_coverage).toEqual({
      visible_blocks: 1,
      visible_characters: 7,
      native_blocks: 0,
      native_characters: 0,
      flattened: [{ name: 'Axis label', reason: 'svg-text', characters: 7 }],
    })
  })

  it('ledgers direct slide-root text without creating a full-slide textbox', () => {
    const root = slideRoot(`Loose root copy<h2 data-box>Semantic heading</h2>`)

    const result = collectEditableElements(root, request())

    expect(result.elements).toEqual([
      expect.objectContaining({ role: 'heading-2', text: 'Semantic heading' }),
    ])
    expect(result.text_coverage).toEqual({
      visible_blocks: 2,
      visible_characters: 31,
      native_blocks: 1,
      native_characters: 16,
      flattened: [{ name: 'root-text-1', reason: 'unstructured-root-text', characters: 15 }],
    })
  })

  it('keeps foreground-occluded text flattened to preserve shell stacking', () => {
    const root = slideRoot(`
      <p id="covered-copy" data-box>Covered</p>
      <div id="cover" data-box aria-hidden="true"></div>
    `)
    const copy = root.querySelector<HTMLElement>('#covered-copy')!
    const cover = root.querySelector<HTMLElement>('#cover')!
    const original = document.elementsFromPoint
    Object.defineProperty(document, 'elementsFromPoint', {
      configurable: true,
      value: vi.fn(() => [cover, copy, root]),
    })

    try {
      const result = collectEditableElements(root, request())

      expect(result.elements).toEqual([])
      expect(result.hidden).toEqual([])
      expect(result.text_coverage).toEqual({
        visible_blocks: 1,
        visible_characters: 7,
        native_blocks: 0,
        native_characters: 0,
        flattened: [{ name: 'covered-copy', reason: 'foreground-occlusion', characters: 7 }],
      })
    } finally {
      if (original) {
        Object.defineProperty(document, 'elementsFromPoint', { configurable: true, value: original })
      } else {
        Reflect.deleteProperty(document, 'elementsFromPoint')
      }
    }
  })

  it('flattens text with embedded graphics atomically', () => {
    const root = slideRoot(`
      <p id="metric" data-box>Growth <svg aria-label="Trend icon"><path d="M0 1 L1 0"></path></svg></p>
    `)

    const result = collectEditableElements(root, request())

    expect(result.elements).toEqual([])
    expect(result.hidden).toEqual([])
    expect(result.text_coverage).toEqual({
      visible_blocks: 1,
      visible_characters: 6,
      native_blocks: 0,
      native_characters: 0,
      flattened: [{ name: 'metric', reason: 'embedded-graphic', characters: 6 }],
    })
  })

  it('accounts for generic leaf text without selecting the slide root or semantic parents twice', () => {
    const root = slideRoot(`
      <section data-box>
        <h2 data-box>Semantic heading</h2>
      </section>
      <div id="generic-copy" data-box>Direct generic copy</div>
      <article data-box><div data-box>Nested generic copy</div></article>
    `)

    const result = collectEditableElements(root, request())

    expect(result.elements.map((element) => element.name)).toEqual([
      'heading-2-1',
      'generic-copy',
      'text-2',
    ])
    expect(result.elements.map((element) => element.text)).toEqual([
      'Semantic heading',
      'Direct generic copy',
      'Nested generic copy',
    ])
    expect(result.elements).not.toContainEqual(expect.objectContaining({
      text: expect.stringContaining('Semantic headingDirect generic copy'),
    }))
    expect(result.text_coverage).toEqual({
      visible_blocks: 3,
      visible_characters: 54,
      native_blocks: 3,
      native_characters: 54,
      flattened: [],
    })
  })
})

describe('ArtifactSlideRenderBridge', () => {
  beforeEach(() => {
    renderer.renderHtmlSlide.mockReset().mockResolvedValue({
      preview_png_base64: 'preview',
      shell_png_base64: 'shell',
      editable_elements: [],
      text_coverage: {
        visible_blocks: 1,
        visible_characters: 12,
        native_blocks: 1,
        native_characters: 12,
        flattened: [],
      },
      issues: [],
    })
  })

  it('posts the extended editable manifest and text coverage unchanged', async () => {
    const completedBodies: unknown[] = []
    let claimed = false
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      if (url.endsWith('/heartbeat')) return { ok: true, status: 204 } as Response
      if (url.endsWith('/next') && !claimed) {
        claimed = true
        return { ok: true, status: 200, json: async () => request() } as Response
      }
      if (url.endsWith('/complete')) {
        completedBodies.push(JSON.parse(String(init?.body)))
        return { ok: true, status: 204 } as Response
      }
      return { ok: true, status: 204 } as Response
    }))

    const view = render(createElement(ArtifactSlideRenderBridge))

    await waitFor(() => expect(completedBodies).toHaveLength(1))
    expect(renderer.renderHtmlSlide).toHaveBeenCalledWith(request())
    expect(completedBodies[0]).toMatchObject({
      editable_elements: [],
      text_coverage: {
        visible_blocks: 1,
        visible_characters: 12,
        native_blocks: 1,
        native_characters: 12,
        flattened: [],
      },
    })
    view.unmount()
  })

  it('keeps an application-level heartbeat alive while a slide is rendering', async () => {
    vi.useFakeTimers()
    let finishRender: ((value: Awaited<ReturnType<typeof renderer.renderHtmlSlide>>) => void) | undefined
    renderer.renderHtmlSlide.mockReturnValue(new Promise((resolve) => {
      finishRender = resolve
    }))
    const urls: string[] = []
    let claimed = false
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      urls.push(url)
      if (url.endsWith('/heartbeat')) return { ok: true, status: 204 } as Response
      if (url.endsWith('/next') && !claimed) {
        claimed = true
        return { ok: true, status: 200, json: async () => request() } as Response
      }
      return { ok: true, status: 204 } as Response
    }))

    const view = render(createElement(ArtifactSlideRenderBridge))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })

    expect(renderer.renderHtmlSlide).toHaveBeenCalledOnce()
    expect(urls.filter((url) => url.endsWith('/heartbeat'))).toHaveLength(1)
    expect(urls.some((url) => url.includes('/artifacts/renderers/global/'))).toBe(true)

    await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
    expect(urls.filter((url) => url.endsWith('/heartbeat'))).toHaveLength(2)

    finishRender?.({
      preview_png_base64: 'preview',
      shell_png_base64: 'shell',
      editable_elements: [],
      text_coverage: {
        visible_blocks: 0,
        visible_characters: 0,
        native_blocks: 0,
        native_characters: 0,
        flattened: [],
      },
      issues: [],
    })
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    view.unmount()
  })
})
