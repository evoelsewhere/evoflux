/**
 * Full-screen image lightbox.
 *
 * Shared by ``ImageAttachment`` (user-uploaded thumbnails) and ``MarkdownBlock``
 * (assistant-rendered inline images) so both get identical UX: click to open,
 * click the backdrop or press Esc to close, portal-rendered so ancestor
 * ``overflow``/``transform`` never clips the overlay.
 */

import { useEffect, useRef, useState, type ReactNode, type TouchEvent, type Touch as ReactTouch } from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, ChevronRight, Download, X } from 'lucide-react'

export interface LightboxImage {
  src: string
  alt: string
}

interface ImageLightboxProps {
  src: string
  alt: string
  isOpen: boolean
  onClose: () => void
  allowDownload?: boolean
  images?: readonly LightboxImage[]
  initialIndex?: number
}

/**
 * Derive a sensible filename from the image source.
 *
 * Handles absolute/relative URLs and ``data:`` URIs. Falls back to a
 * timestamped default when nothing useful can be extracted.
 */
function filenameFromSrc(src: string, alt: string): string {
  // data: URI — pull mime subtype for extension.
  if (src.startsWith('data:')) {
    const match = /^data:([^;,]+)/.exec(src)
    const ext = match?.[1]?.split('/')[1]?.split('+')[0] ?? 'png'
    const base = alt?.trim() ? alt.trim().replace(/[^\w.-]+/g, '_') : `image-${Date.now()}`
    return `${base}.${ext}`
  }
  try {
    const url = new URL(src, window.location.origin)
    const last = url.pathname.split('/').filter(Boolean).pop()
    if (last && last.includes('.')) return last
    if (last) return `${last}.png`
  } catch {
    // fall through
  }
  return `image-${Date.now()}.png`
}

/**
 * Icon button with a CSS-only tooltip.
 *
 * Uses a ``group`` wrapper so the tooltip fades in on hover/focus without
 * needing a ``TooltipProvider`` (not wired up globally in the app yet).
 */
function LightboxIconButton({
  onClick,
  icon,
  label,
  tooltip,
}: {
  onClick: () => void
  icon: ReactNode
  label: string
  tooltip: string
}) {
  return (
    <div className="group relative">
      <button
        onClick={onClick}
        className="flex h-10 w-10 cursor-pointer items-center justify-center rounded-lg bg-(--bg-card) text-(--color-text) transition-colors hover:bg-(--bg-key) focus-visible:ring-2 focus-visible:ring-(--color-text) focus-visible:outline-none"
        aria-label={label}
      >
        {icon}
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute top-full right-0 mt-2 whitespace-nowrap rounded-md bg-(--bg-key) px-2 py-1 text-xs text-(--color-text) opacity-0 shadow-md transition-opacity duration-(--motion-fast) group-hover:opacity-100 group-focus-within:opacity-100"
      >
        {tooltip}
      </span>
    </div>
  )
}

function distance(a: Touch | ReactTouch, b: Touch | ReactTouch): number {
  return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)
}

export function ImageLightbox({
  src,
  alt,
  isOpen,
  onClose,
  allowDownload = true,
  images,
  initialIndex = 0,
}: ImageLightboxProps) {
  const gallery = images?.length ? images : [{ src, alt }]
  const gallerySize = gallery.length
  const boundedInitialIndex = Math.min(Math.max(initialIndex, 0), gallerySize - 1)
  const [activeIndex, setActiveIndex] = useState(boundedInitialIndex)
  const [scale, setScale] = useState(1)
  const [translateY, setTranslateY] = useState(0)
  const touchStartYRef = useRef(0)
  const pinchStartDistanceRef = useRef<number | null>(null)
  const lastTapRef = useRef(0)

  const activeImage = gallery[activeIndex] ?? gallery[boundedInitialIndex] ?? { src, alt }

  // Keyboard navigation + body-scroll lock while open.
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setActiveIndex(boundedInitialIndex)
        setScale(1)
        setTranslateY(0)
        onClose()
        return
      }
      if (e.key === 'ArrowLeft') {
        setActiveIndex((current) => Math.max(0, current - 1))
        setScale(1)
        setTranslateY(0)
      }
      if (e.key === 'ArrowRight') {
        setActiveIndex((current) => Math.min(gallerySize - 1, current + 1))
        setScale(1)
        setTranslateY(0)
      }
    }

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [boundedInitialIndex, gallerySize, isOpen, onClose])

  const navigateTo = (index: number) => {
    setActiveIndex(Math.min(Math.max(index, 0), gallerySize - 1))
    setScale(1)
    setTranslateY(0)
    pinchStartDistanceRef.current = null
  }

  const closeLightbox = () => {
    setActiveIndex(boundedInitialIndex)
    setScale(1)
    setTranslateY(0)
    pinchStartDistanceRef.current = null
    onClose()
  }

  const handleTouchStart = (event: TouchEvent) => {
    if (event.touches.length === 1) {
      touchStartYRef.current = event.touches[0]?.clientY ?? 0
      pinchStartDistanceRef.current = null
      return
    }
    if (event.touches.length >= 2) {
      pinchStartDistanceRef.current = distance(event.touches[0], event.touches[1])
    }
  }

  const handleTouchMove = (event: TouchEvent) => {
    if (event.touches.length >= 2 && pinchStartDistanceRef.current) {
      const nextDistance = distance(event.touches[0], event.touches[1])
      const ratio = nextDistance / pinchStartDistanceRef.current
      setScale(Math.min(4, Math.max(1, ratio)))
      return
    }
    if (event.touches.length === 1 && scale <= 1.05) {
      const deltaY = (event.touches[0]?.clientY ?? 0) - touchStartYRef.current
      if (deltaY > 0) setTranslateY(Math.min(160, deltaY))
    }
  }

  const handleTouchEnd = () => {
    if (translateY > 80 && scale <= 1.05) {
      closeLightbox()
      return
    }
    setTranslateY(0)
    pinchStartDistanceRef.current = null
  }

  const handleDoubleClick = () => {
    setScale((current) => (current > 1 ? 1 : 2))
  }

  const handleImageClick = () => {
    const now = Date.now()
    if (now - lastTapRef.current < 300) handleDoubleClick()
    lastTapRef.current = now
  }

  const handleDownload = async () => {
    const filename = filenameFromSrc(activeImage.src, activeImage.alt)
    try {
      // Fetch as blob so the browser honors the `download` attribute even
      // for cross-origin or same-origin URLs that lack Content-Disposition.
      const response = await fetch(activeImage.src)
      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objectUrl
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(objectUrl)
    } catch {
      // Fallback: direct link (may navigate instead of download for cross-origin).
      const a = document.createElement('a')
      a.href = activeImage.src
      a.download = filename
      a.target = '_blank'
      a.rel = 'noopener noreferrer'
      document.body.appendChild(a)
      a.click()
      a.remove()
    }
  }

  if (!isOpen) return null

  return createPortal(
    <div
      className="mobile-safe-overlay fixed inset-0 z-(--z-modal) flex items-center justify-center bg-(--color-overlay) backdrop-blur-sm transition-opacity duration-(--motion-base)"
      onClick={closeLightbox}
      role="dialog"
      aria-modal="true"
      aria-label="Image lightbox"
    >
      {/* Action buttons — stopPropagation so clicking them doesn't close the overlay. */}
      <div
        className="absolute right-[max(1rem,env(safe-area-inset-right,0px))] top-[max(1rem,env(safe-area-inset-top,0px))] flex items-center gap-2 [[data-mobile-shell='ios']_&]:top-[max(4rem,calc(env(safe-area-inset-top)+1rem))]"
        onClick={(e) => e.stopPropagation()}
      >
        {allowDownload && (
          <LightboxIconButton
            onClick={handleDownload}
            icon={<Download size={20} />}
            label="Download image"
            tooltip="Download"
          />
        )}
        <LightboxIconButton
          onClick={closeLightbox}
          icon={<X size={20} />}
          label="Close lightbox"
          tooltip="Close (Esc)"
        />
      </div>

      {gallerySize > 1 && (
        <>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              navigateTo(activeIndex - 1)
            }}
            disabled={activeIndex === 0}
            className="absolute left-[max(0.75rem,env(safe-area-inset-left,0px))] top-1/2 flex size-11 -translate-y-1/2 items-center justify-center rounded-full bg-(--bg-card)/90 text-(--color-text) shadow-lg backdrop-blur-sm transition-[background-color,opacity,transform] hover:bg-(--bg-key) active:scale-95 disabled:cursor-default disabled:opacity-25"
            aria-label="Previous image"
            title="Previous image (Left arrow)"
          >
            <ChevronLeft size={24} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              navigateTo(activeIndex + 1)
            }}
            disabled={activeIndex === gallerySize - 1}
            className="absolute right-[max(0.75rem,env(safe-area-inset-right,0px))] top-1/2 flex size-11 -translate-y-1/2 items-center justify-center rounded-full bg-(--bg-card)/90 text-(--color-text) shadow-lg backdrop-blur-sm transition-[background-color,opacity,transform] hover:bg-(--bg-key) active:scale-95 disabled:cursor-default disabled:opacity-25"
            aria-label="Next image"
            title="Next image (Right arrow)"
          >
            <ChevronRight size={24} aria-hidden="true" />
          </button>
          <span className="absolute bottom-[max(1rem,env(safe-area-inset-bottom,0px))] left-1/2 -translate-x-1/2 rounded-full bg-(--bg-card)/90 px-3 py-1 text-xs tabular-nums text-(--color-text-muted) shadow-sm backdrop-blur-sm">
            {activeIndex + 1} / {gallerySize}
          </span>
        </>
      )}

      {/* Image container — stops backdrop-click propagation so a click on
          the image itself doesn't close the overlay. */}
      <div
        className="flex max-h-[75vh] max-w-[75vw] touch-none flex-col items-center justify-center"
        onClick={(e) => e.stopPropagation()}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onDoubleClick={handleDoubleClick}
      >
        <img
          key={activeImage.src}
          src={activeImage.src}
          alt={activeImage.alt}
          className="max-h-[75vh] max-w-[75vw] rounded-lg object-contain shadow-2xl transition-transform duration-(--motion-fast)"
          style={{ transform: `translateY(${translateY}px) scale(${scale})` }}
          onClick={handleImageClick}
        />
        {activeImage.alt && (
          <p className="mt-4 text-center text-sm text-(--color-text-muted)">
            {activeImage.alt}
          </p>
        )}
      </div>
    </div>,
    document.body,
  )
}
