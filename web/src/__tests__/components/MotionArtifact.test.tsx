import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { VisualArtifactPayload } from '@/api/types'

const motionMocks = vi.hoisted(() => ({
  exportFrames: vi.fn(),
  postMotionReviewSamples: vi.fn(),
  frameHandler: undefined as ((message: { type: 'rendered_frame'; requestId: number; currentTimeMs: number; bitmap: ImageBitmap }) => void) | undefined,
  port: {
    postMessage: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  },
}))

vi.mock('@/lib/visual-artifact-export', () => ({
  canRenderMotionFrames: () => true,
  getSupportedExportMimeType: () => 'video/webm',
}))
vi.mock('@/components/ui/select', () => ({ SelectControl: () => <div /> }))
vi.mock('@/api/client/team', () => ({ postMotionReviewSamples: motionMocks.postMotionReviewSamples }))
vi.mock('@/components/VisualArtifactFrame', async () => {
  const React = await import('react')
  return {
    VisualArtifactFrame: ({ onPort, onReady, onFrame }: {
      onPort?: (port: MessagePort | null) => void
      onReady?: (message: { motionCanvas: boolean; frameRenderer: boolean; canvasWidth: number; canvasHeight: number }) => void
      onFrame?: (message: { type: 'rendered_frame'; requestId: number; currentTimeMs: number; bitmap: ImageBitmap }) => void
    }) => {
      React.useEffect(() => {
        motionMocks.frameHandler = onFrame
        onPort?.(motionMocks.port as unknown as MessagePort)
        onReady?.({ motionCanvas: true, frameRenderer: true, canvasWidth: 640, canvasHeight: 360 })
      }, [onFrame, onPort, onReady])
      return <div data-testid="mock-motion-frame" />
    },
  }
})
vi.mock('@/lib/motion-video-export', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/motion-video-export')>()
  return { ...actual, exportMotionFrames: (options: unknown) => motionMocks.exportFrames(options) }
})

import { MotionArtifact } from '@/components/visual-artifact/MotionArtifact'

const artifact: VisualArtifactPayload = {
  artifactId: 'motion-active-test', kind: 'motion', title: 'Motion test', summary: 'A short explainer',
  sourceHtml: '<canvas data-evoflux-motion-canvas></canvas>', scene: null, sources: [], durationMs: 1_000, revision: 1,
}
let originalCreateObjectUrl: PropertyDescriptor | undefined

describe('MotionArtifact', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: vi.fn() } as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((callback) => callback(new Blob(['preview'], { type: 'image/jpeg' })))
    motionMocks.port.postMessage.mockImplementation((rawMessage: unknown) => {
      const message = rawMessage as { command?: { type?: string; requestId?: number; currentTimeMs?: number } }
      if (message.command?.type === 'render_frame' && message.command.requestId !== undefined) {
        motionMocks.frameHandler?.({
          type: 'rendered_frame',
          requestId: message.command.requestId,
          currentTimeMs: message.command.currentTimeMs ?? 0,
          bitmap: { width: 640, height: 360, close: vi.fn() } as unknown as ImageBitmap,
        })
      }
    })
  })

  afterEach(() => {
    if (originalCreateObjectUrl) Object.defineProperty(URL, 'createObjectURL', originalCreateObjectUrl)
    else Reflect.deleteProperty(URL, 'createObjectURL')
    originalCreateObjectUrl = undefined
  })

  it('cancels deterministic rendering when its Workbench tab becomes hidden', async () => {
    originalCreateObjectUrl = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:previous-video') })
    motionMocks.exportFrames.mockResolvedValueOnce({ blob: new Blob(['video']), extension: 'mp4', frameCount: 30 })
    const { rerender } = render(<MotionArtifact artifact={artifact} theme="dark" reducedMotion={false} active />)
    const renderButton = await screen.findByRole('button', { name: 'Render video' })
    await waitFor(() => expect(renderButton).toBeEnabled())
    fireEvent.click(renderButton)
    expect(await screen.findByLabelText('Motion test rendered video')).toHaveAttribute('src', 'blob:previous-video')

    let cancellationCheck: (() => boolean) | undefined
    motionMocks.exportFrames.mockImplementation((rawOptions: unknown) => {
      const options = rawOptions as { isCancelled: () => boolean }
      cancellationCheck = options.isCancelled
      return new Promise((_resolve, reject) => {
        const timer = window.setInterval(() => {
          if (!options.isCancelled()) return
          window.clearInterval(timer)
          reject(new DOMException('Video export cancelled.', 'AbortError'))
        }, 5)
      })
    })

    fireEvent.click(screen.getByRole('button', { name: 'Render video' }))
    await waitFor(() => expect(motionMocks.exportFrames).toHaveBeenCalledTimes(2))

    rerender(<MotionArtifact artifact={artifact} theme="dark" reducedMotion={false} active={false} />)

    expect(await screen.findByText('Video export cancelled.')).toBeVisible()
    expect(cancellationCheck?.()).toBe(true)
    expect(screen.getByLabelText('Motion test rendered video')).toHaveAttribute('src', 'blob:previous-video')
  })

  it('requests the exact next frame through the isolated renderer bridge', async () => {
    render(<MotionArtifact artifact={artifact} theme="dark" reducedMotion={false} active />)
    fireEvent.click(await screen.findByRole('button', { name: 'Next frame' }))

    await waitFor(() => expect(motionMocks.port.postMessage).toHaveBeenCalledWith({
      type: 'command',
      command: { type: 'render_frame', requestId: 1_000_000_000, currentTimeMs: 1000 / 30 },
    }))
  })

  it('renders and posts only the requested bounded frame sample', async () => {
    originalCreateObjectUrl = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:review-frame') })
    motionMocks.postMotionReviewSamples.mockResolvedValue(undefined)
    const reviewArtifact = { ...artifact, artifactId: 'motion-agent-review-test' }
    const reviewRequest = {
      id: 'motion-job:request-1',
      jobId: `motion-${'a'.repeat(32)}`,
      sampleRequestId: 'request-1',
      samples: [{ sampleId: 'impact', beatId: 'intake', frameIndex: 10, timestampMs: 333, role: 'impact' as const }],
    }
    render(<MotionArtifact
      artifact={reviewArtifact}
      theme="dark"
      reducedMotion={false}
      active
      sessionId="session-review"
      motionSampleReviewRequest={reviewRequest}
    />)

    await waitFor(() => expect(motionMocks.postMotionReviewSamples).toHaveBeenCalledTimes(1))
    expect(motionMocks.port.postMessage).toHaveBeenCalledWith({
      type: 'command',
      command: { type: 'render_frame', requestId: 1_000_000_000, currentTimeMs: 333 },
    })
    expect(motionMocks.postMotionReviewSamples).toHaveBeenCalledWith('session-review', reviewRequest.jobId, expect.objectContaining({
      sampleRequestId: 'request-1',
      artifactId: 'motion-agent-review-test',
      artifactRevision: 1,
      samples: [expect.objectContaining({ sampleId: 'impact', frameIndex: 10, timestampMs: 333, mimeType: 'image/jpeg' })],
    }))
  })
})
