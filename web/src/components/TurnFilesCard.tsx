import { useMemo, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import type { ContentBlock, WorkspaceFileInfo } from '@/api/types'
import { workspaceMediaUrl } from '@/api/client'
import { isTauriAvailable, tauriOpenWorkspaceFile } from '@/api/tauri-workspace'
import { FileTypeIcon } from '@/components/FileTypeIcon'
import { openExternalUrl } from '@/lib/open-external'
import { resolveTurnFiles, turnFileMentions } from '@/lib/turn-files'
import { workspaceFileExtension, workspaceFileKind } from '@/lib/workspace-file-kind'
import { useWorkspaceFilesQuery } from '@/queries/useWorkspaceFilesQuery'
import { useUIStore } from '@/stores/useUIStore'
import { formatBytes } from '@/utils/format'

const KIND_LABEL = {
  pptx: 'Slides',
  xlsx: 'Spreadsheet',
  docx: 'Document',
  pdf: 'PDF',
  image: 'Image',
} as const

function describe(file: WorkspaceFileInfo): string {
  const kind = workspaceFileKind(file)
  const label = kind in KIND_LABEL ? KIND_LABEL[kind as keyof typeof KIND_LABEL] : 'File'
  const extension = workspaceFileExtension(file.name).toUpperCase()
  return [label, extension, formatBytes(file.size)].filter(Boolean).join(' · ')
}

function WorkspaceFileCard({
  file,
  sessionId,
  workspaceRoot,
}: {
  file: WorkspaceFileInfo
  sessionId: string
  workspaceRoot: string | null
}) {
  const openPreview = () => useUIStore.getState().requestWorkspaceFile(sessionId, file.path)
  const openExternally = async () => {
    try {
      if (isTauriAvailable() && workspaceRoot) await tauriOpenWorkspaceFile(workspaceRoot, file.path)
      else await openExternalUrl(workspaceMediaUrl(sessionId, file.path))
    } catch {
      // Opening in another app is a convenience; the preview still works.
    }
  }
  return (
    <div className="group relative flex min-w-0 items-center gap-2.5 rounded-lg border border-(--color-border) bg-(--bg-card) py-1.5 pl-2 pr-8 transition-colors hover:border-(--color-border-strong) hover:bg-(--bg-key)">
      <button
        type="button"
        onClick={openPreview}
        className="flex min-w-0 flex-1 items-center gap-2.5 text-left after:absolute after:inset-0 after:content-['']"
        title={`Preview ${file.path} in Files`}
        aria-label={`Preview ${file.name}`}
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-(--bg-page)">
          <FileTypeIcon name={file.name} mime={file.mime} size={20} />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-[12px] font-medium text-(--color-text)">{file.name}</span>
          <span className="block truncate text-[11px] text-(--color-text-muted)">{describe(file)}</span>
        </span>
      </button>
      <button
        type="button"
        onClick={() => void openExternally()}
        className="absolute right-1.5 top-1/2 z-10 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-(--color-text-muted) opacity-0 transition-opacity hover:bg-(--bg-page) hover:text-(--color-text) focus-visible:opacity-100 group-hover:opacity-100"
        title="Open in default app"
        aria-label={`Open ${file.name} in default app`}
      >
        <ExternalLink size={12} />
      </button>
    </div>
  )
}

// Documents come before images: a deck matters more than the renders QA made of it.
const KIND_ORDER: Record<string, number> = { pptx: 0, docx: 0, xlsx: 0, pdf: 0, image: 1 }
const VISIBLE_FILES = 4

/**
 * Cards for the previewable files (decks, sheets, documents, PDFs, images)
 * a finished turn created or changed; clicking one opens it in Files.
 */
export function TurnFilesCard({ blocks, sessionId }: { blocks: readonly ContentBlock[]; sessionId?: string }) {
  const mentions = useMemo(() => turnFileMentions(blocks), [blocks])
  const { data } = useWorkspaceFilesQuery(mentions.length > 0 ? sessionId : null)
  const files = useMemo(
    () => resolveTurnFiles(mentions, data?.files ?? [], data?.workspace_root)
      .map((file, index) => ({ file, index, rank: KIND_ORDER[workspaceFileKind(file)] ?? 1 }))
      .sort((a, b) => a.rank - b.rank || a.index - b.index)
      .map(({ file }) => file),
    [data, mentions],
  )
  const [expanded, setExpanded] = useState(false)
  if (!sessionId || files.length === 0) return null
  const hidden = files.length - VISIBLE_FILES
  const shown = expanded || hidden <= 0 ? files : files.slice(0, VISIBLE_FILES)
  return (
    <div
      className="grid max-w-3xl grid-cols-[repeat(auto-fill,minmax(13rem,1fr))] gap-1.5"
      aria-label="Files from this turn"
    >
      {shown.map((file) => (
        <WorkspaceFileCard
          key={file.path}
          file={file}
          sessionId={sessionId}
          workspaceRoot={data?.workspace_root ?? null}
        />
      ))}
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="flex items-center justify-center gap-1 rounded-lg border border-dashed border-(--color-border) px-3 py-1.5 text-[12px] font-medium text-(--color-text-muted) transition-colors hover:border-(--color-border-strong) hover:bg-(--bg-key) hover:text-(--color-text)"
        >
          {expanded ? 'Show less' : `+${hidden} more`}
        </button>
      )}
    </div>
  )
}
