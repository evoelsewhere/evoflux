import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { VisualArtifactPayload } from '@/api/types'
import { VisualArtifactWorkbench } from '@/components/workbench/VisualArtifactWorkbench'

const { saveDialog, writeWorkspaceFile, isTauri } = vi.hoisted(() => ({
  saveDialog: vi.fn(),
  writeWorkspaceFile: vi.fn(),
  isTauri: vi.fn(),
}))

vi.mock('@tauri-apps/plugin-dialog', () => ({ save: saveDialog }))
vi.mock('@/api/client/team', () => ({ writeCodingWorkspaceFile: writeWorkspaceFile, postMotionReviewSamples: vi.fn() }))
vi.mock('@/api/tauri-workspace', () => ({ isTauriAvailable: isTauri }))
vi.mock('@/hooks/useThemePreference', () => ({ useThemePreference: () => ({ preference: 'dark', resolved: 'dark' }) }))
vi.mock('@/lib/motion', () => ({ useMotionPreset: () => ({ intensity: 'full' }) }))
vi.mock('@/components/visual-artifact/DashboardArtifact', () => ({
  DashboardArtifact: () => <div data-testid="dashboard-preview" />,
}))
vi.mock('@/components/visual-artifact/MotionArtifact', () => ({
  MotionArtifact: ({ active, reviewRequest, motionSampleReviewRequest }: { active?: boolean; reviewRequest?: { timestampMs: number }; motionSampleReviewRequest?: { sampleRequestId: string } }) => <div data-testid="motion-preview" data-active={String(active)} data-review-time={reviewRequest?.timestampMs} data-sample-request={motionSampleReviewRequest?.sampleRequestId} />,
}))
vi.mock('@/components/visual-artifact/Scene3DArtifact', () => ({
  Scene3DArtifact: ({ visible }: { visible?: boolean }) => <div data-testid="scene3d-preview" data-visible={String(visible)} />,
}))

const base: VisualArtifactPayload = {
  artifactId: 'demo-ui', kind: 'dashboard', title: 'Demo UI', summary: 'Interactive overview',
  sourceHtml: '<main>demo</main>', scene: null, sources: [], durationMs: null, revision: 1,
}
const repoPath = String.raw`C:\repo`

describe('VisualArtifactWorkbench', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    isTauri.mockReturnValue(false)
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
      })),
    })
  })

  it.each([
    ['dashboard', 'dashboard-preview'],
    ['motion', 'motion-preview'],
    ['scene3d', 'scene3d-preview'],
  ] as const)('renders %s inside the workbench surface', (kind, marker) => {
    const artifact = {
      ...base,
      kind,
      sourceHtml: kind === 'scene3d' ? null : base.sourceHtml,
      scene: kind === 'scene3d' ? { nodes: [] } : null,
    } satisfies VisualArtifactPayload
    render(<VisualArtifactWorkbench artifact={artifact} mode="work" sessionId="session-1" workspace={null} />)
    expect(screen.getByTestId(marker)).toBeVisible()
    expect(writeWorkspaceFile).not.toHaveBeenCalled()
  })

  it('pauses rich runtime components while their Workbench tab is hidden', () => {
    const artifact = { ...base, kind: 'scene3d' as const, sourceHtml: null, scene: { nodes: [] } }
    render(<VisualArtifactWorkbench artifact={artifact} mode="work" sessionId="session-1" workspace={null} active={false} />)
    expect(screen.getByTestId('scene3d-preview')).toHaveAttribute('data-visible', 'false')
  })

  it('marks the motion player inactive so it can pause playback off-tab', () => {
    const artifact = { ...base, kind: 'motion' as const, durationMs: 10_000 }
    render(<VisualArtifactWorkbench artifact={artifact} mode="work" sessionId="session-1" workspace={null} active={false} />)
    expect(screen.getByTestId('motion-preview')).toHaveAttribute('data-active', 'false')
  })

  it('passes the selected chat sample time into the motion review surface', () => {
    const artifact = { ...base, kind: 'motion' as const, durationMs: 10_000 }
    render(<VisualArtifactWorkbench
      artifact={artifact}
      mode="work"
      sessionId="session-1"
      workspace={null}
      reviewRequest={{ id: 1, frameIndex: 45, timestampMs: 1_500 }}
    />)
    expect(screen.getByTestId('motion-preview')).toHaveAttribute('data-review-time', '1500')
  })

  it('passes an agent frame review request and session to the isolated renderer', () => {
    const artifact = { ...base, kind: 'motion' as const, durationMs: 10_000 }
    render(<VisualArtifactWorkbench
      artifact={artifact}
      mode="work"
      sessionId="session-1"
      workspace={null}
      motionSampleReviewRequest={{
        id: 'job:request', jobId: `motion-${'c'.repeat(32)}`, sampleRequestId: 'review-1',
        samples: [{ sampleId: 'hit', beatId: 'arrival', frameIndex: 60, timestampMs: 2000, role: 'impact' }],
      }}
    />)
    expect(screen.getByTestId('motion-preview')).toHaveAttribute('data-sample-request', 'review-1')
  })

  it('saves into the project only after a path inside the active repo is selected', async () => {
    isTauri.mockReturnValue(true)
    saveDialog.mockResolvedValue('C:\\repo\\src\\demo-ui.html')
    render(<VisualArtifactWorkbench artifact={base} mode="coding" sessionId="s1" workspace={repoPath} />)

    fireEvent.click(screen.getByRole('button', { name: 'Save to project' }))

    await waitFor(() => expect(writeWorkspaceFile).toHaveBeenCalledWith(
      repoPath, 'src/demo-ui.html', '<main>demo</main>',
    ))
    expect(await screen.findByText(/Review it in Source Control before committing/)).toBeVisible()
  })

  it('does not write when the native save dialog chooses a path outside the project', async () => {
    isTauri.mockReturnValue(true)
    saveDialog.mockResolvedValue('C:\\outside\\demo-ui.html')
    render(<VisualArtifactWorkbench artifact={base} mode="coding" sessionId="s1" workspace={repoPath} />)
    fireEvent.click(screen.getByRole('button', { name: 'Save to project' }))
    expect(await screen.findByText(/inside the active project folder/)).toBeVisible()
    expect(writeWorkspaceFile).not.toHaveBeenCalled()
  })
})
