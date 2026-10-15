import { useEffect } from 'react'
import { Box, ExternalLink } from 'lucide-react'
import type { ContentBlock } from '@/api/types'
import { useUIStore } from '@/stores/useUIStore'

const KIND_LABELS = {
  dashboard: 'Dashboard',
  motion: 'Animated explainer',
  scene3d: '3D scene',
} as const

export function VisualArtifactRenderer({ block }: { block: ContentBlock }) {
  const artifact = block.visualArtifact
  const sessionId = useUIStore((state) => state.workbenchSessionId)
  const tabs = useUIStore((state) => state.workbenchTabs)
  const openWorkbenchTool = useUIStore((state) => state.openWorkbenchTool)
  const updateWorkbenchTab = useUIStore((state) => state.updateWorkbenchTab)

  useEffect(() => {
    if (!artifact) return
    for (const tab of tabs) {
      if (
        tab.tool === 'visual-artifact'
        && tab.sessionId === sessionId
        && tab.artifact?.artifactId === artifact.artifactId
        && tab.artifact.revision < artifact.revision
      ) {
        updateWorkbenchTab(tab.id, { title: artifact.title, artifact })
      }
    }
  }, [artifact, sessionId, tabs, updateWorkbenchTab])

  if (!artifact) return null
  return (
    <div className="my-2 flex min-w-0 items-center gap-3 rounded-xl border border-(--color-border-subtle) bg-(--bg-card) p-3">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-(--color-accent)/10 text-(--color-accent)">
        <Box size={18} aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="truncate text-sm font-medium text-(--color-text)">{artifact.title}</h3>
          <span className="shrink-0 rounded-md border border-(--color-border-subtle) px-1.5 py-0.5 text-[10px] text-(--color-text-muted)">
            {KIND_LABELS[artifact.kind]}
          </span>
        </div>
        <p className="mt-0.5 line-clamp-2 text-xs text-(--color-text-subtle)">{artifact.summary}</p>
      </div>
      <button
        type="button"
        onClick={() => openWorkbenchTool('visual-artifact', { title: artifact.title, artifact })}
        className="flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-(--color-accent) px-2.5 text-xs font-medium text-white transition-colors hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
      >
        <span>Open in Workbench</span>
        <ExternalLink size={13} aria-hidden="true" />
      </button>
    </div>
  )
}
