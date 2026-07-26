import { AnimatePresence, motion } from 'framer-motion'
import { Trash2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useDeleteChapter } from '@/hooks/useSessionChapters'
import { useMotionPreset } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { Chapter } from '@/api/types'

interface SessionChapterRailProps {
  chapters: Chapter[]
  containerRef: React.RefObject<HTMLDivElement | null>
  sessionId: string | null | undefined
}

function findChapterAnchor(
  container: HTMLDivElement,
  messageId: string,
): HTMLElement | null {
  for (const element of container.querySelectorAll<HTMLElement>('[data-chapter-anchor]')) {
    if (element.dataset.chapterAnchor === messageId) return element
  }
  return null
}

export function SessionChapterRail({
  chapters,
  containerRef,
  sessionId,
}: SessionChapterRailProps) {
  const anchoredChapters = useMemo(
    () => chapters.filter((chapter) => chapter.message_id),
    [chapters],
  )
  const [activeChapterId, setActiveChapterId] = useState<string | null>(null)
  const [previewChapterId, setPreviewChapterId] = useState<string | null>(null)
  const deleteMutation = useDeleteChapter(sessionId)
  const preset = useMotionPreset()

  const updateActiveChapter = useCallback(() => {
    const container = containerRef.current
    if (!container || anchoredChapters.length === 0) return

    const threshold = container.getBoundingClientRect().top
      + Math.min(160, container.clientHeight * 0.3)
    let nextChapterId = anchoredChapters[0]?.id ?? null

    for (const chapter of anchoredChapters) {
      const messageId = chapter.message_id
      if (!messageId) continue
      const anchor = findChapterAnchor(container, messageId)
      if (!anchor) continue
      if (anchor.getBoundingClientRect().top <= threshold) {
        nextChapterId = chapter.id
      } else {
        break
      }
    }

    setActiveChapterId((current) => current === nextChapterId ? current : nextChapterId)
  }, [anchoredChapters, containerRef])

  useEffect(() => {
    const container = containerRef.current
    if (!container || anchoredChapters.length === 0) return

    let frame = requestAnimationFrame(updateActiveChapter)
    const scheduleUpdate = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(updateActiveChapter)
    }

    container.addEventListener('scroll', scheduleUpdate, { passive: true })
    window.addEventListener('resize', scheduleUpdate)
    return () => {
      cancelAnimationFrame(frame)
      container.removeEventListener('scroll', scheduleUpdate)
      window.removeEventListener('resize', scheduleUpdate)
    }
  }, [anchoredChapters.length, containerRef, updateActiveChapter])

  const scrollToChapter = useCallback((chapter: Chapter) => {
    const container = containerRef.current
    if (!container || !chapter.message_id) return
    const anchor = findChapterAnchor(container, chapter.message_id)
    anchor?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setActiveChapterId(chapter.id)
  }, [containerRef])

  if (anchoredChapters.length === 0) return null

  return (
    <nav
      aria-label="Session chapters"
      className="pointer-events-none absolute inset-y-5 left-2 z-(--z-panel) hidden w-14 items-center lg:flex"
    >
      <div className="pointer-events-auto flex max-h-full flex-col gap-1.5 py-2">
        {anchoredChapters.map((chapter) => {
          const active = chapter.id === activeChapterId
          const previewing = chapter.id === previewChapterId
          return (
            <div
              key={chapter.id}
              className="relative flex h-3 items-center"
              onMouseEnter={() => setPreviewChapterId(chapter.id)}
              onMouseLeave={() => setPreviewChapterId(null)}
              onFocus={() => setPreviewChapterId(chapter.id)}
              onBlur={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget)) {
                  setPreviewChapterId(null)
                }
              }}
            >
              <button
                type="button"
                onClick={() => scrollToChapter(chapter)}
                aria-current={active ? 'location' : undefined}
                aria-label={`Go to chapter: ${chapter.title}`}
                className="group flex h-3 w-12 items-center outline-none"
              >
                <span
                  className={cn(
                    'h-1 rounded-full transition-[width,background-color] duration-(--motion-fast)',
                    active
                      ? 'w-12 bg-(--color-text)'
                      : 'w-2 bg-(--color-border-strong) group-hover:w-7 group-hover:bg-(--color-text-muted) group-focus-visible:w-7 group-focus-visible:bg-(--color-text-muted)',
                  )}
                />
              </button>

              <AnimatePresence>
                {previewing && (
                  <motion.div
                    role="tooltip"
                    initial={{ opacity: 0, x: -6 * preset.distance, scale: 0.98 }}
                    animate={{ opacity: 1, x: 0, scale: 1 }}
                    exit={{ opacity: 0, x: -4 * preset.distance, scale: 0.98 }}
                    transition={preset.spring}
                    className="absolute left-14 top-1/2 w-[clamp(20rem,42vw,36rem)] -translate-y-1/2 rounded-lg border border-(--color-border) bg-(--bg-card)/95 p-4 shadow-xl backdrop-blur-xl"
                  >
                    <div className="flex items-start gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-(--color-text)">
                          {chapter.title}
                        </p>
                        {chapter.summary && (
                          <p className="mt-2 line-clamp-3 whitespace-pre-line text-sm leading-relaxed text-(--color-text-muted)">
                            {chapter.summary}
                          </p>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation()
                          deleteMutation.mutate(chapter.id)
                        }}
                        disabled={deleteMutation.isPending}
                        aria-label={`Delete chapter: ${chapter.title}`}
                        title="Delete chapter"
                        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-(--color-text-subtle) outline-none transition-colors hover:bg-(--bg-key) hover:text-(--color-error) focus-visible:ring-2 focus-visible:ring-(--color-accent)/30 disabled:opacity-40"
                      >
                        <Trash2 size={14} aria-hidden="true" />
                      </button>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )
        })}
      </div>
    </nav>
  )
}