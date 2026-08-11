/**
 * AimSidePanel — shared shell for AIM's right-hand side panels
 * (Discussion, Run Monitor, Unit detail): a resizable column with the
 * same drag-handle affordance as the sidebars and the coding file
 * viewer. Width persists per storageKey, so the Discussion keeps its
 * size across Pipelines and Runs & Reports.
 *
 * Thin wrapper over the shared ``SidePanel`` chrome — open/close follows
 * the Appearance motion preset (instant under reduced).
 */

import { SidePanel } from '@/components/shell/SidePanel'

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
  return (
    <SidePanel
      storageKey={storageKey}
      defaultWidth={defaultWidth}
      minWidth={minWidth}
      maxWidth={maxWidth}
      mobileOverlay
      animated
      resizeLabel="Resize panel"
      className="bg-(--bg-page)"
    >
      {children}
    </SidePanel>
  )
}
