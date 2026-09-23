import { describe, expect, it } from 'vitest'

import {
  annotateRenderedDocx,
  DOCUMENT_PREVIEW_CSP,
  neutralizeRenderedDocx,
  repairRenderedVml,
} from '@/lib/docx-preview-render'

function fragment(markup: string): HTMLDivElement {
  const root = document.createElement('div')
  root.innerHTML = markup
  return root
}

describe('docx-preview-render', () => {
  it('mirrors the backend preview CSP', () => {
    expect(DOCUMENT_PREVIEW_CSP).toContain("script-src 'none'")
    expect(DOCUMENT_PREVIEW_CSP).toContain("connect-src 'none'")
    expect(DOCUMENT_PREVIEW_CSP).toContain('img-src data: blob:')
  })

  it('removes active content, handlers and remote references', () => {
    const root = fragment(`
      <section class="docx">
        <script>alert(1)</script>
        <iframe src="https://example.com"></iframe>
        <p onclick="steal()">Hello <a href="https://example.com/x">link</a> <a href="#_Toc1">toc</a></p>
        <img src="https://tracker.example/p.png"><img src="data:image/png;base64,AAAA">
      </section>`)

    neutralizeRenderedDocx(root)

    expect(root.querySelector('script, iframe')).toBeNull()
    expect(root.querySelector('p')?.hasAttribute('onclick')).toBe(false)
    const [external, internal] = Array.from(root.querySelectorAll('a'))
    expect(external.hasAttribute('href')).toBe(false)
    expect(external.getAttribute('data-href')).toBe('https://example.com/x')
    expect(internal.hasAttribute('href')).toBe(false)
    expect(internal.hasAttribute('data-href')).toBe(false)
    const [remote, inline] = Array.from(root.querySelectorAll('img'))
    expect(remote.hasAttribute('src')).toBe(false)
    expect(inline.getAttribute('src')).toBe('data:image/png;base64,AAAA')
  })

  it('keeps inline image data on SVG images but never on links', () => {
    const root = fragment(`
      <svg><image href="data:image/png;base64,AAAA"></image><image href="https://tracker.example/p.png"></image></svg>
      <a href="data:text/html,<b>x</b>">data link</a>`)

    neutralizeRenderedDocx(root)

    const [inline, remote] = Array.from(root.querySelectorAll('image'))
    expect(inline.getAttribute('href')).toBe('data:image/png;base64,AAAA')
    expect(remote.hasAttribute('href')).toBe(false)
    expect(remote.getAttribute('data-href')).toBe('https://tracker.example/p.png')
    expect(root.querySelector('a')?.hasAttribute('href')).toBe(false)
  })

  it('repairs VML fallback shapes so their paint and text are visible', () => {
    const root = fragment(`
      <svg><rect width="100%" fill="#156082 [3204]"><foreignObject><p>Boxed</p></foreignObject></rect></svg>
      <svg><ellipse fill="white [3201]" stroke="null" stroke-width="1px"></ellipse></svg>
      <svg><g><foreignObject><p>Kept</p></foreignObject></g></svg>`)

    repairRenderedVml(root)

    const [rectSvg, ellipseSvg, groupSvg] = Array.from(root.querySelectorAll('svg'))
    expect(rectSvg.querySelector('rect')?.getAttribute('fill')).toBe('#156082')
    expect(rectSvg.querySelector('rect foreignObject')).toBeNull()
    expect(rectSvg.querySelector(':scope > foreignObject')?.textContent).toBe('Boxed')
    const ellipse = ellipseSvg.querySelector('ellipse')
    expect(ellipse?.getAttribute('fill')).toBe('white')
    expect(ellipse?.hasAttribute('stroke')).toBe(false)
    expect(ellipse?.hasAttribute('stroke-width')).toBe(false)
    expect(groupSvg.querySelector('g > foreignObject')?.textContent).toBe('Kept')
  })

  it('tags each rendered page and paragraph with viewer anchors', () => {
    const root = fragment(`
      <div class="docx-wrapper">
        <section class="docx"><article><p>First   page intro</p><table></table></article></section>
        <section class="docx"><article><p></p><p>Second page</p></article></section>
      </div>`)

    expect(annotateRenderedDocx(root)).toBe(2)

    const pages = root.querySelectorAll<HTMLElement>('[data-preview-item]')
    expect(Array.from(pages, (page) => page.dataset.previewLabel)).toEqual(['Page 1', 'Page 2'])
    const labels = Array.from(root.querySelectorAll<HTMLElement>('p[data-qa-label]'), (p) => p.dataset.qaLabel)
    expect(labels).toEqual(['First page intro', 'Second page'])
    expect(root.querySelector('table')?.dataset.qaLabel).toBe('Table 1')
  })
})
