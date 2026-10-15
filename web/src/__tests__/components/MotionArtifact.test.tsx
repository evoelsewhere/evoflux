import { fireEvent, render, screen } from '@testing-library/react'
import { useEffect } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { VisualArtifactPayload } from '@/api/types'
import { MotionArtifact } from '@/components/visual-artifact/MotionArtifact'

const postMessage = vi.fn()
const port = {
  postMessage,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
} as unknown as MessagePort

vi.mock('@/components/VisualArtifactFrame', () => ({
  VisualArtifactFrame: ({ onPort, onReady }: {
    onPort: (port: MessagePort | null) => void
    onReady: (message: { type: 'ready'; motionCanvas: boolean }) => void
  }) => {
    useEffect(() => {
      onPort(port)
      onReady({ type: 'ready', motionCanvas: false })
      return () => onPort(null)
    }, [onPort, onReady])
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
})
