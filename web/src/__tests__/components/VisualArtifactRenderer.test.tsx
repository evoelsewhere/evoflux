import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BlockRenderer } from '@/components/BlockRenderer'
import type { ContentBlock } from '@/api/types'
import { DashboardArtifact } from '@/components/visual-artifact/DashboardArtifact'

const artifact: ContentBlock = {
  id: 'budget', type: 'visual_artifact', content: '', title: 'Budget dashboard',
  visualArtifact: {
    artifactId: 'budget', kind: 'dashboard', title: 'Budget dashboard', summary: 'Trip spend',
    sourceHtml: '<main>chart</main>', scene: null, durationMs: null, revision: 1, sources: [],
  },
}

describe('visual artifact rendering', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false, media: query, onchange: null,
        addEventListener: vi.fn(), removeEventListener: vi.fn(),
      })),
    })
  })

  it('renders dashboard HTML in a script-only opaque iframe and discloses missing provenance', () => {
    render(<BlockRenderer block={artifact} isStreaming={false} />)
    const frame = screen.getByTitle('Budget dashboard')
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts')
    expect(frame).not.toHaveAttribute('allow')
    expect(frame).toHaveAttribute('srcdoc', expect.stringContaining("default-src 'none'"))
    expect(screen.getByText(/Illustrative example/)).toBeVisible()
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
