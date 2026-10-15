import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useEffect, useRef } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { VisualArtifactPayload } from '@/api/types'
import { MotionArtifact } from '@/components/visual-artifact/MotionArtifact'

const postMessage = vi.fn()
const playbackSimulation = vi.hoisted(() => ({ enabled: false }))
const frameRendererSimulation = vi.hoisted(() => ({ enabled: false }))
const exportMotionFrames = vi.hoisted(() => vi.fn())
const port = {
  postMessage,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
} as unknown as MessagePort

vi.mock('@/lib/motion-video-export', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/lib/motion-video-export')>(),
  exportMotionFrames,
}))

vi.mock('@/components/VisualArtifactFrame', () => ({
  VisualArtifactFrame: ({ onPort, onReady, onPlayback }: {
    onPort: (port: MessagePort | null) => void
    onReady: (message: { type: 'ready'; motionCanvas: boolean; frameRenderer?: boolean; canvasWidth?: number; canvasHeight?: number }) => void
    onPlayback: (message: { state: 'playing' | 'paused' | 'ended'; currentTimeMs: number }) => void
  }) => {
    const didSimulate = useRef(false)
    useEffect(() => {
      onPort(port)
      onReady({ type: 'ready', motionCanvas: frameRendererSimulation.enabled, frameRenderer: frameRendererSimulation.enabled, canvasWidth: 960, canvasHeight: 540 })
      if (playbackSimulation.enabled && !didSimulate.current) {
        didSimulate.current = true
        onPlayback({ state: 'playing', currentTimeMs: 100 })
      }
      return () => onPort(null)
    }, [onPort, onReady, onPlayback])
    return <div title="Motion frame" />
  },
}))

const artifact: VisualArtifactPayload = {
  artifactId: 'orbit-demo', kind: 'motion', title: 'Orbital motion', summary: 'How the orbit changes',
  sourceHtml: '<canvas data-evoflux-motion-canvas></canvas>', scene: null, durationMs: 12_000,
  revision: 1, sources: [],
}

describe('MotionArtifact controls', () => {
  beforeEach(() => {
    postMessage.mockClear()
    playbackSimulation.enabled = false
    frameRendererSimulation.enabled = false
    exportMotionFrames.mockReset()
    Object.defineProperty(globalThis, 'VideoEncoder', { configurable: true, value: class {} })
    Object.defineProperty(globalThis, 'ImageBitmap', { configurable: true, value: class {} })
    Object.defineProperty(globalThis, 'createImageBitmap', { configurable: true, value: vi.fn() })
    Object.defineProperty(window, 'MediaRecorder', {
      configurable: true,
      value: class { static isTypeSupported() { return true } },
    })
  })

  it('sends play, restart and seek commands and explains missing-canvas export', () => {
    render(<MotionArtifact artifact={artifact} theme="system" reducedMotion />)

    fireEvent.click(screen.getByRole('button', { name: 'Play' }))
    fireEvent.click(screen.getByRole('button', { name: 'Restart' }))
    fireEvent.change(screen.getByRole('slider', { name: 'Motion timeline' }), { target: { value: '4200' } })

    expect(postMessage).toHaveBeenNthCalledWith(1, { type: 'command', command: 'play' })
    expect(postMessage).toHaveBeenNthCalledWith(2, { type: 'command', command: 'restart' })
    expect(postMessage).toHaveBeenNthCalledWith(3, { type: 'command', command: { type: 'seek', currentTimeMs: 4200 } })
    expect(screen.getByText(/Reduced motion is on/)).toBeVisible()
    expect(screen.getByText(/no marked canvas/)).toBeVisible()
    expect(screen.getByRole('button', { name: /Export/ })).toBeDisabled()
  })

  it('pauses playback automatically when the Workbench tab becomes inactive', async () => {
    playbackSimulation.enabled = true
    render(<MotionArtifact artifact={artifact} theme="system" reducedMotion={false} active={false} />)
    await waitFor(() => expect(postMessage).toHaveBeenCalledWith({ type: 'command', command: 'pause' }))
  })

  it('offers a selectable quality preset when deterministic frame export is available', async () => {
    frameRendererSimulation.enabled = true
    render(<MotionArtifact artifact={artifact} theme="system" reducedMotion={false} />)

    const quality = screen.getByRole('combobox', { name: 'Video quality' })
    expect(quality).toHaveTextContent('720p · Balanced')
    fireEvent.click(quality)
    const highOption = await screen.findByRole('option', { name: '1080p · High' })
    fireEvent.mouseMove(highOption)
    fireEvent.pointerDown(highOption, { pointerType: 'mouse' })
    fireEvent.mouseUp(highOption)
    fireEvent.click(highOption)
    await waitFor(() => expect(quality).toHaveTextContent('1080p · High'))
    expect(screen.getByRole('button', { name: 'Render video' })).toBeEnabled()
  })

  it('cancels a render when the artifact revision changes', async () => {
    frameRendererSimulation.enabled = true
    exportMotionFrames.mockImplementation(async (options: { requestFrame: (time: number, id: number) => Promise<unknown> }) => {
      await options.requestFrame(0, 1)
      return { blob: new Blob(), extension: 'mp4' }
    })
    const view = render(<MotionArtifact artifact={artifact} theme="system" reducedMotion={false} />)

    fireEvent.click(screen.getByRole('button', { name: 'Render video' }))
    await waitFor(() => expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({
      type: 'command',
      command: expect.objectContaining({ type: 'render_frame' }),
    })))
    view.rerender(<MotionArtifact artifact={{ ...artifact, revision: 2 }} theme="system" reducedMotion={false} />)

    expect(await screen.findByText('Video export cancelled.')).toBeVisible()
    expect(exportMotionFrames).toHaveBeenCalledWith(expect.objectContaining({ preset: 'balanced' }))
  })
})
