import { useEffect, useState } from 'react'
import { Download, FolderDown } from 'lucide-react'
import type { VisualArtifactPayload } from '@/api/types'
import { writeCodingWorkspaceFile } from '@/api/client/team'
import { useThemePreference } from '@/hooks/useThemePreference'
import { useMotionPreset } from '@/lib/motion'
import { projectRelativePath } from '@/lib/project-relative-path'
import { isTauriAvailable } from '@/api/tauri-workspace'
import { useTeamStore } from '@/stores/useTeamStore'
import type { MotionReviewRequest, MotionSampleReviewRequest } from '@/stores/useUIStore'
import { DashboardArtifact } from '@/components/visual-artifact/DashboardArtifact'
import { MotionArtifact } from '@/components/visual-artifact/MotionArtifact'
import { Scene3DArtifact } from '@/components/visual-artifact/Scene3DArtifact'
import type { WorkbenchContext } from './tools'

interface Props extends WorkbenchContext {
  artifact: VisualArtifactPayload
  active?: boolean
  reviewRequest?: MotionReviewRequest
  motionSampleReviewRequest?: MotionSampleReviewRequest
}

function sourceFor(artifact: VisualArtifactPayload): { content: string; extension: string; mime: string } {
  if (artifact.sourceHtml !== null) {
    return { content: artifact.sourceHtml, extension: 'html', mime: 'text/html' }
  }
  return {
    content: `${JSON.stringify({ kind: artifact.kind, title: artifact.title, scene: artifact.scene }, null, 2)}\n`,
    extension: 'json',
    mime: 'application/json',
  }
}

function downloadSource(artifact: VisualArtifactPayload) {
  const source = sourceFor(artifact)
  const url = URL.createObjectURL(new Blob([source.content], { type: `${source.mime};charset=utf-8` }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${artifact.artifactId}.${source.extension}`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function VisualArtifactWorkbench({ artifact, mode, sessionId, workspace, active = true, reviewRequest, motionSampleReviewRequest }: Props) {
  const { preference, resolved } = useThemePreference()
  const motionPreset = useMotionPreset()
  const [reducedMotion, setReducedMotion] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true,
  )
  const [saveStatus, setSaveStatus] = useState('')
  const respectReducedMotion = reducedMotion || motionPreset.intensity === 'reduced'
  const canSaveToProject = mode === 'coding' && Boolean(workspace) && isTauriAvailable()

  useEffect(() => {
    if (!window.matchMedia) return
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => setReducedMotion(media.matches)
    media.addEventListener('change', sync)
    return () => media.removeEventListener('change', sync)
  }, [])

  const saveSource = async () => {
    const source = sourceFor(artifact)
    setSaveStatus('')
    if (!canSaveToProject || !workspace) {
      downloadSource(artifact)
      setSaveStatus('Source download started.')
      return
    }
    try {
      const { save } = await import('@tauri-apps/plugin-dialog')
      const selectedPath = await save({
        defaultPath: `${workspace.replace(/[\\/]+$/, '')}/${artifact.artifactId}.${source.extension}`,
        filters: [{ name: source.extension.toUpperCase(), extensions: [source.extension] }],
      })
      if (!selectedPath) return
      const path = projectRelativePath(workspace, selectedPath)
      if (!path) {
        setSaveStatus('Choose a path inside the active project folder.')
        return
      }
      await writeCodingWorkspaceFile(workspace, path, source.content)
      setSaveStatus(`Saved to ${path}. Review it in Source Control before committing.`)
    } catch (error) {
      setSaveStatus(error instanceof Error ? error.message : 'Could not save the artifact source.')
    }
  }

  const onSendPrompt = (prompt: string) => {
    void useTeamStore.getState().sendMessage(prompt, undefined, { delivery: 'steer' })
  }

  return (
    <section className="flex h-full min-h-0 min-w-0 flex-col bg-(--bg-page)" aria-label={`${artifact.title} preview`}>
      <header className="flex shrink-0 items-start gap-3 border-b border-(--color-border-subtle) px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold text-(--color-text)">{artifact.title}</h2>
          <p className="mt-0.5 line-clamp-2 text-xs text-(--color-text-subtle)">{artifact.summary}</p>
        </div>
        <button
          type="button"
          onClick={() => void saveSource()}
          className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-(--color-border) px-2.5 text-xs font-medium text-(--color-text-2) transition-colors hover:bg-(--bg-key) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
        >
          {canSaveToProject ? <FolderDown size={14} aria-hidden="true" /> : <Download size={14} aria-hidden="true" />}
          {canSaveToProject ? 'Save to project' : 'Download source'}
        </button>
      </header>
      {saveStatus && <p role="status" className="shrink-0 px-4 py-2 text-xs text-(--color-text-muted)">{saveStatus}</p>}
      <div className="min-h-0 min-w-0 flex-1 overflow-auto p-3">
        {artifact.kind === 'dashboard' && (
          <DashboardArtifact artifact={artifact} theme={preference} reducedMotion={respectReducedMotion} onSendPrompt={onSendPrompt} />
        )}
        {artifact.kind === 'motion' && (
          <MotionArtifact artifact={artifact} theme={preference} reducedMotion={respectReducedMotion} active={active} reviewRequest={reviewRequest} motionSampleReviewRequest={motionSampleReviewRequest} sessionId={sessionId} />
        )}
        {artifact.kind === 'scene3d' && (
          <Scene3DArtifact artifact={artifact} reducedMotion={respectReducedMotion} resolvedTheme={resolved} visible={active} />
        )}
      </div>
    </section>
  )
}
