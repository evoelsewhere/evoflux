/**
 * UnifiedSidebarDialogs — all dialogs and context menus for UnifiedSidebar.
 *
 * Extracted from UnifiedSidebar.tsx to reduce file size.
 * Receives state + handlers via a single props interface.
 */
import { Folder, GitBranch, Pencil, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { ProjectSetupModal } from "@/components/ProjectSetupModal";
import { workspaceLabel } from "@/utils/workspace";
import type { SessionResponse, WorktreeInfo } from "@/api/types";

// ── Types ────────────────────────────────────────────────────────────────────

interface WorkspaceActionBase {
  path: string;
  kind: "main" | "worktree";
  source?: string;
  worktree?: WorktreeInfo;
}

export interface WorkspaceAction extends WorkspaceActionBase {
  x: number;
  y: number;
}

export type MobileWorkspaceAction = WorkspaceActionBase;

export interface SessionAction {
  session: SessionResponse;
  x: number;
  y: number;
}

export interface UnifiedSidebarDialogsProps {
  // Edit session dialog
  editTarget: SessionResponse | null;
  setEditTarget: (target: SessionResponse | null) => void;
  editTitle: string;
  setEditTitle: (title: string) => void;
  submitSessionTitle: (e: React.FormEvent) => void;

  // Project modal
  showProjectModal: boolean;
  setShowProjectModal: (show: boolean) => void;

  // Workspace dialog
  dialogOpen: boolean;
  setDialogOpen: (open: boolean) => void;
  closeWorkspaceDialog: () => void;
  trustWorkspace: string | null;
  setTrustWorkspace: (ws: string | null) => void;
  nativeFolderPickerEnabled: boolean;
  isTauriMobile: boolean;
  selectedWorkspace: string | null;
  error: string | null;
  loading: boolean;
  browserPath: string | null;
  parentPath: string | null;
  dirs: Array<{ name: string; path: string }>;
  loadBrowser: (path?: string | null) => void;
  confirmTrustedWorkspace: () => void;
  openSelectedFolder: () => void;
  openWorkspaceDialog: () => void;

  // Mobile workspace actions
  mobileWorkspaceActions: MobileWorkspaceAction | null;
  setMobileWorkspaceActions: (actions: MobileWorkspaceAction | null) => void;
  selectWorkspace: (path: string, opts?: { create?: boolean }) => void;
  openWorktreeDialog: (path: string) => void;
  setRemoveWorkspaceTarget: (target: string | null) => void;

  // Mobile session actions
  mobileSessionActions: SessionResponse | null;
  setMobileSessionActions: (session: SessionResponse | null) => void;
  handleSessionEdit: (session: SessionResponse) => void;
  setPendingDeleteId: (id: string | null) => void;

  // Desktop workspace context menu
  desktopWorkspaceActions: WorkspaceAction | null;
  setDesktopWorkspaceActions: (actions: WorkspaceAction | null) => void;
  handleRemoveWorktree: (item: WorktreeInfo) => void;

  // Desktop session context menu
  desktopSessionActions: SessionAction | null;
  setDesktopSessionActions: (actions: SessionAction | null) => void;

  // Remove workspace confirmation
  removeWorkspaceTarget: string | null;
  confirmRemoveWorkspace: () => void;

  // Worktree creation dialog
  worktreeTarget: string | null;
  setWorktreeTarget: (target: string | null) => void;
  submitWorktree: (event: React.FormEvent) => void;
  worktreeName: string;
  setWorktreeName: (name: string) => void;
  worktreeBranch: string;
  setWorktreeBranch: (branch: string) => void;
  worktreeLoading: boolean;
}

// ── Component ────────────────────────────────────────────────────────────────

export function UnifiedSidebarDialogs({
  editTarget,
  setEditTarget,
  editTitle,
  setEditTitle,
  submitSessionTitle,
  showProjectModal,
  setShowProjectModal,
  dialogOpen,
  setDialogOpen,
  closeWorkspaceDialog,
  trustWorkspace,
  setTrustWorkspace,
  nativeFolderPickerEnabled,
  isTauriMobile,
  selectedWorkspace,
  error,
  loading,
  browserPath,
  parentPath,
  dirs,
  loadBrowser,
  confirmTrustedWorkspace,
  openSelectedFolder,
  openWorkspaceDialog,
  mobileWorkspaceActions,
  setMobileWorkspaceActions,
  selectWorkspace,
  openWorktreeDialog,
  setRemoveWorkspaceTarget,
  mobileSessionActions,
  setMobileSessionActions,
  handleSessionEdit,
  setPendingDeleteId,
  desktopWorkspaceActions,
  setDesktopWorkspaceActions,
  handleRemoveWorktree,
  desktopSessionActions,
  setDesktopSessionActions,
  removeWorkspaceTarget,
  confirmRemoveWorkspace,
  worktreeTarget,
  setWorktreeTarget,
  submitWorktree,
  worktreeName,
  setWorktreeName,
  worktreeBranch,
  setWorktreeBranch,
  worktreeLoading,
}: UnifiedSidebarDialogsProps) {
  return (
    <>
      {/* Edit session title dialog */}
      {editTarget && (
        <Dialog open={!!editTarget} onOpenChange={() => setEditTarget(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Rename session</DialogTitle>
              <DialogDescription>
                Enter a new name for this session.
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={submitSessionTitle}>
              <input
                type="text"
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                className="w-full rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-2 text-sm text-(--color-text) focus:outline-none focus:ring-2 focus:ring-(--color-accent)"
                placeholder="Session title"
                autoFocus
              />
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setEditTarget(null)}
                >
                  Cancel
                </Button>
                <Button type="submit">Save</Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      )}

      {/* Project setup modal */}
      {showProjectModal && (
        <ProjectSetupModal
          open={showProjectModal}
          onOpenChange={setShowProjectModal}
        />
      )}

      {/* Workspace dialog — trust flow from CodingSidebar */}
      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          if (!open) closeWorkspaceDialog();
          else setDialogOpen(true);
        }}
      >
        <DialogContent showCloseButton={false} className="min-w-0">
          {trustWorkspace ? (
            <>
              <DialogHeader>
                <DialogTitle>Trust this workspace?</DialogTitle>
                <DialogDescription>
                  Coding mode grants agents filesystem and shell access. The workspace directory is the primary working area, but agents may access other paths outside it (excluding system directories).
                </DialogDescription>
              </DialogHeader>
              <div className="rounded-lg border border-(--color-border) bg-(--bg-page) px-3 py-2">
                <p className="break-all font-mono text-xs text-(--color-text-muted)">
                  {trustWorkspace}
                </p>
              </div>
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setTrustWorkspace(null)}
                >
                  Back
                </Button>
                <Button type="button" onClick={confirmTrustedWorkspace}>
                  Trust and open
                </Button>
              </DialogFooter>
            </>
          ) : nativeFolderPickerEnabled && !isTauriMobile ? (
            <>
              <DialogHeader>
                <DialogTitle>Open workspace</DialogTitle>
                <DialogDescription>
                  Use the desktop folder picker to choose a local project folder.
                </DialogDescription>
              </DialogHeader>
              <div className="min-w-0 space-y-2">
                {selectedWorkspace && (
                  <div className="min-w-0 rounded-lg border border-(--color-border) bg-(--bg-page) px-3 py-2">
                    <p
                      className="min-w-0 font-mono text-xs text-(--color-text-muted) [overflow-wrap:anywhere]"
                      title={selectedWorkspace}
                    >
                      {selectedWorkspace}
                    </p>
                  </div>
                )}
                {error && (
                  <p className="text-xs text-(--color-error)">{error}</p>
                )}
              </div>
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={closeWorkspaceDialog}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  disabled={loading}
                  onClick={() => {
                    void openWorkspaceDialog();
                  }}
                >
                  {loading ? "Opening…" : "Choose folder…"}
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>Open workspace</DialogTitle>
                <DialogDescription>
                  Choose a server-local project folder.
                </DialogDescription>
              </DialogHeader>
              <div className="min-w-0 space-y-2">
                <div className="min-w-0 rounded-lg border border-(--color-border) bg-(--bg-page) px-3 py-2">
                  <p
                    className="min-w-0 font-mono text-xs text-(--color-text-muted) [overflow-wrap:anywhere]"
                    title={browserPath ?? undefined}
                  >
                    {browserPath ?? "Loading folders…"}
                  </p>
                </div>
                <div className="max-h-64 space-y-1 overflow-y-auto rounded-lg border border-(--color-border) p-1">
                  {parentPath && (
                    <button
                      type="button"
                      className="w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-(--bg-key)"
                      onClick={() => void loadBrowser(parentPath)}
                    >
                      ..
                    </button>
                  )}
                  {loading && dirs.length === 0 && (
                    <p className="px-2 py-4 text-center text-xs text-(--color-text-subtle)">
                      Loading folders…
                    </p>
                  )}
                  {!loading && dirs.length === 0 && (
                    <p className="px-2 py-4 text-center text-xs text-(--color-text-subtle)">
                      No folders here
                    </p>
                  )}
                  {dirs.map((dir) => (
                    <button
                      type="button"
                      key={dir.path}
                      className="flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-(--bg-key)"
                      onClick={() => void loadBrowser(dir.path)}
                    >
                      <Folder size={14} className="shrink-0" />
                      <span className="min-w-0 truncate">{dir.name}</span>
                    </button>
                  ))}
                </div>
                {error && (
                  <p className="text-xs text-(--color-error)">{error}</p>
                )}
              </div>
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={closeWorkspaceDialog}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  disabled={!browserPath || loading}
                  onClick={openSelectedFolder}
                >
                  Open
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Mobile workspace actions sheet */}
      <Dialog
        open={mobileWorkspaceActions !== null}
        onOpenChange={(open) => {
          if (!open) setMobileWorkspaceActions(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {mobileWorkspaceActions ? workspaceLabel(mobileWorkspaceActions.path) : "Workspace actions"}
            </DialogTitle>
            <DialogDescription>Choose a workspace action.</DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col items-stretch gap-2 p-3 sm:flex-col">
            <Button
              type="button"
              variant="outline"
              className="justify-start"
              onClick={() => {
                const action = mobileWorkspaceActions;
                setMobileWorkspaceActions(null);
                if (action) void selectWorkspace(action.path, { create: true });
              }}
            >
              <Plus size={14} aria-hidden="true" />
              New session
            </Button>
            {mobileWorkspaceActions?.kind === "main" ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  className="justify-start"
                  onClick={() => {
                    const action = mobileWorkspaceActions;
                    setMobileWorkspaceActions(null);
                    if (action) void openWorktreeDialog(action.path);
                  }}
                >
                  <GitBranch size={14} aria-hidden="true" />
                  Create worktree
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="justify-start text-(--color-error)"
                  onClick={() => {
                    const action = mobileWorkspaceActions;
                    setMobileWorkspaceActions(null);
                    if (action) setRemoveWorkspaceTarget(action.path);
                  }}
                >
                  <Trash2 size={14} aria-hidden="true" />
                  Remove from sidebar
                </Button>
              </>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Mobile session actions sheet */}
      <Dialog
        open={mobileSessionActions !== null}
        onOpenChange={(open) => {
          if (!open) setMobileSessionActions(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {mobileSessionActions?.title || "Untitled"}
            </DialogTitle>
            <DialogDescription>Choose a session action.</DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col items-stretch gap-2 p-3 sm:flex-col">
            <Button
              type="button"
              variant="outline"
              className="justify-start"
              onClick={() => {
                const session = mobileSessionActions;
                setMobileSessionActions(null);
                if (session) handleSessionEdit(session);
              }}
            >
              <Pencil size={14} aria-hidden="true" />
              Edit title
            </Button>
            <Button
              type="button"
              variant="outline"
              className="justify-start text-(--color-error)"
              onClick={() => {
                const session = mobileSessionActions;
                setMobileSessionActions(null);
                if (session) setPendingDeleteId(session.id);
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
              Delete session
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Desktop workspace context menu */}
      {desktopWorkspaceActions && (
        <div
          className="fixed inset-0 z-50"
          onClick={() => setDesktopWorkspaceActions(null)}
          onContextMenu={(event) => {
            event.preventDefault();
            setDesktopWorkspaceActions(null);
          }}
        >
          <div
            role="menu"
            aria-label={`Actions for ${workspaceLabel(desktopWorkspaceActions.path)}`}
            className="fixed min-w-48 rounded-lg border border-(--color-border) bg-(--bg-card) p-1 text-sm text-(--color-text) shadow-xl"
            style={{
              left: desktopWorkspaceActions.x,
              top: desktopWorkspaceActions.y,
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
              onClick={() => {
                const action = desktopWorkspaceActions;
                setDesktopWorkspaceActions(null);
                void selectWorkspace(action.path, { create: true });
              }}
            >
              <Plus size={14} aria-hidden="true" />
              New session
            </button>
            {desktopWorkspaceActions.kind === "main" ? (
              <>
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
                  onClick={() => {
                    const action = desktopWorkspaceActions;
                    setDesktopWorkspaceActions(null);
                    void openWorktreeDialog(action.path);
                  }}
                >
                  <GitBranch size={14} aria-hidden="true" />
                  Create worktree
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-(--color-error) hover:bg-(--color-error-subtle) focus-visible:bg-(--color-error-subtle) focus-visible:outline-none"
                  onClick={() => {
                    const action = desktopWorkspaceActions;
                    setDesktopWorkspaceActions(null);
                    setRemoveWorkspaceTarget(action.path);
                  }}
                >
                  <Trash2 size={14} aria-hidden="true" />
                  Remove from sidebar
                </button>
              </>
            ) : desktopWorkspaceActions.worktree?.managed ? (
              <button
                type="button"
                role="menuitem"
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-(--color-error) hover:bg-(--color-error-subtle) focus-visible:bg-(--color-error-subtle) focus-visible:outline-none"
                onClick={() => {
                  const item = desktopWorkspaceActions.worktree;
                  setDesktopWorkspaceActions(null);
                  if (item) void handleRemoveWorktree(item);
                }}
              >
                <Trash2 size={14} aria-hidden="true" />
                Remove worktree
              </button>
            ) : null}
          </div>
        </div>
      )}

      {/* Desktop session context menu */}
      {desktopSessionActions && (
        <div
          className="fixed inset-0 z-50"
          onClick={() => setDesktopSessionActions(null)}
          onContextMenu={(event) => {
            event.preventDefault();
            setDesktopSessionActions(null);
          }}
        >
          <div
            role="menu"
            aria-label={`Actions for ${desktopSessionActions.session.title || "Untitled"}`}
            className="fixed min-w-44 rounded-lg border border-(--color-border) bg-(--bg-card) p-1 text-sm text-(--color-text) shadow-xl"
            style={{
              left: desktopSessionActions.x,
              top: desktopSessionActions.y,
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
              onClick={() => {
                const { session } = desktopSessionActions;
                setDesktopSessionActions(null);
                handleSessionEdit(session);
              }}
            >
              <Pencil size={14} aria-hidden="true" />
              Edit title
            </button>
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-(--color-error) hover:bg-(--color-error-subtle) focus-visible:bg-(--color-error-subtle) focus-visible:outline-none"
              onClick={() => {
                const { session } = desktopSessionActions;
                setDesktopSessionActions(null);
                setPendingDeleteId(session.id);
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
              Delete session
            </button>
          </div>
        </div>
      )}

      {/* Remove workspace confirmation dialog */}
      <Dialog
        open={removeWorkspaceTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRemoveWorkspaceTarget(null);
        }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Remove workspace from sidebar</DialogTitle>
            <DialogDescription>
              &ldquo;
              {removeWorkspaceTarget
                ? workspaceLabel(removeWorkspaceTarget)
                : ""}
              &rdquo; will be hidden from the sidebar. Its sessions stay on disk.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setRemoveWorkspaceTarget(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={confirmRemoveWorkspace}
            >
              Remove
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Worktree creation dialog */}
      <Dialog
        open={worktreeTarget !== null}
        onOpenChange={(open) => {
          if (!open) setWorktreeTarget(null);
        }}
      >
        <DialogContent showCloseButton={false} className="max-w-md">
          <form onSubmit={submitWorktree}>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <GitBranch size={15} className="text-(--color-accent)" aria-hidden="true" />
                Create worktree
              </DialogTitle>
              <DialogDescription>
                Isolated checkout from{" "}
                {worktreeTarget
                  ? workspaceLabel(worktreeTarget)
                  : "this workspace"}.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-3">
              <div className="rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-2">
                <p className="truncate font-mono text-xs text-(--color-text-muted)" title={worktreeTarget ?? undefined}>
                  {worktreeTarget}
                </p>
              </div>
              <label className="block space-y-1 text-xs font-medium text-(--color-text-2)">
                <span>Worktree name</span>
                <input
                  value={worktreeName}
                  onChange={(e) => setWorktreeName(e.target.value)}
                  placeholder="feature-login"
                  className="h-9 w-full min-w-0 rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-1 font-mono text-sm text-(--color-text) outline-none focus-visible:border-(--focus-ring) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25"
                  maxLength={80}
                  autoFocus
                />
                <p className="text-xs font-normal text-(--color-text-subtle)">Blank uses "session".</p>
              </label>
              <label className="block space-y-1 text-xs font-medium text-(--color-text-2)">
                <span>Branch</span>
                <input
                  value={worktreeBranch}
                  onChange={(e) => setWorktreeBranch(e.target.value)}
                  placeholder="EvoFlux/feature-login"
                  className="h-9 w-full min-w-0 rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-1 font-mono text-sm text-(--color-text) outline-none focus-visible:border-(--focus-ring) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25"
                  maxLength={255}
                />
                <p className="text-xs font-normal text-(--color-text-subtle)">Blank defaults to EvoFlux/name.</p>
              </label>
            </div>
            {error && (
              <p className="rounded-md border border-(--color-error)/30 bg-(--color-error-subtle) px-3 py-2 text-xs text-(--color-error)">
                {error}
              </p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setWorktreeTarget(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={worktreeLoading}>
                {worktreeLoading ? "Creating…" : "Create and open"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
