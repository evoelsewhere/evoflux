import { Wrench } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { cn } from '@/lib/utils'
import type { UserMessageNavigationItem } from '@/utils/user-message-navigation'

export const USER_MESSAGE_NAVIGATION_MIN_ITEMS = 2
const ACTIVE_THRESHOLD_PX = 160
const SCRUB_START_DELTA_PX = 4

interface UserMessageNavigationRailProps {
  items: UserMessageNavigationItem[]
  containerRef: React.RefObject<HTMLDivElement | null>
  isWorking?: boolean
  onNavigate: (messageId: string, behavior: ScrollBehavior) => void
}

interface DragState {
  pointerId: number
  startY: number
  didScrub: boolean
}

interface PreviewPosition {
  left: number
  top: number
}

function findMessageAnchor(
  container: HTMLDivElement,
  messageId: string,
): HTMLElement | null {
  for (const element of container.querySelectorAll<HTMLElement>(
    '[data-user-message-navigation-anchor]',
  )) {
    if (element.dataset.userMessageNavigationAnchor === messageId) return element
  }
  return null
}

function messageIdFromElement(element: Element | null): string | null {
  return element
    ?.closest<HTMLElement>('[data-user-message-navigation-id]')
    ?.dataset.userMessageNavigationId ?? null
}

function markerWidthClass(distance: number, active: boolean): string {
  if (distance === 0 || (distance < 0 && active)) return 'w-8'
  if (distance === 1) return 'w-6'
  if (distance === 2) return 'w-4'
  if (distance === 3) return 'w-3'
  return 'w-2'
}

export function UserMessageNavigationRail({
  items,
  containerRef,
  isWorking = false,
  onNavigate,
}: UserMessageNavigationRailProps) {
  const [activeMessageId, setActiveMessageId] = useState<string | null>(
    items.at(-1)?.id ?? null,
  )
  const activeMessageIdRef = useRef(activeMessageId)
  const [previewMessageId, setPreviewMessageId] = useState<string | null>(null)
  const [previewPosition, setPreviewPosition] = useState<PreviewPosition | null>(null)
  const dragRef = useRef<DragState | null>(null)
  const suppressClickRef = useRef(false)
  const tooltipId = useId()

  const updateActiveMessage = useCallback(() => {
    const container = containerRef.current
    if (!container || items.length === 0) return

    const threshold = container.getBoundingClientRect().top
      + Math.min(ACTIVE_THRESHOLD_PX, container.clientHeight * 0.3)
    let nextMessageId: string | null = null

    for (const item of items) {
      const anchor = findMessageAnchor(container, item.id)
      if (!anchor) continue
      if (nextMessageId === null) nextMessageId = item.id
      if (anchor.getBoundingClientRect().top <= threshold) {
        nextMessageId = item.id
      } else {
        break
      }
    }

    if (nextMessageId && activeMessageIdRef.current !== nextMessageId) {
      activeMessageIdRef.current = nextMessageId
      setActiveMessageId(nextMessageId)
    }
  }, [containerRef, items])

  useEffect(() => {
    const container = containerRef.current
    if (!container || items.length < USER_MESSAGE_NAVIGATION_MIN_ITEMS) return

    let frame = requestAnimationFrame(updateActiveMessage)
    const scheduleUpdate = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(updateActiveMessage)
    }

    container.addEventListener('scroll', scheduleUpdate, { passive: true })
    window.addEventListener('resize', scheduleUpdate)
    return () => {
      cancelAnimationFrame(frame)
      container.removeEventListener('scroll', scheduleUpdate)
      window.removeEventListener('resize', scheduleUpdate)
    }
  }, [containerRef, items.length, updateActiveMessage])

  const openPreview = useCallback((messageId: string, element: Element | null) => {
    const marker = element?.closest<HTMLElement>('[data-user-message-navigation-id]')
    if (marker) {
      const rect = marker.getBoundingClientRect()
      setPreviewPosition({
        left: Math.max(12, Math.min(rect.right + 8, window.innerWidth - 300)),
        top: Math.max(72, Math.min(rect.top + rect.height / 2, window.innerHeight - 72)),
      })
    }
    setPreviewMessageId(messageId)
  }, [])

  const navigateFromElement = useCallback((element: Element | null) => {
    const messageId = messageIdFromElement(element)
    if (!messageId) return
    openPreview(messageId, element)
    onNavigate(messageId, 'auto')
  }, [onNavigate, openPreview])

  if (items.length < USER_MESSAGE_NAVIGATION_MIN_ITEMS) return null

  const previewIndex = items.findIndex((item) => item.id === previewMessageId)
  const previewItem = previewIndex >= 0 ? items[previewIndex] : null

  return (
    <>
      <nav
        aria-label="User messages"
        className="pointer-events-none absolute inset-y-5 left-2 z-(--z-panel) hidden w-12 items-center @[48rem]/agent-view:flex"
      >
        <div
          className="pointer-events-auto flex max-h-[min(70vh,40rem)] w-10 touch-none flex-col overflow-y-auto overscroll-contain py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          data-user-message-navigation-rail
          onPointerDown={(event) => {
            if (event.button !== 0) return
            const messageId = messageIdFromElement(
              event.target instanceof Element ? event.target : null,
            )
            if (!messageId) return
            dragRef.current = {
              pointerId: event.pointerId,
              startY: event.clientY,
              didScrub: false,
            }
            event.currentTarget.setPointerCapture?.(event.pointerId)
            openPreview(
              messageId,
              event.target instanceof Element ? event.target : null,
            )
          }}
          onPointerMove={(event) => {
            const drag = dragRef.current
            if (!drag || drag.pointerId !== event.pointerId) return
            if (!drag.didScrub && Math.abs(event.clientY - drag.startY) < SCRUB_START_DELTA_PX) {
              return
            }
            drag.didScrub = true
            const pointedElement = document.elementFromPoint?.(
              event.clientX,
              event.clientY,
            ) ?? null
            navigateFromElement(pointedElement)
          }}
          onPointerUp={(event) => {
            const drag = dragRef.current
            if (!drag || drag.pointerId !== event.pointerId) return
            dragRef.current = null
            event.currentTarget.releasePointerCapture?.(event.pointerId)
            setPreviewMessageId(null)
            if (drag.didScrub) {
              suppressClickRef.current = true
              window.setTimeout(() => {
                suppressClickRef.current = false
              }, 0)
            }
          }}
          onPointerCancel={() => {
            dragRef.current = null
            setPreviewMessageId(null)
          }}
          onPointerLeave={() => {
            if (!dragRef.current) setPreviewMessageId(null)
          }}
        >
          {items.map((item, index) => {
            const active = item.id === activeMessageId
            const previewing = item.id === previewMessageId
            const distance = previewIndex >= 0 ? Math.abs(index - previewIndex) : -1
            return (
              <button
                key={item.id}
                type="button"
                data-user-message-navigation-id={item.id}
                aria-current={active ? 'location' : undefined}
                aria-describedby={previewing ? tooltipId : undefined}
                aria-label={`Jump to user message ${index + 1}`}
                className="group flex h-2.5 w-10 shrink-0 cursor-pointer items-center outline-none"
                onClick={() => {
                  if (suppressClickRef.current) return
                  setPreviewMessageId(null)
                  onNavigate(item.id, 'smooth')
                }}
                onMouseEnter={(event) => openPreview(item.id, event.currentTarget)}
                onFocus={(event) => openPreview(item.id, event.currentTarget)}
                onBlur={() => setPreviewMessageId(null)}
              >
                <span
                  className={cn(
                    'h-0.5 rounded-full transition-[width,background-color,opacity] duration-(--motion-fast)',
                    markerWidthClass(distance, active),
                    previewing
                      ? 'bg-(--color-text) opacity-100'
                      : active
                        ? 'bg-(--color-text) opacity-70'
                        : 'bg-(--color-text-muted) opacity-45 group-focus-visible:bg-(--color-text) group-focus-visible:opacity-100',
                  )}
                />
              </button>
            )
          })}
        </div>
      </nav>

      {previewItem && previewPosition && createPortal(
        <div
          id={tooltipId}
          role="tooltip"
          style={{ left: previewPosition.left, top: previewPosition.top }}
          className="pointer-events-none fixed z-(--z-modal) w-[min(18rem,calc(100vw-1.5rem))] -translate-y-1/2 overflow-hidden rounded-lg border border-(--color-border-strong) bg-(--bg-card)/75 p-2.5 text-xs shadow-lg backdrop-blur-2xl"
        >
          <p className="truncate font-medium text-(--color-text)">
            {previewItem.label}
          </p>
          {previewItem.response ? (
            <p className="mt-1 line-clamp-2 whitespace-pre-line leading-relaxed text-(--color-text-muted)">
              {previewItem.response}
            </p>
          ) : isWorking && previewIndex === items.length - 1 ? (
            <p className="mt-1 text-(--color-text-subtle)">Preparing a response…</p>
          ) : null}
          {previewItem.toolNames.length > 0 && (
            <div className="mt-2 flex min-w-0 items-center gap-2 text-xs text-(--color-text-subtle)">
              <Wrench size={12} className="shrink-0" aria-hidden="true" />
              <span className="truncate">{previewItem.toolNames.slice(0, 2).join(' · ')}</span>
              {previewItem.toolNames.length > 2 && (
                <span className="shrink-0 tabular-nums">+{previewItem.toolNames.length - 2}</span>
              )}
            </div>
          )}
        </div>,
        document.body,
      )}
    </>
  )
}
