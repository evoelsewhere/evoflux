import { Skeleton } from '@/components/ui/skeleton'
import type { WorkspaceDocumentKind } from '@/lib/workspace-file-kind'

const THUMBNAILS = 5
const SHEET_COLUMNS = 7
const SHEET_ROWS = 14
// Varied line lengths so the placeholder reads as prose, not a barcode.
const LINE_WIDTHS = ['92%', '100%', '96%', '88%', '64%', '0', '97%', '100%', '93%', '71%', '0', '98%', '85%', '90%', '56%']

function ToolbarSkeleton({ controls }: { controls: number }) {
  return (
    <div className="flex h-9 shrink-0 items-center gap-2 border-b border-(--color-border) bg-(--bg-card) px-2.5">
      <Skeleton className="size-5" />
      <Skeleton className="size-5" />
      <Skeleton className="h-3 w-28" />
      <div className="ml-auto flex items-center gap-2">
        {Array.from({ length: controls }, (_, index) => (
          <Skeleton key={index} className="size-5" />
        ))}
      </div>
    </div>
  )
}

function SlideSkeleton() {
  return (
    <div className="flex min-h-0 flex-1">
      <div className="hidden w-36 shrink-0 flex-col gap-3 border-r border-(--color-border) bg-(--bg-card) p-2.5 sm:flex">
        {Array.from({ length: THUMBNAILS }, (_, index) => (
          <div key={index} className="flex items-start gap-1.5">
            <Skeleton className="mt-1 h-2 w-2.5 shrink-0" />
            <Skeleton className="aspect-video w-full rounded" />
          </div>
        ))}
      </div>
      <div className="flex min-w-0 flex-1 items-center justify-center bg-[#e8eaed] p-6">
        <div className="flex aspect-video w-full max-w-3xl flex-col justify-center gap-4 rounded bg-white p-[8%] shadow-sm">
          <Skeleton className="h-[9%] w-3/5" />
          <Skeleton className="h-[5%] w-2/5" />
          <div className="mt-[4%] flex flex-col gap-3">
            <Skeleton className="h-2.5 w-4/5" />
            <Skeleton className="h-2.5 w-3/4" />
            <Skeleton className="h-2.5 w-2/3" />
          </div>
        </div>
      </div>
    </div>
  )
}

function SheetSkeleton() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-(--color-border) bg-(--bg-card) px-2.5">
        <Skeleton className="h-5 w-14" />
        <Skeleton className="h-5 flex-1" />
      </div>
      <div className="min-h-0 flex-1 overflow-hidden bg-white">
        <div
          className="grid"
          style={{ gridTemplateColumns: `44px repeat(${SHEET_COLUMNS}, minmax(72px, 1fr))` }}
        >
          <div className="h-6 border-r border-b border-(--color-border) bg-[#f3f4f6]" />
          {Array.from({ length: SHEET_COLUMNS }, (_, column) => (
            <div key={column} className="flex h-6 items-center justify-center border-r border-b border-(--color-border) bg-[#f3f4f6]">
              <Skeleton className="h-2 w-3" />
            </div>
          ))}
          {Array.from({ length: SHEET_ROWS }, (_, row) => (
            <div key={row} className="contents">
              <div className="flex h-6 items-center justify-center border-r border-b border-(--color-border) bg-[#f3f4f6]">
                <Skeleton className="h-2 w-3" />
              </div>
              {Array.from({ length: SHEET_COLUMNS }, (_, column) => (
                <div key={column} className="flex h-6 items-center border-r border-b border-(--color-border) px-2">
                  {/* Fill a denser block in the top-left, like real data. */}
                  {(row < 9 && column < 5) || (row === 0) ? (
                    <Skeleton
                      className="h-2.5"
                      style={{ width: `${45 + ((row * 7 + column * 13) % 45)}%` }}
                    />
                  ) : null}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
      <div className="flex h-8 shrink-0 items-center gap-2 border-t border-(--color-border) bg-(--bg-card) px-2.5">
        <Skeleton className="h-4 w-16" />
        <Skeleton className="h-4 w-14" />
      </div>
    </div>
  )
}

function PageSkeleton() {
  return (
    <div className="flex min-h-0 flex-1 justify-center overflow-hidden bg-[#e8eaed] px-4 pt-6">
      <div className="flex aspect-[1/1.414] w-full max-w-2xl flex-col gap-2.5 bg-white px-[9%] py-[10%] shadow-sm">
        <Skeleton className="mb-3 h-5 w-1/2" />
        {LINE_WIDTHS.map((width, index) => (
          width === '0'
            ? <div key={index} className="h-3" />
            : <Skeleton key={index} className="h-2.5" style={{ width }} />
        ))}
      </div>
    </div>
  )
}

/**
 * Placeholder shaped like the viewer about to appear, so a slow render
 * (the first exact LibreOffice render can take up to a minute) does not
 * read as a blank panel.
 */
export function DocumentPreviewSkeleton({
  kind,
  label,
  note,
}: {
  kind: WorkspaceDocumentKind
  label: string
  note?: string
}) {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-(--bg-app)" data-testid="document-preview-skeleton">
      {kind !== 'xlsx' && <ToolbarSkeleton controls={kind === 'pptx' ? 6 : 4} />}
      {kind === 'pptx' ? <SlideSkeleton /> : kind === 'xlsx' ? <SheetSkeleton /> : <PageSkeleton />}
      <p role="status" aria-live="polite" className={note ? 'shrink-0 border-t border-(--color-border) bg-(--bg-card) px-3 py-1.5 text-[11px] text-(--color-text-muted)' : 'sr-only'}>
        Rendering {label} document…{note ? ` ${note}` : ''}
      </p>
    </div>
  )
}
