/**
 * SidePanel — the shared desktop chrome of the app's right-hand side panels
 * (plan review, activity, coding workspace / file viewer, workspace files,
 * AIM discussion / monitor / report / unit detail): the trailing-row mirror
 * of ``SidebarShell``.
 *
 * Extracted from panels that each hand-rolled the same mechanics. The shell
 * owns:
 *   - `useResizableWidth` (persisted width, pointer drag, dbl-click reset),
 *     always resizing from the panel's LEFT edge (`edge: 'left'`)
 *   - the resize-handle separator (aria-label + pointer logic unchanged)
 *   - the framer-motion width animation (0.22s, eased; reduced-motion aware)
 *   - the dual-mode mobile pattern the coding panels copy-pasted:
 *     `fixed bottom-0 right-0 z-(--z-overlay) … md:relative md:z-auto …` — a full-screen
 *     overlay below the md breakpoint, an in-flow flex sibling at md and up
 *     (pass `mobileOverlay`). In mobile mode the resize is disabled and the
 *     open/close animation degrades to a fade.
 *   - an optional standard header (title + optional actions + close button)
 *
 * It deliberately does NOT own panel content: bespoke headers, tab bars,
 * footers, and panel-specific conditionals stay in the caller's `children`.
 * The terminal aside keeps its own chrome (xterm wants tight control) and
 * BrowserViewer keeps its own drag handle — only their configs are shared.
 */

import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import { X } from 'lucide-react'
import { useIsMobile } from '@/hooks/use-mobile'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import { useResizableWidth } from '@/hooks/use-resizable-width'
import { cn } from '@/lib/utils'

interface SidePanelProps {
  /** localStorage key the resized width persists under. */
  storageKey: string
  defaultWidth: number
  minWidth: number
  maxWidth: number
  /**
   * Dual-mode layout: fixed full-screen overlay below the md breakpoint,
   * in-flow row sibling at md and up. Panels mounted only as desktop row
   * siblings (activity, AIM) leave this off.
   */
  mobileOverlay?: boolean
  /** Mobile state for a `mobileOverlay` panel — defaults to useIsMobile(). */
  mobile?: boolean
  /**
   * Width open/close + drag animation. Pass false for panels that never
   * animated before (AIM) — width changes then apply instantly.
   */
  animated?: boolean
  /**
   * Pinned width override (e.g. WorkspaceFilesPanel's expanded mode). Wins
   * over the resized width and hides the handle, since dragging a pinned
   * width would visibly do nothing.
   */
  width?: number
  /** Standard-header slot — render none of the three to skip the header. */
  title?: ReactNode
  headerActions?: ReactNode
  onClose?: () => void
  closeLabel?: string
  /** aria-label of the resize handle (each panel names itself). */
  resizeLabel?: string
  /** aria-label of the panel landmark itself. */
  ariaLabel?: string
  /** Extra classes on the outer aside (bg surface, mac insets, …). */
  className?: string
  /** Extra classes on the inner column wrapper (e.g. the traffic-light pt-10). */
  contentClassName?: string
  children: ReactNode
}

export function SidePanel({
  storageKey,
  defaultWidth,
  minWidth,
  maxWidth,
  mobileOverlay = false,
  mobile: mobileProp,
  animated = true,
  width: widthOverride,
  title,
  headerActions,
  onClose,
  closeLabel = 'Close panel',
  resizeLabel = 'Resize panel',
  ariaLabel,
  className,
  contentClassName,
  children,
}: SidePanelProps) {
  const detectedMobile = useIsMobile()
  const prefersReducedMotion = useReducedMotion()
  const mobile = mobileOverlay && (mobileProp ?? detectedMobile)
  const resizable = useResizableWidth({
    storageKey,
    defaultWidth,
    minWidth,
    maxWidth,
    edge: 'left',
    disabled: mobile,
  })
  const width = widthOverride ?? resizable.width

  // Mobile and reduced-motion both degrade the open/close animation to a
  // fade — width-tweening a full-screen overlay (or against the user's
  // motion preference) is wrong. Matches the panels' pre-extraction code.
  const fade = prefersReducedMotion || mobile
  const hasHeader = title != null || headerActions != null || onClose != null

  return (
    <motion.aside
      initial={!animated ? false : fade ? { opacity: 0 } : { width: 0 }}
      animate={fade ? { opacity: 1 } : { width }}
      exit={fade ? { opacity: 0 } : { width: 0 }}
      transition={
        animated
          ? { duration: prefersReducedMotion ? 0.01 : 0.22, ease: [0.4, 0, 0.2, 1] }
          : { duration: 0 }
      }
      className={cn(
        mobileOverlay
          ? 'fixed bottom-0 right-0 z-(--z-overlay) min-h-0 w-full overflow-hidden border-l border-(--color-border) shadow-xl md:relative md:inset-y-auto md:right-auto md:z-auto md:w-auto md:shrink-0 md:shadow-none'
          : 'relative flex h-full shrink-0 flex-col overflow-hidden border-l border-(--color-border)',
        mobile && 'mobile-safe-top max-w-none',
        className,
      )}
      aria-label={ariaLabel}
    >
      <div
        className={cn(
          'relative flex h-full min-h-0 w-full flex-col',
          mobileOverlay && (mobile ? 'max-w-none' : 'md:w-full'),
          contentClassName,
        )}
      >
        {!mobile && widthOverride === undefined && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label={resizeLabel}
            title="Drag to resize · double-click to reset"
            className="absolute left-0 top-0 z-(--z-header) h-full w-1 cursor-col-resize transition-colors hover:bg-(--color-accent)/40"
            onPointerDown={resizable.startResize}
            onDoubleClick={resizable.resetWidth}
          />
        )}
        {hasHeader && (
          <div className="flex shrink-0 items-center justify-between border-b border-(--color-border) px-3 py-2">
            {typeof title === 'string' ? (
              <span className="text-xs font-semibold text-(--color-text-2)">{title}</span>
            ) : (
              title
            )}
            <div className="flex items-center gap-1">
              {headerActions}
              {onClose && (
                <button
                  type="button"
                  onClick={onClose}
                  aria-label={closeLabel}
                  className="flex h-5 w-5 items-center justify-center rounded-md text-(--color-text-muted) hover:text-(--color-text)"
                >
                  <X size={12} aria-hidden="true" />
                </button>
              )}
            </div>
          </div>
        )}
        {children}
      </div>
    </motion.aside>
  )
}
