/**
 * AimSidePanel — shared shell for AIM's right-hand side panels
 * (Discussion, Run Monitor, Unit detail): a resizable column with the
 * same drag-handle affordance as the sidebars and the coding file
 * viewer. Width persists per storageKey, so the Discussion keeps its
 * size across Pipelines and Runs & Reports.
 */

import { useResizableWidth } from '@/hooks/use-resizable-width'

export function AimSidePanel({
  storageKey,
  defaultWidth = 384,
  minWidth = 300,
  maxWidth = 760,
  children,
}: {
  storageKey: string
  defaultWidth?: number
  minWidth?: number
  maxWidth?: number
  children: React.ReactNode
}) {
  const resizable = useResizableWidth({
    storageKey,
    defaultWidth,
    minWidth,
    maxWidth,
    edge: 'left',
  })

  return (
    <div
      className="relative flex shrink-0 flex-col border-l border-(--color-border)"
      style={{ width: resizable.width, minWidth: resizable.width }}
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panel"
        title="Drag to resize · double-click to reset"
        className="absolute left-0 top-0 z-20 h-full w-1 cursor-col-resize transition-colors hover:bg-(--color-accent)/40"
        onPointerDown={resizable.startResize}
        onDoubleClick={resizable.resetWidth}
      />
      {children}
    </div>
  )
}
