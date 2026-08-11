import { Download, FileText, FileType, File as FileIcon, X } from 'lucide-react'
import { openExternalUrl } from '@/lib/open-external'

interface FileCardProps {
  name?: string
  mediaType?: string
  url?: string
  onRemove?: () => void
  /** If true, show a remove button (for pending attachments) */
  removable?: boolean
  /** If true, clicking opens the file in a new tab (for persisted files) */
  clickable?: boolean
  /** Show a dedicated download action for generated workspace files. */
  onDownload?: () => void
  /** Optional direct download URL for generated workspace artifacts. */
  downloadUrl?: string
  /** Host-owned preview action; preferred over opening a raw URL externally. */
  onOpen?: () => void
}

function getFileIcon(mediaType?: string) {
  if (!mediaType) return <FileIcon size={16} />

  if (mediaType.includes('pdf')) {
    return <FileType size={16} />
  }
  if (mediaType.includes('word') || mediaType.includes('document')) {
    return <FileType size={16} />
  }
  if (mediaType.includes('text')) {
    return <FileText size={16} />
  }

  return <FileIcon size={16} />
}

export function FileCard({
  name = 'File',
  mediaType,
  url,
  onRemove,
  removable,
  clickable,
  onDownload,
  downloadUrl,
  onOpen,
}: FileCardProps) {
  // Truncate long filenames to ~20 chars
  const displayName = name.length > 20 ? `${name.substring(0, 17)}…` : name

  const handleClick = () => {
    if (clickable && onOpen) {
      onOpen()
    } else if (clickable && url) {
      // window.open silently no-ops in Tauri webviews; openExternalUrl uses
      // the system opener there and falls back to window.open in browsers.
      void openExternalUrl(url)
    }
  }

  return (
    <div className="group relative inline-flex">
      <button
        type="button"
        onClick={handleClick}
        disabled={!clickable}
        className={`surface-raised flex items-center gap-2 border border-(--color-border) bg-(--bg-card) px-3 py-2 text-xs text-(--color-text) transition-[background-color,border-color,box-shadow,opacity] duration-(--motion-fast) ${onDownload || downloadUrl ? 'rounded-l-lg' : 'rounded-lg'} ${
          clickable ? 'cursor-pointer hover:border-(--color-accent) hover:bg-(--bg-key)' : ''
        }`}
        title={name}
      >
        <span className="flex-shrink-0 text-(--color-text-muted)">
          {getFileIcon(mediaType)}
        </span>
        <span className="flex-shrink-0 font-medium">{displayName}</span>
      </button>

      {(onDownload || downloadUrl) && (
        <button
          type="button"
          onClick={() => {
            if (onDownload) onDownload()
            else if (downloadUrl) void openExternalUrl(downloadUrl)
          }}
          className="surface-raised flex items-center justify-center rounded-r-lg border border-l-0 border-(--color-border) bg-(--bg-card) px-2 text-(--color-text-muted) transition-colors duration-(--motion-fast) hover:border-(--color-accent) hover:bg-(--bg-key) hover:text-(--color-text)"
          aria-label={`Download ${name}`}
          title="Download"
        >
          <Download size={14} />
        </button>
      )}

      {removable && onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onRemove()
          }}
          className="absolute -right-2 -top-2 flex h-7 w-7 items-center justify-center rounded-full bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border) shadow-sm transition-opacity opacity-100 hover:text-(--color-text) md:-right-1.5 md:-top-1.5 md:h-4 md:w-4 md:opacity-0 md:group-hover:opacity-100"
          aria-label="Remove file"
          title="Remove"
        >
          <X size={12} className="md:h-2.5 md:w-2.5" />
        </button>
      )}
    </div>
  )
}
