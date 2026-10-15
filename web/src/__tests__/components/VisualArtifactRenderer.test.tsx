import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BlockRenderer } from '@/components/BlockRenderer'
import type { ContentBlock } from '@/api/types'
import { DashboardArtifact } from '@/components/visual-artifact/DashboardArtifact'
import { useUIStore } from '@/stores/useUIStore'

const artifact: ContentBlock = {
  id: 'budget', type: 'visual_artifact', content: '', title: 'Budget dashboard',
  visualArtifact: {
    artifactId: 'budget', kind: 'dashboard', title: 'Budget dashboard', summary: 'Trip spend',
    sourceHtml: '<main>chart</main>', scene: null, durationMs: null, revision: 1, sources: [],
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
})
