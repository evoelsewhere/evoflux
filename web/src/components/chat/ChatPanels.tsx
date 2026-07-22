/**
 * ChatPanels — the side panels and fixed overlays mounted by TeamChatView
 * (extracted, unchanged, from its layout).
 *
 *   - ``ChatTrailingPanels`` — rendered after <main> inside AppShell's body
 *     row: PlanReviewPanel, the Activity aside, coding workbench /
 *     file viewer, WorkspaceFilesPanel, BrowserViewer, TerminalPanel.
 *     Every panel except BrowserViewer and the terminal now shares the
 *     ``SidePanel`` chrome (persisted resize, width animation, mobile
 *     overlay pattern).
 *   - ``ChatOverlayPanels`` — rendered after the body row (fixed-position —
 *     DOM order only matters for z-stacking): CommandPalette,
 *     RunInputsDialog, FloatingTodosPanel. WikiPanel and SchedulerPanel
 *     moved to the route root (``__root.tsx``) so they open in every mode.
 *
 * Props-driven; every conditional and the exact DOM order are preserved.
 */
import { AnimatePresence } from 'framer-motion'
import { PlanReviewPanel } from '../PlanReviewPanel'
import { ActivityPanel } from '../ActivityPanel'
import { CodingFileViewerPanel } from '../CodingFileViewerPanel'
import { CodingWorkspacePanel } from '../CodingWorkspacePanel'
import { BrowserViewer } from '../BrowserViewer'
import { TerminalPanel } from '../TerminalPanel'
import { CommandPalette, type Command } from '../CommandPalette'
import { RunInputsDialog, type RunInputsRequest } from '../RunInputsDialog'
import { FloatingTodosPanel } from '../FloatingTodosPanel'
import { SidePanel } from '@/components/shell/SidePanel'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import type { useResizableWidth } from '@/hooks/use-resizable-width'
import type { TodoItem, WorkspaceFileInfo } from '@/api/types'

interface ChatTrailingPanelsProps {
  mode: 'forge' | 'coding' | 'aim'
  workspace: string | null
  isMobile: boolean
  sessionId: string | null
  projectId: string | null
  isWorking: boolean
  onQuoteComment: (quote: string, comment: string) => void
  showActivity: boolean
  onCloseActivity: () => void
  codingFileViewer: WorkspaceFileInfo | null
  onCloseCodingFileViewer: () => void
  onAddFileComment: (path: string, startLine: number, endLine: number) => void
  onSendToChat: (action: string, code: string, path: string, startLine: number, endLine: number) => void
  codingPanel: 'changed' | 'files' | null
  onCodingFileSelect: (file: WorkspaceFileInfo | null) => void
  onCloseCodingPanel: () => void
  browserOpen: boolean
  onCloseBrowser: () => void
  terminalOpen: boolean
  onCloseTerminal: () => void
  terminalResize: ReturnType<typeof useResizableWidth>
}

// Side panels rendered after <main> inside AppShell's body row.
export function ChatTrailingPanels({
  mode,
  workspace,
  isMobile,
  sessionId,
  projectId,
  isWorking,
  onQuoteComment,
  showActivity,
  onCloseActivity,
  codingFileViewer,
  onCloseCodingFileViewer,
  onAddFileComment,
  onSendToChat,
  codingPanel,
  onCodingFileSelect,
  onCloseCodingPanel,
  browserOpen,
  onCloseBrowser,
  terminalOpen,
  onCloseTerminal,
  terminalResize,
}: ChatTrailingPanelsProps) {
  return (
    <>
      <PlanReviewPanel onQuoteComment={onQuoteComment} />
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
      {mode === 'coding' && workspace && codingFileViewer !== null && (
        <CodingFileViewerPanel
          workspace={codingFileViewer.sourceWorkspace ?? workspace}
          file={codingFileViewer}
          mobile={isMobile}
          onAddComment={onAddFileComment}
          onSendToChat={onSendToChat}
          onClose={onCloseCodingFileViewer}
        />
      )}
      {mode === 'coding' && workspace && codingPanel !== null && (
        <CodingWorkspacePanel
          key={codingPanel}
          workspace={workspace}
          open
          initialTab={codingPanel}
          mobile={isMobile}
          selectedFilePath={codingFileViewer?.path ?? null}
          onFileSelect={onCodingFileSelect}
          onClose={onCloseCodingPanel}
          sessionId={sessionId}
          projectId={projectId}
          isWorking={isWorking}
        />
      )}
      <BrowserViewer
        sessionId={sessionId}
        open={browserOpen}
        onClose={onCloseBrowser}
      />
      {terminalOpen && (
        <aside
          className="relative flex h-full shrink-0 flex-col"
          style={{ width: terminalResize.width }}
        >
          <div
            onPointerDown={terminalResize.startResize}
            onDoubleClick={terminalResize.resetWidth}
            className="absolute -left-1 top-0 z-(--z-panel) h-full w-2 cursor-col-resize"
            aria-hidden="true"
          />
          <TerminalPanel
            sessionId={sessionId}
            mode={mode}
            onClose={onCloseTerminal}
          />
        </aside>
      )}
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
  todos: TodoItem[]
}

// Modals / floating panels rendered after the body row (fixed-position —
// DOM order only matters for z-stacking).
export function ChatOverlayPanels({
  showPalette,
  paletteCommands,
  onClosePalette,
  runInputsRequest,
  onCancelRunInputs,
  onRunInputs,
  todos,
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
      <FloatingTodosPanel todos={todos} />
    </>
  )
}
