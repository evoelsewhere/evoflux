/**
 * ChatPanels — the side panels and fixed overlays mounted by TeamChatView
 * (extracted, unchanged, from its layout).
 *
 *   - ``ChatTrailingPanels`` — rendered after <main> inside AppShell's body
 *     row: PlanReviewPanel, Activity, BrowserViewer, TerminalPanel.
 *     Coding workspace / file viewer live in ``fullHeightTrailing`` (same
 *     slot as Work's WorkspaceFilesPanel) so they cover the right corner
 *     beside the main card instead of sitting under the topbar.
 *   - ``ChatOverlayPanels`` — rendered after the body row (fixed-position —
 *     DOM order only matters for z-stacking): CommandPalette,
 *     RunInputsDialog. WikiPanel and SchedulerPanel
 *     moved to the route root (``__root.tsx``) so they open in every mode.
 *
 * Props-driven; every conditional and the exact DOM order are preserved.
 */
import { AnimatePresence } from 'framer-motion'
import { PlanReviewPanel } from '../PlanReviewPanel'
import { ChangesReviewPanel } from '../ChangesReviewPanel'
import { ActivityPanel } from '../ActivityPanel'
import { CommandPalette, type Command } from '../CommandPalette'
import { RunInputsDialog, type RunInputsRequest } from '../RunInputsDialog'
import { SidePanel } from '@/components/shell/SidePanel'
import { STORAGE_KEYS } from '@/lib/storage-keys'

interface ChatTrailingPanelsProps {
  onQuoteComment: (quote: string, comment: string) => void
  showActivity: boolean
  onCloseActivity: () => void
  workspace?: string | null
  mode?: 'work' | 'coding'
  onOpenChangedFile?: (path: string) => void
}

// Side panels rendered after <main> inside AppShell's body row.
export function ChatTrailingPanels({
  onQuoteComment,
  showActivity,
  onCloseActivity,
  workspace,
  mode = 'work',
  onOpenChangedFile,
}: ChatTrailingPanelsProps) {
  return (
    <>
      <PlanReviewPanel onQuoteComment={onQuoteComment} />
      <ChangesReviewPanel
        workspace={workspace}
        mode={mode}
        onOpenFile={onOpenChangedFile}
      />
      <AnimatePresence>
        {showActivity && (
          <SidePanel
            key="activity-panel"
            storageKey={STORAGE_KEYS.panels.activity}
            defaultWidth={280}
            minWidth={240}
            maxWidth={480}
            title="Activity"
            onClose={onCloseActivity}
            closeLabel="Close activity panel"
            resizeLabel="Resize activity panel"
            className="bg-(--bg-page)"
          >
            <div className="min-h-0 flex-1">
              <ActivityPanel />
            </div>
          </SidePanel>
        )}
      </AnimatePresence>
    </>
  )
}

interface ChatOverlayPanelsProps {
  showPalette: boolean
  paletteCommands: Command[]
  onClosePalette: () => void
  runInputsRequest: RunInputsRequest | null
  onCancelRunInputs: () => void
  onRunInputs: (values: Record<string, unknown>) => Promise<void>
}

// Modals rendered after the body row (fixed-position —
// DOM order only matters for z-stacking).
export function ChatOverlayPanels({
  showPalette,
  paletteCommands,
  onClosePalette,
  runInputsRequest,
  onCancelRunInputs,
  onRunInputs,
}: ChatOverlayPanelsProps) {
  return (
    <>
      {showPalette && (
        <CommandPalette commands={paletteCommands} onClose={onClosePalette} />
      )}
      {runInputsRequest && (
        <RunInputsDialog
          request={runInputsRequest}
          onCancel={onCancelRunInputs}
          onRun={onRunInputs}
        />
      )}
    </>
  )
}
