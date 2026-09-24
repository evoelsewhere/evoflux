import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import type { ContentBlock, WorkspaceFileInfo } from '@/api/types'
import { workspaceDocumentPreviewUrl, workspaceMediaUrl } from '@/api/client'
import { isTauriAvailable, tauriOpenWorkspaceFile } from '@/api/tauri-workspace'
import { FileTypeIcon } from '@/components/FileTypeIcon'
import { firstItemThumbnail } from '@/lib/document-thumbnail'
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

// Documents come before images: a deck matters more than the renders QA made of it.
const KIND_ORDER: Record<string, number> = { pptx: 0, docx: 0, xlsx: 0, pdf: 0, image: 1 }
const VISIBLE_FILES = 4
// Pages and sheets are laid out at this width, then scaled into the tile.
const PAGE_WIDTH = 816
// A preview larger than this is not worth downloading for a thumbnail.
const MAX_THUMBNAIL_SOURCE_BYTES = 30 * 1024 * 1024

function describe(file: WorkspaceFileInfo): string {
  const kind = workspaceFileKind(file)
  const label = kind in KIND_LABEL ? KIND_LABEL[kind as keyof typeof KIND_LABEL] : 'File'
  const extension = workspaceFileExtension(file.name).toUpperCase()
  return [label, extension, formatBytes(file.size)].filter(Boolean).join(' · ')
}

/** Whether ``ref`` has come near the viewport (and stays true once it has). */
function useSeen(ref: React.RefObject<HTMLElement | null>): boolean {
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    const element = ref.current
    if (seen || !element || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) setSeen(true)
    }, { rootMargin: '200px' })
    observer.observe(element)
    return () => observer.disconnect()
  }, [ref, seen])
  return seen
}

function useWidth(ref: React.RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const element = ref.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(element)
    return () => observer.disconnect()
  }, [ref])
  return width
}

/** The first slide or page, from the same cached preview the viewer shows. */
function useDocumentThumbnail(sessionId: string, file: WorkspaceFileInfo, enabled: boolean) {
  const kind = workspaceFileKind(file)
  return useQuery({
    queryKey: ['team', 'document-thumbnail', sessionId, file.path, file.size, file.mtime],
    enabled: enabled && kind !== 'image',
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: 10 * 60 * 1000,
    retry: false,
    queryFn: async ({ signal }) => {
      const response = await fetch(workspaceDocumentPreviewUrl(sessionId, file.path), { signal })
      const size = Number(response.headers.get('content-length') ?? 0)
      if (!response.ok || size > MAX_THUMBNAIL_SOURCE_BYTES) throw new Error('No thumbnail')
      return firstItemThumbnail(await response.text(), kind)
    },
  })
}

function FileThumbnail({ file, sessionId }: { file: WorkspaceFileInfo; sessionId: string }) {
  const boxRef = useRef<HTMLSpanElement>(null)
  const seen = useSeen(boxRef)
  const width = useWidth(boxRef)
  const kind = workspaceFileKind(file)
  const [imageFailed, setImageFailed] = useState(false)
  const thumbnail = useDocumentThumbnail(sessionId, file, seen)

  let content: React.ReactNode = <FileTypeIcon name={file.name} mime={file.mime} size={28} />
  if (kind === 'image' && seen && !imageFailed) {
    content = (
      <img
        src={workspaceMediaUrl(sessionId, file.path)}
        alt=""
        loading="lazy"
        onError={() => setImageFailed(true)}
        className="h-full w-full object-cover"
      />
    )
  } else if (thumbnail.data && kind === 'pptx') {
    content = <ThumbnailFrame html={thumbnail.data} className="h-full w-full" />
  } else if (thumbnail.data && width > 0) {
    const scale = width / PAGE_WIDTH
    content = (
      <ThumbnailFrame
        html={thumbnail.data}
        className="absolute left-0 top-0 origin-top-left"
        style={{ width: PAGE_WIDTH, height: (width * 10) / 16 / scale, transform: `scale(${scale})` }}
      />
    )
  }
  return (
    <span
      ref={boxRef}
      className="relative flex aspect-[16/10] items-center justify-center overflow-hidden border-b border-(--color-border) bg-(--bg-page)"
    >
      {content}
    </span>
  )
}

function ThumbnailFrame({ html, className, style }: { html: string; className: string; style?: React.CSSProperties }) {
  return (
    <iframe
      srcDoc={html}
      title=""
      sandbox=""
      referrerPolicy="no-referrer"
      tabIndex={-1}
      aria-hidden="true"
      className={`pointer-events-none border-0 bg-white ${className}`}
      style={style}
    />
  )
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
    <div className="group relative min-w-0 overflow-hidden rounded-lg border border-(--color-border) bg-(--bg-card) transition-colors hover:border-(--color-border-strong)">
      <button
        type="button"
        onClick={openPreview}
        className="block w-full text-left"
        title={`Preview ${file.path} in Files`}
        aria-label={`Preview ${file.name}`}
      >
        <FileThumbnail file={file} sessionId={sessionId} />
        <span className="flex min-w-0 items-center gap-2 px-2.5 py-1.5 group-hover:bg-(--bg-key)">
          <FileTypeIcon name={file.name} mime={file.mime} size={16} />
          <span className="min-w-0">
            <span className="block truncate text-[12px] font-medium text-(--color-text)">{file.name}</span>
            <span className="block truncate text-[11px] text-(--color-text-muted)">{describe(file)}</span>
          </span>
        </span>
      </button>
      <button
        type="button"
        onClick={() => void openExternally()}
        className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-md bg-(--bg-card)/90 text-(--color-text-muted) opacity-0 shadow-sm transition-opacity hover:text-(--color-text) focus-visible:opacity-100 group-hover:opacity-100"
        title="Open in default app"
        aria-label={`Open ${file.name} in default app`}
      >
        <ExternalLink size={12} />
      </button>
    </div>
  )
}

/**
 * Cards for the previewable files (decks, sheets, documents, PDFs, images)
 * a finished turn created or changed, each with a thumbnail of the file;
 * clicking one opens it in Files.
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
      className="grid max-w-3xl grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))] gap-2"
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
          className="flex min-h-16 items-center justify-center rounded-lg border border-dashed border-(--color-border) px-3 py-1.5 text-[12px] font-medium text-(--color-text-muted) transition-colors hover:border-(--color-border-strong) hover:bg-(--bg-key) hover:text-(--color-text)"
        >
          {expanded ? 'Show less' : `+${hidden} more`}
        </button>
      )}
    </div>
  )
}
