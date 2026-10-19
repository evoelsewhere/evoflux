import { describe, expect, it } from 'vitest'
import { buildVisualArtifactSrcDoc } from '@/components/VisualArtifactFrame'

describe('VisualArtifactFrame bootstrap', () => {
  it('installs the artifact API before generated inline scripts execute', () => {
    const sourceHtml = '<script id="generated-motion">window.evofluxArtifact.registerFrameRenderer(() => {})</script>'
    const srcDoc = buildVisualArtifactSrcDoc(sourceHtml)

    expect(srcDoc.indexOf("Object.defineProperty(window,'evofluxArtifact'")).toBeLessThan(
      srcDoc.indexOf('id="generated-motion"'),
    )
  })

  it('lets generated scripts register frame and playback handlers in an isolated frame', () => {
    const sourceHtml = `<script>
      window.evofluxArtifact.registerFrameRenderer(() => {})
      window.evofluxArtifact.onCommand((command) => { window.__lastCommand = command })
      window.__artifactRuntimeReady = true
    </script>`
    const srcDoc = buildVisualArtifactSrcDoc(sourceHtml)
    const parsed = new DOMParser().parseFromString(srcDoc, 'text/html')
    const frame = document.createElement('iframe')
    document.body.append(frame)

    try {
      const frameWindow = frame.contentWindow
      if (!frameWindow) throw new Error('iframe window is unavailable')
      const isolatedFrame = frameWindow as Window & {
        eval: (source: string) => unknown
        MessageEvent: typeof MessageEvent
      }
      parsed.querySelectorAll('script').forEach((script) => {
        isolatedFrame.eval(script.textContent ?? '')
      })

      expect((frameWindow as unknown as { __artifactRuntimeReady?: boolean }).__artifactRuntimeReady).toBe(true)

      const outgoing: unknown[] = []
      const port = {
        onmessage: null as ((event: MessageEvent<unknown>) => void) | null,
        postMessage: (message: unknown) => outgoing.push(message),
        start: () => {},
      }
      Object.defineProperty(frameWindow, 'ResizeObserver', {
        configurable: true,
        value: class { observe() {} },
      })
      frameWindow.dispatchEvent(new isolatedFrame.MessageEvent('message', {
        data: { type: 'evoflux-artifact-init' },
        source: frameWindow.parent,
        ports: [port as unknown as MessagePort],
      }))
      port.onmessage?.({ data: { type: 'command', command: 'restart' } } as MessageEvent<unknown>)

      expect(outgoing).toContainEqual(expect.objectContaining({ type: 'ready', frameRenderer: true }))
      expect((frameWindow as unknown as { __lastCommand?: string }).__lastCommand).toBe('restart')

      const beats = [{ id: 'beat-1', title: 'First beat', startFrame: 0, endFrame: 29, markers: [{ frame: 12, kind: 'hit' }] }]
      const artifactApi = (frameWindow as unknown as {
        evofluxArtifact: { registerTimeline: (value: unknown) => boolean }
      }).evofluxArtifact
      expect(artifactApi.registerTimeline(beats)).toBe(true)
      expect(artifactApi.registerTimeline([{ ...beats[0], id: 'bad id' }])).toBe(false)
      expect(outgoing).toContainEqual({ type: 'timeline', beats })
    } finally {
      frame.remove()
    }
  })
})
