import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useEffect, useRef } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { VisualArtifactPayload } from '@/api/types'
import { MotionArtifact } from '@/components/visual-artifact/MotionArtifact'

const postMessage = vi.fn()
const playbackSimulation = vi.hoisted(() => ({ enabled: false }))
const port = {
  postMessage,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
} as unknown as MessagePort

vi.mock('@/components/VisualArtifactFrame', () => ({
  VisualArtifactFrame: ({ onPort, onReady, onPlayback }: {
    onPort: (port: MessagePort | null) => void
    onReady: (message: { type: 'ready'; motionCanvas: boolean }) => void
    onPlayback: (message: { state: 'playing' | 'paused' | 'ended'; currentTimeMs: number }) => void
  }) => {
    const didSimulate = useRef(false)
    useEffect(() => {
      onPort(port)
      onReady({ type: 'ready', motionCanvas: false })
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
})
