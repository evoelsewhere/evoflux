/**
 * FilePreviewStrip — horizontally scrolling row of file previews with an
 * optional scroll-position hint pill below.
 *
 * Used by InputBar when `files.length > 0`. The strip clips at the visible
 * width and scrolls horizontally; when content overflows, a 3px-tall pill
 * appears below the strip showing a thumb that mirrors the current scroll
 * position. The hint matches pencil's `attachmentScrollHint` /
 * `attachmentScrollThumb` pattern from the `MultiAttachOverflow` variant.
 *
 * If the content fits within the visible width (no overflow), the hint
 * is not rendered — keeping the bar visually quiet for small attachment
 * counts.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ImageAttachment } from './ImageAttachment'
import { FileCard } from './FileCard'

interface FilePreviewStripProps {
  files: File[]
  blobUrls: Map<number, string>
  onRemove: (index: number) => void
  /** Whether to apply top margin (true) or bottom margin (false). */
  filesBelow: boolean
}

interface ScrollMetrics {
  thumbWidthPct: number
  thumbLeftPct: number
  hasOverflow: boolean
}

function computeMetrics(el: HTMLElement): ScrollMetrics {
  const { scrollLeft, scrollWidth, clientWidth } = el
  const hasOverflow = scrollWidth > clientWidth + 1
  if (!hasOverflow) {
    return { thumbWidthPct: 100, thumbLeftPct: 0, hasOverflow: false }
  }
  const thumbWidthPct = Math.max(15, (clientWidth / scrollWidth) * 100)
  const maxScroll = scrollWidth - clientWidth
  const scrollPct = maxScroll > 0 ? scrollLeft / maxScroll : 0
  const thumbLeftPct = scrollPct * (100 - thumbWidthPct)
  return { thumbWidthPct, thumbLeftPct, hasOverflow }
}

export function FilePreviewStrip({
  files,
  blobUrls,
  onRemove,
  filesBelow,
}: FilePreviewStripProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [metrics, setMetrics] = useState<ScrollMetrics>({
    thumbWidthPct: 100,
    thumbLeftPct: 0,
    hasOverflow: false,
  })

  // Recompute on file count change and window resize.
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    setMetrics(computeMetrics(el))
  }, [files.length])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const update = () => setMetrics(computeMetrics(el))
    el.addEventListener('scroll', update, { passive: true })
    const ro = new ResizeObserver(update)
    ro.observe(el)
    window.addEventListener('resize', update)
    return () => {
      el.removeEventListener('scroll', update)
      ro.disconnect()
      window.removeEventListener('resize', update)
    }
  }, [])

  if (files.length === 0) return null

  return (
    <div className={`${filesBelow ? 'mt-3' : 'mb-3'} -mx-2 -my-2`}>
      <div ref={scrollRef} className="overflow-x-auto px-2 py-2">
        <div className="flex w-max flex-nowrap items-center gap-2">
          {files.map((file, idx) => {
            const isImage = file.type.startsWith('image/')
            const blobUrl = blobUrls.get(idx) || ''
            if (isImage) {
              return (
                <div key={idx} className="shrink-0">
                  <ImageAttachment
                    src={blobUrl}
                    alt={file.name}
                    removable
                    compact
                    onRemove={() => onRemove(idx)}
                  />
                </div>
              )
            }
            return (
              <div key={idx} className="shrink-0">
                <FileCard
                  name={file.name}
                  mediaType={file.type}
                  removable
                  onRemove={() => onRemove(idx)}
                />
              </div>
            )
          })}
        </div>
      </div>
      {metrics.hasOverflow && (
        <div
          className="mx-2 mt-1 h-[3px] overflow-hidden rounded-full bg-(--color-border-subtle)"
          aria-hidden="true"
        >
          <div
            className="h-full rounded-full bg-(--color-text-subtle)/60 transition-[left,width] duration-100"
            style={{
              width: `${metrics.thumbWidthPct}%`,
              marginLeft: `${metrics.thumbLeftPct}%`,
            }}
          />
        </div>
      )}
    </div>
  )
}
