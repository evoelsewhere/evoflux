import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BlockRenderer } from '@/components/BlockRenderer'
import type { ContentBlock } from '@/api/types'
import { DashboardArtifact } from '@/components/visual-artifact/DashboardArtifact'
import { publishMotionRenderSnapshot } from '@/lib/motion-render-store'
import { useUIStore } from '@/stores/useUIStore'

const artifact: ContentBlock = {
  id: 'budget', type: 'visual_artifact', content: '', title: 'Budget dashboard',
  visualArtifact: {
    artifactId: 'budget', kind: 'dashboard', title: 'Budget dashboard', summary: 'Trip spend',
    sourceHtml: '<main>chart</main>', scene: null, durationMs: null, revision: 1, sources: [],
  },
}
const motionArtifact: ContentBlock = {
  id: 'water-motion', type: 'visual_artifact', content: '', title: 'Water journey',
  visualArtifact: {
    artifactId: 'water-motion', kind: 'motion', title: 'Water journey', summary: 'From rain to clean water',
    sourceHtml: '<main>motion</main>', scene: null, durationMs: 10_000, revision: 1, sources: [],
  },
}

describe('visual artifact rendering', () => {
  beforeEach(() => {
    useUIStore.setState((state) => {
      state.workbenchTabs = []
      state.workbenchSessionId = 'session-1'
      state.activeWorkbenchTabId = null
      state.activeWorkbenchTool = null
      state.workbenchOpen = false
    })
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false, media: query, onchange: null,
        addEventListener: vi.fn(), removeEventListener: vi.fn(),
      })),
    })
  })

  it('keeps rich content out of the chat and opens the artifact in the Workbench', () => {
    render(<BlockRenderer block={artifact} isStreaming={false} />)
    expect(screen.getByText('Budget dashboard')).toBeVisible()
    expect(screen.queryByTitle('Budget dashboard')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Open in Workbench/i }))
    expect(useUIStore.getState().activeWorkbenchTool).toBe('visual-artifact')
    expect(useUIStore.getState().workbenchOpen).toBe(true)
    expect(useUIStore.getState().workbenchTabs[0]).toMatchObject({
      tool: 'visual-artifact',
      artifact: artifact.visualArtifact,
    })
  })

  it('shows the verified source call and refreshes by sending a normal chat prompt', () => {
    const onSendPrompt = vi.fn()
    render(<DashboardArtifact
      artifact={{
        ...artifact.visualArtifact!,
        sources: [{ toolCallId: 'call-sales', querySummary: 'open opportunities', verified: true, toolName: 'mcp_salesforce.query', arguments: '{"limit":3}', result: '{"rows":3}' }],
      }}
      theme="dark"
      reducedMotion={false}
      onSendPrompt={onSendPrompt}
    />)
    fireEvent.click(screen.getByRole('button', { name: /Data sources/i }))
    expect(screen.getByText(/mcp_salesforce.query/)).toBeVisible()
    expect(screen.getByText(/open opportunities/)).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /Refresh with agent/i }))
    expect(onSendPrompt).toHaveBeenCalledWith(expect.stringContaining('budget'))
  })

  it('shows exact frame progress and opens a selected preview at its timestamp', () => {
    publishMotionRenderSnapshot({
      artifactId: 'water-motion', revision: 1, renderId: 'render-water-1', status: 'rendering',
      completedFrames: 7, totalFrames: 300, fps: 30, lastCompletedIndex: 6, currentTimeMs: 200, currentFrameUrl: null,
      beats: [{ id: 'collection', title: 'Collect rain', startFrame: 0, endFrame: 99, markers: [] }],
      samples: [{ sampleId: 'rain-start', beatId: 'collection', frameIndex: 6, timestampMs: 200, role: 'style', objectUrl: 'blob:rain-start' }],
      audioStatus: 'not_requested',
    })
    render(<BlockRenderer block={motionArtifact} isStreaming={false} />)

    expect(screen.getByRole('status')).toHaveTextContent('7 / 300 frames')
    expect(screen.getByRole('img', { name: /Collect rain.*frame 7/i })).toHaveAttribute('src', 'blob:rain-start')
    fireEvent.click(screen.getByRole('button', { name: /Review frame 7/i }))
    expect(useUIStore.getState().workbenchTabs[0]?.motionReviewRequest).toMatchObject({
      frameIndex: 6, timestampMs: 200,
    })
  })

  it('renders lifecycle progress before the motion artifact is ready', () => {
    const progress: ContentBlock = {
      id: 'motion-job-progress', type: 'motion_progress', content: '', title: 'Collect rain',
      motionProgress: {
        jobId: `motion-${'a'.repeat(32)}`, sequence: 2, artifactId: 'water-progress', artifactRevision: 1,
        status: 'running', phase: 'reviewing',
        beat: { id: 'collection', index: 0, total: 4, title: 'Collect rain' },
        iteration: { current: 1, budget: 3 }, selectedSamples: [], audioStatus: 'pending',
      },
    }
    render(<BlockRenderer block={progress} isStreaming />)

    expect(screen.getByText('Collect rain')).toBeVisible()
    expect(screen.getByRole('status')).toHaveTextContent('Reviewing selected frames')
    expect(screen.getByRole('status')).toHaveTextContent('Beat 1/4: Collect rain')
    expect(screen.queryByRole('button', { name: /Open in Workbench/i })).not.toBeInTheDocument()
  })
})
