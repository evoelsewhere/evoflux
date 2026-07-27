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

import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import { X } from 'lucide-react'
import { useIsMobile } from '@/hooks/use-mobile'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import { useResizableWidth } from '@/hooks/use-resizable-width'
import { panelTransition, useMotionPreset } from '@/lib/motion'
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
  /** Force a viewport overlay even above the normal mobile breakpoint. */
  forceOverlay?: boolean
  /** Desktop right-edge drawer that overlays content without shrinking it. */
  desktopOverlay?: boolean
  /** Extra right offset for desktop overlays so sibling drawers can sit beside each other. */
  desktopOverlayOffset?: number
  /** Whether a desktop overlay keeps its drop shadow. */
  desktopOverlayShadow?: boolean
  /**
   * When true the panel renders as a normal relative flex column (no fixed
   * positioning) so it can sit inside a parent fixed container alongside
   * a sibling overlay panel without offset arithmetic.
   */
  desktopOverlayInner?: boolean
  /**
   * Fill an existing workbench surface. The parent owns resizing and
   * animation, so this panel becomes a plain relative content container.
   */
  fillParent?: boolean
  /** Mobile state for a `mobileOverlay` panel — defaults to useIsMobile(). */
  mobile?: boolean
  /**
   * Width open/close + drag animation. Pass false for panels that never
   * animated before (AIM) — width changes then apply instantly.
   */
  animated?: boolean
  /**
   * Pinned width override for callers that need a fixed panel size. Wins
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
  /** Emits the current panel width so sibling overlays can align beside it. */
  onWidthChange?: (width: number) => void
  children: ReactNode
}

export function SidePanel({
  storageKey,
  defaultWidth,
  minWidth,
  maxWidth,
  mobileOverlay = false,
  forceOverlay = false,
  desktopOverlay = false,
  desktopOverlayOffset = 0,
  desktopOverlayShadow = true,
  desktopOverlayInner = false,
  fillParent = false,
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
  onWidthChange,
  children,
}: SidePanelProps) {
  const detectedMobile = useIsMobile()
  const prefersReducedMotion = useReducedMotion()
  const motionPreset = useMotionPreset()
  const breakpointOverlay = mobileOverlay && (mobileProp ?? detectedMobile)
  const overlay = !fillParent && (forceOverlay || breakpointOverlay)
  const fixedDesktopDrawer = desktopOverlay && !overlay && !desktopOverlayInner
  const resizable = useResizableWidth({
    storageKey,
    defaultWidth,
    minWidth,
    maxWidth,
    edge: 'left',
    disabled: overlay || fillParent,
  })
  const width = widthOverride ?? resizable.width
  const isResizing = resizable.isResizing

  useEffect(() => {
    onWidthChange?.(width)
  }, [onWidthChange, width])

  // For desktopOverlayInner panels, apply width directly via style (bypassing
  // framer-motion's spring animation) so resize drag is always instant.
  // The wrapper fixed container in TeamChatView handles open/close visuals.
  const isInner = (desktopOverlayInner && !overlay) || fillParent
  const fade = prefersReducedMotion || overlay
  const hasHeader = title != null || headerActions != null || onClose != null
  const travel = 14 * motionPreset.distance
  const panelStyle = fillParent
    ? { width: '100%' }
    : overlay
    ? { width: '100%' }
    : fixedDesktopDrawer
    ? { right: desktopOverlayOffset, width }
    : isInner
    ? { width }
    : undefined

  return (
    <motion.aside
      layout={isInner || isResizing ? false : 'size'}
      style={panelStyle}
      initial={
        isInner || !animated
          ? false
          : fade
            ? { opacity: 0, x: travel }
            : { width: 0, opacity: 0, x: travel * 0.5 }
      }
      animate={
        isInner
          ? undefined
          : fade
            ? { opacity: 1, x: 0 }
            : { width, opacity: 1, x: 0 }
      }
      exit={
        isInner
          ? undefined
          : fade
            ? { opacity: 0, x: travel }
            : { width: 0, opacity: 0, x: travel * 0.5 }
      }
      transition={
        isInner || !animated
          ? { duration: 0 }
          : isResizing
          ? { duration: 0 }
          : fade
            ? motionPreset.transition
            : panelTransition(motionPreset)
      }
      className={cn(
        fillParent
          ? 'relative box-border flex h-full min-h-0 min-w-0 w-full flex-col overflow-hidden'
          : forceOverlay
          ? 'fixed inset-0 z-(--z-overlay) box-border min-h-0 min-w-0 w-full max-w-none overflow-hidden border-l border-(--color-border) shadow-xl'
          : fixedDesktopDrawer
          ? cn(
              'fixed inset-y-0 right-0 z-(--z-overlay) box-border flex min-h-0 min-w-0 shrink-0 flex-col overflow-hidden border-l border-(--color-border)',
              desktopOverlayShadow ? 'shadow-xl' : 'shadow-none',
            )
          : desktopOverlayInner && !overlay
          ? 'relative box-border flex h-full min-h-0 min-w-0 shrink-0 flex-col border-l border-(--color-border)'
          : mobileOverlay
          ? 'fixed bottom-0 right-0 z-(--z-overlay) box-border min-h-0 min-w-0 w-full overflow-hidden border-l border-(--color-border) shadow-xl md:relative md:inset-y-auto md:right-auto md:z-auto md:w-auto md:shrink-0 md:shadow-none'
          : 'relative box-border flex h-full min-w-0 shrink-0 flex-col overflow-hidden border-l border-(--color-border)',
        breakpointOverlay && !forceOverlay && 'mobile-safe-top max-w-none',
        forceOverlay && 'max-w-none',
        className,
      )}
      aria-label={ariaLabel}
    >
      {/* Resize handle sits outside the overflow-hidden content wrapper so
          it is never clipped and always receives pointer events. */}
      {!fillParent && !overlay && widthOverride === undefined && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={resizeLabel}
          title="Drag to resize · double-click to reset"
          className={cn(
            'absolute top-0 h-full cursor-col-resize transition-colors hover:bg-(--color-accent)/40',
            desktopOverlayInner && !overlay
              ? '-left-1 z-(--z-overlay) w-2'
              : 'left-0 z-(--z-header) w-1',
          )}
          onPointerDown={resizable.startResize}
          onDoubleClick={resizable.resetWidth}
        />
      )}
      <div
        className={cn(
          'relative flex h-full min-h-0 min-w-0 w-full flex-col overflow-hidden',
          mobileOverlay && (overlay ? 'max-w-none' : 'md:w-full'),
          contentClassName,
        )}
      >
        {hasHeader && (
          <motion.div
            layout="position"
            className="flex shrink-0 items-center justify-between px-3 py-2"
          >
            {typeof title === 'string' ? (
              <span className="text-xs font-semibold text-(--color-text-2)">{title}</span>
            ) : (
              title
            )}
            <div className="flex items-center gap-1">
              {headerActions}
              {onClose && (
                <motion.button
                  type="button"
                  onClick={onClose}
                  whileHover={{ scale: 1.06 }}
                  whileTap={{ scale: 0.9 }}
                  transition={motionPreset.spring}
                  aria-label={closeLabel}
                  className="focus-ring-control press-control flex h-5 w-5 items-center justify-center rounded-md text-(--color-text-muted) hover:text-(--color-text)"
                >
                  <X size={12} aria-hidden="true" />
                </motion.button>
              )}
            </div>
          </motion.div>
        )}
        {children}
      </div>
    </motion.aside>
  )
}
