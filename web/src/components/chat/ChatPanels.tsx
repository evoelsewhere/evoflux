/**
 * ChatPanels — the side panels and fixed overlays mounted by TeamChatView
 * (extracted, unchanged, from its layout).
 *
 *   - ``ChatTrailingPanels`` — rendered after <main> inside AppShell's body
 *     row: PlanReviewPanel, BrowserViewer, TerminalPanel.
 *     Coding workspace / file viewer live in ``fullHeightTrailing`` (same
 *     slot as Work's WorkspaceFilesPanel) so they cover the right corner
 *     beside the main card instead of sitting under the topbar.
 *   - ``ChatOverlayPanels`` — rendered after the body row (fixed-position —
 *     DOM order only matters for z-stacking): CommandPalette.
 *     WikiPanel and SchedulerPanel moved to the route root (``__root.tsx``) so they open in every mode.
 *
 * Props-driven; every conditional and the exact DOM order are preserved.
 */
import { PlanReviewPanel } from '../PlanReviewPanel'
import { ChangesReviewPanel } from '../ChangesReviewPanel'
import { ChangeSetReviewPanel } from '../ChangeSetReviewPanel'
import { CommandPalette, type Command } from '../CommandPalette'

interface ChatTrailingPanelsProps {
  onQuoteComment: (quote: string, comment: string) => void
  workspace?: string | null
  mode?: 'work' | 'coding'
  onOpenChangedFile?: (path: string) => void
}

// Side panels rendered after <main> inside AppShell's body row.
export function ChatTrailingPanels({
  onQuoteComment,
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
      <ChangeSetReviewPanel />
    </>
  )
}

interface ChatOverlayPanelsProps {
  showPalette: boolean
  paletteCommands: Command[]
  searchPaletteCommands?: (query: string, signal: AbortSignal) => Promise<Command[]>
  onClosePalette: () => void
}

// Modals rendered after the body row (fixed-position —
// DOM order only matters for z-stacking).
export function ChatOverlayPanels({
  showPalette,
  paletteCommands,
  searchPaletteCommands,
  onClosePalette,
}:ChatOverlayPanelsProps) {
  return (
    <>
      {showPalette && (
        <CommandPalette
          commands={paletteCommands}
          searchCommands={searchPaletteCommands}
          onClose={onClosePalette}
        />
      )}
    </>
  )
}
