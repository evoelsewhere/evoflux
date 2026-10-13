/**
 * REAL mermaid render verification (no mocks).
 *
 * Runs mermaid.render with the exact configuration MermaidFence uses —
 * `securityLevel: 'strict'`, `startOnLoad: false`, theme chosen the same
 * way — against the demo flowchart and a realistic model-generated
 * diagram, asserting SVG output. Also exercises the hardened failure
 * path: a failed render must not leave mermaid's temp DOM nodes behind
 * and must not poison a later retry.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import mermaid from 'mermaid'
import { cleanupMermaidTempNodes } from '@/components/markdown/mermaidTempNodes'

// jsdom has no SVG layout engine; mermaid measures nodes with getBBox /
// getComputedTextLength during layout. Stub them with plausible sizes —
// this does not mock mermaid itself, only the browser APIs it measures with.
// Node.prototype (not SVGElement/Element) because mermaid's label measuring
// calls .getBBox() on whatever d3 `.node()` returns, including text nodes
// produced by DOMPurify-sanitized labels.
beforeAll(() => {
  const nodeProto = Node.prototype as unknown as {
    getBBox?: () => { x: number; y: number; width: number; height: number }
    getComputedTextLength?: () => number
  }
  if (!nodeProto.getBBox) {
    nodeProto.getBBox = () => ({ x: 0, y: 0, width: 120, height: 20 })
  }
  if (!nodeProto.getComputedTextLength) {
    nodeProto.getComputedTextLength = () => 60
  }
  // MermaidFence reads the OS theme via matchMedia; jsdom lacks it.
  if (!window.matchMedia) {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as typeof window.matchMedia
  }
})

// Mirror MermaidFence's configuration (getMermaid).
mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'default' })

let renderCounter = 0
const nextId = () => `evoflux-mermaid-test-${++renderCounter}`

describe('real mermaid.render (as MermaidFence configures it)', () => {
  it('renders the demo flowchart to SVG', async () => {
    const { svg } = await mermaid.render(nextId(), 'flowchart LR\n  A[Build] --> B[Test]\n  B --> C[Release]')
    expect(svg).toContain('<svg')
    expect(svg).toContain('Build')
    expect(svg).toContain('Release')
  })

  it('renders a realistic model-generated diagram to SVG', async () => {
    // A sequence diagram of the kind an EvoFlux agent actually emits when
    // explaining a request lifecycle.
    const diagram = [
      'sequenceDiagram',
      '  participant U as User',
      '  participant A as Agent',
      '  participant T as Tools',
      '  U->>A: Send prompt with attachment',
      '  A->>T: read(active_file)',
      '  T-->>A: file contents',
      '  A-->>U: Stream answer with ui_block',
    ].join('\n')
    const { svg } = await mermaid.render(nextId(), diagram)
    expect(svg).toContain('<svg')
    expect(svg).toContain('Send prompt with attachment')
    expect(svg).toContain('ui_block')
  })

  it('renders the dark theme too (theme switch path)', async () => {
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'dark' })
    try {
      const { svg } = await mermaid.render(nextId(), 'flowchart TD\n  X[Start] --> Y[End]')
      expect(svg).toContain('<svg')
    } finally {
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'default' })
    }
  })

  it('a failed render leaves no temp DOM nodes and a retry succeeds (hardened fence)', async () => {
    const before = document.body.innerHTML
    const badId = nextId()
    await expect(
      mermaid.render(badId, 'flowchart LR\n  A[Start --> B[Broken'),
    ).rejects.toThrow()
    // The hardened fence sweeps mermaid's temp container after failure.
    cleanupMermaidTempNodes(badId)
    expect(document.getElementById(`d${badId}`)).toBeNull()
    expect(document.getElementById(badId)).toBeNull()

    // …and the runtime is not poisoned: a later retry renders fine.
    const { svg } = await mermaid.render(nextId(), 'flowchart LR\n  A[Build] --> B[Test]')
    expect(svg).toContain('<svg')
    expect(document.body.innerHTML).toBe(before)
  })

  it('script injection stays inert under securityLevel strict', async () => {
    // DOMPurify strips hostile markup entirely — neither the tag nor the
    // payload text survives into the SVG. (An `<img onerror>` label hangs
    // jsdom's HTML-label image measurement; that is a jsdom limitation,
    // not a mermaid one — the browser path resolves the image load.)
    const script = await mermaid.render(
      nextId(),
      'flowchart LR\n  A["<script>alert(1)</script>"] --> B[Safe]',
    )
    expect(script.svg).toContain('<svg')
    expect(script.svg).not.toContain('<script')
    expect(script.svg).not.toContain('alert')

    const iframe = await mermaid.render(
      nextId(),
      'flowchart LR\n  A["<iframe src=javascript:alert(1)>"] --> B[Safe]',
    )
    expect(iframe.svg).toContain('<svg')
    expect(iframe.svg).not.toContain('<iframe')
    expect(iframe.svg).not.toMatch(/href="javascript/)
  })
})
