/**
 * CodingSidebar — two-section navigator for coding mode.
 *
 * PROJECTS section (top):
 *   Sessions belong to the PROJECT, not to individual repos. A project
 *   session spans all repos in the project — the agent gets access to
 *   every workspace path via project_id. Clicking a project row
 *   expands/collapses to reveal, in order:
 *     1. Repos — the project's member repos, management-only (create
 *        worktree / remove from project). Clicking a repo NEVER starts a
 *        session — a project has no notion of "a session for repo X".
 *     2. Sessions — the project's session list (ProjectSessionList).
 *   "+" on the project row creates a new project session; the backend
 *   derives the primary workspace from the project. "+" on the "Repos"
 *   sub-header adds another repo to the project.
 *
 * WORKSPACES section (bottom):
 *   Standalone repos only — any workspace NOT linked to a project. This is
 *   the legacy single-workspace flow: clicking a row (or its "+") opens/
 *   creates a single-repo session, exactly as before project support
 *   existed. A repo disappears from this list the moment it's added to a
 *   project, since sessions on it must then go through the project.
 *
 * The desktop chrome (resizable width, collapse-to-rail, search trigger,
 * footer, section headers, session rows, session action surfaces) comes
 * from the shared `@/components/shell/` primitives — same as the work
 * sidebar. Coding keeps its stacked-cards layout (mode switch,
 * search, navigator, footer as separate floating cards) and all of its
 * workspace/worktree dialogs in-file.
 */
import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useParams } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useIsMobile } from "@/hooks/use-mobile";
import { useModalFocus } from "@/hooks/useModalFocus";
import { usePlatform } from "@/hooks/use-platform";
import { useMotionPreset, useListEnterIndex } from "@/lib/motion";
import { STORAGE_KEYS } from "@/lib/storage-keys";
import {
  Blocks,
  CalendarClock,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderPlus,
  GitBranch,
  CircleHelp,
  Layers3,
  Loader2,
  MessageSquareText,
  MoreHorizontal,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { ModeSwitchTabs } from "@/components/ModeSwitchTabs";
import { queryKeys } from "@/queries";
import {
  useCodingWorkspaceSessionsQuery,
  useDeleteTeamSessionMutation,
  useProjectSessionsQuery,
  useTeamSessionsQuery,
  useUpdateTeamSessionTitleMutation,
} from "@/queries/useSessionsQuery";
import { apiBaseUrl } from "@/api/base-url";
import {
  browseWorkspaces,
  listWorktrees,
  removeWorktree,
  resolveTeamSession,
  setCodingWorkspaceVisibility,
  validateWorkspace,
} from "@/api/client";
import { getAppBackendStatus } from "@/lib/app-backend";
import { useTeamStore } from "@/stores/useTeamStore";
import { useToastStore } from "@/stores/useToastStore";
import { useUIStore } from "@/stores/useUIStore";
import { usePinnedSessions } from "@/stores/usePinnedSessions";
import {
  prependSession,
  prependWorkspaceSession,
} from "@/stores/cache-invalidation-bridge";
import {
  clearLastCodingFocus,
  codingFocusId,
  isProjectFocusId,
  saveLastCodingFocus,
  saveLastCodingWorkspace,
  workspaceLabel,
} from "@/utils/workspace";
import { isTransientNetworkError } from "@/utils/errors";
import {
  SidebarShell,
  SidebarCard,
  SidebarSearchTrigger,
  SidebarFooter,
  SidebarModeSlot,
  SidebarModeRailSlot,
} from "@/components/shell/SidebarShell";
import { SidebarItem } from "@/components/ui/sidebar-item";
import { SidePanel } from "@/components/shell/SidePanel";
import { SessionRow } from "@/components/shell/SessionRow";
import {
  SessionContextMenu,
  SessionActionsDialog,
  type SessionMenuAnchor,
} from "@/components/shell/SessionContextMenu";
import { EditSessionTitleDialog } from "@/components/shell/EditSessionTitleDialog";
import { MobileDrawerBackdrop } from "@/components/shell/MobileDrawerBackdrop";
import { CollapsibleSection } from "@/components/shell/CollapsibleSection";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type {
  CodingProject,
  SessionResponse,
  WorktreeInfo,
} from "@/api/types";
import { LongPressButton } from "@/components/ui/long-press-button";
import {
  useAddWorkspaceMutation,
  useCodingOverviewQuery,
  useDeleteProjectMutation,
  useRemoveWorkspaceMutation,
} from "@/queries/useProjectsQuery";
import { ProjectSetupModal } from "@/components/ProjectSetupModal";
import { cn } from "@/lib/utils";
import { formatShortcutLabel } from "@/lib/keyboard-shortcuts";


function worktreeNameSlug(value: string): string {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 80)
      .replace(/-+$/g, "") || "session"
  );
}

/** Keep floating context menus inside the viewport. */
function clampMenuPosition(
  x: number,
  y: number,
  menuWidth = 192,
  menuHeight = 160,
): { x: number; y: number } {
  const pad = 8;
  return {
    x: Math.min(Math.max(x, pad), window.innerWidth - menuWidth - pad),
    y: Math.min(Math.max(y, pad), window.innerHeight - menuHeight - pad),
  };
}

function isLocalBackendUrl(value: string): boolean {
  try {
    const hostname = new URL(value).hostname.toLowerCase();
    return (
      hostname === "localhost" ||
      hostname === "127.0.0.1" ||
      hostname === "::1" ||
      hostname === "[::1]"
    );
  } catch {
    return false;
  }
}

/** Persisted expand/collapse state of the PROJECTS and WORKSPACES trees. */
interface CodingExpandedState {
  projects: string[];
  workspaces: string[];
}

function loadCodingExpanded(): CodingExpandedState {
  const empty: CodingExpandedState = { projects: [], workspaces: [] };
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.coding.expanded);
    if (!raw) return empty;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return empty;
    const { projects, workspaces } = parsed as Record<string, unknown>;
    return {
      projects: Array.isArray(projects)
        ? projects.filter((v): v is string => typeof v === "string")
        : [],
      workspaces: Array.isArray(workspaces)
        ? workspaces.filter((v): v is string => typeof v === "string")
        : [],
    };
  } catch {
    return empty;
  }
}

function saveCodingExpanded(state: CodingExpandedState): void {
  try {
    localStorage.setItem(STORAGE_KEYS.coding.expanded, JSON.stringify(state));
  } catch {
    // ignore storage failures
  }
}

interface CodingSidebarProps {
  currentSessionId?: string;
  workspace?: string | null;
  /** Bump this counter to programmatically open the workspace dialog
   *  (e.g. from a "no workspace attached" CTA). */
  openWorkspaceDialogKey?: number;
  /** Open the command palette (search input + footer help). */
  onCommandPalette?: () => void;
  /** Body-row mount point so the picker occupies Work's trailing-panel slot. */
  workspacePickerPortal?: HTMLElement | null;
  /** Whether the mobile/responsive overlay drawer is open. */
  mobileOpen?: boolean;
  /** Called when the drawer should close (backdrop tap, Escape, navigation). */
  onMobileClose?: () => void;
  /** Render the navigation as a modal drawer at constrained desktop widths. */
  drawerMode?: boolean;
}

interface SessionListActionProps {
  currentSessionId?: string;
  mobileLongPressActions?: boolean;
  onSessionSelect: (session: SessionResponse) => void;
  onSessionSideChat: (session: SessionResponse) => void;
  onSessionDelete: (session: SessionResponse) => void;
  pendingDeleteId: string | null;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
  onSessionEdit: (session: SessionResponse) => void;
  onSessionLongPress: (session: SessionResponse) => void;
  onSessionContextActions: (session: SessionResponse, event: React.MouseEvent) => void;
}

function SessionListPanel({
  sessions,
  currentSessionId,
  mobileLongPressActions = false,
  onSessionSelect,
  onSessionSideChat,
  onSessionDelete,
  pendingDeleteId,
  onCancelDelete,
  onConfirmDelete,
  onSessionEdit,
  onSessionLongPress,
  onSessionContextActions,
}: SessionListActionProps & {
  sessions: ReturnType<typeof useProjectSessionsQuery>;
}) {
  const allSessions = sessions.data?.pages.flatMap((page) => page.data) ?? [];
  // Filter out sessions created by scheduled tasks (use scheduled_task_name field)
  // Pinned sessions sort first; Array.prototype.sort is stable, so each
  // group keeps its original (recency) order.
  const pinnedIds = usePinnedSessions((s) => s.pinnedIds);
  const pinnedIdSet = new Set(pinnedIds);
  const projectSessions = allSessions
    .filter((s) => !s.scheduled_task_name)
    .sort(
      (a, b) => Number(pinnedIdSet.has(b.id)) - Number(pinnedIdSet.has(a.id)),
    );
  const sessionEnterIndex = useListEnterIndex(projectSessions.map((s) => s.id));

  return (
    <div className="space-y-0.5 pb-1">
      <div className="flex h-6 items-center gap-1.5 px-2 text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
        <MessageSquareText size={10} aria-hidden="true" />
        <span>Chats</span>
        {!sessions.isLoading && projectSessions.length > 0 && (
          <span className="ml-auto rounded-full bg-(--bg-key) px-1.5 py-px text-[9px] font-medium normal-case tracking-normal text-(--color-text-muted)">
            {projectSessions.length}{sessions.hasNextPage ? "+" : ""}
          </span>
        )}
      </div>
      {projectSessions.length === 0 && !sessions.isLoading && (
        <p className="px-2 py-1.5 text-[11px] text-(--color-text-subtle)">
          No sessions yet.
        </p>
      )}
      {sessions.isLoading && (
        <div className="flex items-center gap-1.5 px-2 py-1.5">
          <Loader2 size={10} className="animate-spin text-(--color-text-muted)" />
          <span className="text-[11px] text-(--color-text-muted)">Loading…</span>
        </div>
      )}
      {projectSessions.map((session) => (
        <SessionRow
          key={session.id}
          session={session}
          isActive={session.id === currentSessionId}
          enterIndex={sessionEnterIndex(session.id)}
          density="compact"
          onSelect={onSessionSelect}
          onOpenSideChat={onSessionSideChat}
          onDelete={onSessionDelete}
          pendingDelete={pendingDeleteId === session.id}
          onCancelDelete={onCancelDelete}
          onConfirmDelete={onConfirmDelete}
          onEdit={onSessionEdit}
          mobileLongPressActions={mobileLongPressActions}
          onLongPress={onSessionLongPress}
          onContextActions={onSessionContextActions}
        />
      ))}
      {sessions.hasNextPage && (
        <button
          type="button"
          onClick={() => void sessions.fetchNextPage()}
          disabled={sessions.isFetchingNextPage}
          className="mt-1 flex w-full items-center justify-center gap-1 rounded-md px-2 py-1.5 text-[11px] font-medium text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-60"
        >
          {sessions.isFetchingNextPage && (
            <Loader2 size={11} className="animate-spin" aria-hidden="true" />
          )}
          <span>{sessions.isFetchingNextPage ? "Loading…" : "Load more"}</span>
        </button>
      )}
    </div>
  );
}

function ProjectSessionList({
  projectId,
  ...actions
}: SessionListActionProps & { projectId: string }) {
  const sessions = useProjectSessionsQuery(projectId);
  return <SessionListPanel sessions={sessions} {...actions} />;
}

function WorkspaceSessionList({
  workspace,
  ...actions
}: SessionListActionProps & { workspace: string }) {
  const sessions = useCodingWorkspaceSessionsQuery(workspace);
  return <SessionListPanel sessions={sessions} {...actions} />;
}

export function CodingSidebar({
  currentSessionId,
  workspace,
  openWorkspaceDialogKey = 0,
  onCommandPalette,
  workspacePickerPortal = null,
  mobileOpen = false,
  onMobileClose,
  drawerMode = false,
}: CodingSidebarProps) {
  const isMobile = useIsMobile();
  const isDrawer = isMobile || drawerMode;
  const { isTauri, os, isMacOverlay } = usePlatform();
  const [nativeFolderPickerEnabled, setNativeFolderPickerEnabled] =
    useState(isTauri);
  const isTauriMobile = isTauri && (os === "ios" || os === "android");
  const mobileLongPressActions = isMobile && isTauriMobile && mobileOpen;
  const preset = useMotionPreset();
  useModalFocus(isDrawer && mobileOpen, onMobileClose);
  // Collapse state is shared by all three mode sidebars and owned by
  // useUIStore; AppShell owns the toggle button + Ctrl+B.
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const sidebarWidth = useUIStore((s) => s.sidebarWidth);
  const toggleScheduler = useUIStore((s) => s.toggleScheduler);
  const toggleSourceControl = useUIStore((s) => s.toggleWorkbenchTool);
  const togglePlugins = toggleSourceControl;
  const pinnedIds = usePinnedSessions((s) => s.pinnedIds);
  const togglePin = usePinnedSessions((s) => s.togglePin);
  const pinnedIdSet = new Set(pinnedIds);
  const navigate = useNavigate();
  const params = useParams({ strict: false }) as { focusId?: string };
  const queryClient = useQueryClient();
  const sessions = useTeamSessionsQuery("coding");
  const deleteSession = useDeleteTeamSessionMutation();
  const updateSessionTitle = useUpdateTeamSessionTitleMutation();
  // One merged query for both Projects and standalone Workspaces — see
  // useCodingOverviewQuery's doc comment for why this replaced two
  // independently-fetched lists reconciled by path-string matching.
  const overviewQuery = useCodingOverviewQuery();
  const projects = overviewQuery.data?.projects ?? [];
  const addWorkspaceMutation = useAddWorkspaceMutation();
  const deleteProjectMutation = useDeleteProjectMutation();
  const removeWorkspaceMutation = useRemoveWorkspaceMutation();
  const [showProjectModal, setShowProjectModal] = useState(false);
  const [deleteProjectTarget, setDeleteProjectTarget] =
    useState<CodingProject | null>(null);
  const [pendingProject, setPendingProject] = useState<string | null>(null);
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(
    () => new Set(loadCodingExpanded().projects),
  );
  const [expandedWorkspaces, setExpandedWorkspaces] = useState<Set<string>>(
    () => new Set(loadCodingExpanded().workspaces),
  );
  // Write-through persistence: every toggle (and the auto-expand-active
  // effects below, which only add to the sets) flows through here.
  useEffect(() => {
    saveCodingExpanded({
      projects: [...expandedProjects],
      workspaces: [...expandedWorkspaces],
    });
  }, [expandedProjects, expandedWorkspaces]);
  const [projectsSectionCollapsed, setProjectsSectionCollapsed] = useState(false);
  const [workspacesSectionCollapsed, setWorkspacesSectionCollapsed] = useState(false);
  // Actions menu for a project's own repo row (create worktree / remove from
  // project) — never offers "new session", since sessions are project-scoped.
  const [projectRepoActions, setProjectRepoActions] = useState<{
    project: CodingProject;
    workspaceId: string;
    path: string;
    x: number;
    y: number;
  } | null>(null);
  const [removeProjectWorkspaceTarget, setRemoveProjectWorkspaceTarget] =
    useState<{
      project: CodingProject;
      workspaceId: string;
      path: string;
    } | null>(null);
  // When set, the workspace-open dialog (folder picker) is in "add repo to
  // project" mode: confirming adds the folder to this project instead of
  // starting a standalone session.
  const [addRepoDialogProjectId, setAddRepoDialogProjectId] = useState<
    string | null
  >(null);

  const allSessions = sessions.data?.pages.flatMap((page) => page.data) ?? [];
  const codingSessions = allSessions.filter(
    (session) => session.mode === "coding" && session.workspace,
  );

  // The store holds the authoritative project binding for the active session
  // (primed synchronously in work.tsx), so it survives even when the active
  // session lives on an unloaded page of the paginated global list. Prefer it,
  // falling back to the list lookup only before the store is primed.
  const storeProjectId = useTeamStore((s) => s.projectId);
  const currentProjectId =
    storeProjectId ??
    codingSessions.find((s) => s.id === currentSessionId)?.project_id ??
    null;

  const workspaceTree = overviewQuery.data?.repositories ?? [];
  // When a workspace has been moved, /coding/$focusId fails before a session
  // exists and ``workspace`` is still null. The route parameter is enough to
  // identify the stale workspace and let its removal return the user to a
  // safe empty Coding page.
  const routeWorkspace =
    params.focusId && !isProjectFocusId(params.focusId) ? params.focusId : null;
  const activeWorkspace = workspace ?? routeWorkspace;
  const worktreeSourceByDirectory = new Map<string, string>();
  for (const repo of workspaceTree) {
    for (const item of repo.worktrees)
      worktreeSourceByDirectory.set(item.path, repo.path);
  }


  const toggleProjectExpanded = (projectId: string) => {
    setExpandedProjects((current) => {
      const next = new Set(current);
      if (next.has(projectId)) next.delete(projectId);
      else next.add(projectId);
      return next;
    });
  };

  useEffect(() => {
    if (!currentProjectId) return;
    setExpandedProjects((current) => {
      if (current.has(currentProjectId)) return current;
      const next = new Set(current);
      next.add(currentProjectId);
      return next;
    });
  }, [currentProjectId]);

  const toggleWorkspaceExpanded = (path: string) => {
    setExpandedWorkspaces((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  useEffect(() => {
    if (!activeWorkspace) return;
    setExpandedWorkspaces((current) => {
      if (current.has(activeWorkspace)) return current;
      const next = new Set(current);
      next.add(activeWorkspace);
      return next;
    });
  }, [activeWorkspace]);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedWorkspace, setSelectedWorkspace] = useState<string | null>(
    null,
  );
  const [browserPath, setBrowserPath] = useState<string | null>(null);
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [dirs, setDirs] = useState<Array<{ name: string; path: string }>>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [pendingWorkspace, setPendingWorkspace] = useState<string | null>(null);
  const [trustWorkspace, setTrustWorkspace] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<SessionResponse | null>(null);
  const [editTitle, setEditTitle] = useState("");
  // Keep the full session — project/workspace lists are separate queries and
  // the deleted row may not be on a loaded page of the global coding list.
  const [pendingDeleteSession, setPendingDeleteSession] =
    useState<SessionResponse | null>(null);
  const [mobileSessionActions, setMobileSessionActions] =
    useState<SessionResponse | null>(null);
  const [desktopSessionActions, setDesktopSessionActions] =
    useState<SessionMenuAnchor | null>(null);
  const [desktopWorkspaceActions, setDesktopWorkspaceActions] = useState<{
    path: string;
    kind: "main" | "worktree";
    source?: string;
    worktree?: WorktreeInfo;
    x: number;
    y: number;
  } | null>(null);
  const [mobileWorkspaceActions, setMobileWorkspaceActions] = useState<{
    path: string;
    kind: "main" | "worktree";
    source?: string;
    worktree?: WorktreeInfo;
  } | null>(null);
  // Workspace pending removal — null when no confirmation is open. The
  // confirmation dialog reads this; ``confirmRemoveWorkspace`` commits.
  const [removeWorkspaceTarget, setRemoveWorkspaceTarget] = useState<
    string | null
  >(null);
  const [worktreeTarget, setWorktreeTarget] = useState<string | null>(null);
  const [worktreeName, setWorktreeName] = useState("");
  const [worktreeBranch, setWorktreeBranch] = useState("");
  const [worktreeLoading, setWorktreeLoading] = useState(false);
  const [worktreeOptions, setWorktreeOptions] = useState<WorktreeInfo[]>([]);
  const [worktreeRemoving, setWorktreeRemoving] = useState<string | null>(null);
  const [worktreesBySource, setWorktreesBySource] = useState<
    Record<string, WorktreeInfo[]>
  >({});
  const [removedWorktreePaths, setRemovedWorktreePaths] = useState<Set<string>>(
    () => new Set(),
  );

  const loadBrowser = useCallback(async (path?: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const result = await browseWorkspaces(path);
      setBrowserPath(result.path);
      setParentPath(result.parent);
      setDirs(result.directories);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to read directory");
    } finally {
      setLoading(false);
    }
  }, []);

  const openWebWorkspaceDialog = useCallback(() => {
    setSelectedWorkspace(null);
    setTrustWorkspace(null);
    setDialogOpen(true);
    if (!browserPath) void loadBrowser(null);
  }, [browserPath, loadBrowser]);

  // Closes the folder-picker dialog and clears every mode flag it can be in
  // (plain "open a standalone workspace" vs. "add a repo to project X") so a
  // cancelled dialog never leaves stale state for the next open.
  const closeWorkspaceDialog = useCallback(() => {
    setDialogOpen(false);
    setTrustWorkspace(null);
    setAddRepoDialogProjectId(null);
  }, []);

  const openWorkspaceDialog = useCallback(async () => {
    setError(null);
    setSelectedWorkspace(null);
    setTrustWorkspace(null);

    if (!isTauri || isTauriMobile) {
      openWebWorkspaceDialog();
      return;
    }

    const backendBaseUrl = apiBaseUrl().replace(/\/api\/?$/, "");
    const backend = await getAppBackendStatus();
    const activeBackendBaseUrl = backend?.base_url ?? backendBaseUrl;
    const isAbsoluteBackendUrl = /^https?:\/\//i.test(activeBackendBaseUrl);
    if (
      (backend?.external || (!backend && isAbsoluteBackendUrl)) &&
      !isLocalBackendUrl(activeBackendBaseUrl)
    ) {
      setNativeFolderPickerEnabled(false);
      openWebWorkspaceDialog();
      return;
    }
    setNativeFolderPickerEnabled(true);

    setDialogOpen(true);
    setLoading(true);
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({
        directory: true,
        multiple: false,
        title: "Open workspace",
      });
      if (typeof selected !== "string") {
        setDialogOpen(false);
        setTrustWorkspace(null);
        setAddRepoDialogProjectId(null);
        return;
      }
      setSelectedWorkspace(selected);
      const result = await validateWorkspace(selected);
      setTrustWorkspace(result.workspace);
      setDialogOpen(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to open workspace");
    } finally {
      setLoading(false);
    }
  }, [isTauri, isTauriMobile, openWebWorkspaceDialog]);

  const refreshWorkspaceTree = useCallback(async () => {
    // Force the merged Projects + Workspaces snapshot to be fetched even if
    // route navigation briefly made the sidebar query inactive. This prevents
    // an old empty snapshot from remaining visible until a later mount.
    await queryClient.refetchQueries({
      queryKey: queryKeys.codingOverview(),
      type: "all",
    });
  }, [queryClient]);

  useEffect(() => {
    const handler = () => {
      void refreshWorkspaceTree();
    };
    window.addEventListener("coding-workspaces-changed", handler);
    window.addEventListener("storage", handler);
    return () => {
      window.removeEventListener("coding-workspaces-changed", handler);
      window.removeEventListener("storage", handler);
    };
  }, [refreshWorkspaceTree]);

  useEffect(() => {
    if (openWorkspaceDialogKey > 0) void openWorkspaceDialog();
  }, [openWorkspaceDialogKey, openWorkspaceDialog]);

  useEffect(() => {
    if (pendingWorkspace && workspace === pendingWorkspace)
      setPendingWorkspace(null);
  }, [pendingWorkspace, workspace]);

  const selectWorkspace = async (
    path: string,
    opts: { create?: boolean } = {},
  ) => {
    const shouldCreate = opts.create === true;
    const state = useTeamStore.getState();
    const create =
      shouldCreate &&
      !(
        state.isEmptyIdleSession() &&
        state.sessionId === currentSessionId &&
        workspace === path
      );
    if (shouldCreate && !create) {
      setPendingWorkspace(null);
      return;
    }
    setPendingWorkspace(path);
    try {
      // Only carry the current model/thinking-level over when there's an
      // existing session to carry them FROM — otherwise a stale value left
      // over from a different mode's session gets sent here and can be
      // rejected as "Choose a model from the registry." (see work.tsx).
      const carryModel = state.sessionId ? state.sessionModel : null;
      const carryThinkingLevel = state.sessionId ? state.sessionThinkingLevel : null;
      state.beginResolvedSession(null, {
        mode: "coding",
        workspace: path,
        model: carryModel,
        thinkingLevel: carryThinkingLevel,
      });
      const session = await resolveTeamSession({
        mode: "coding",
        workspace: path,
        model: carryModel,
        thinkingLevel: carryThinkingLevel,
        create,
      });
      state.beginResolvedSession(session.id, {
        mode: "coding",
        workspace: session.workspace ?? path,
        model: session.model ?? carryModel,
        thinkingLevel: session.thinking_level ?? carryThinkingLevel,
        skipInitialRestore: session.created,
      });
      // A repo already owned by a project is canonicalised server-side to a
      // project session. Keep the store and last-focus pointer aligned so it
      // appears under that Project instead of becoming an invisible
      // standalone session.
      useTeamStore.setState({ projectId: session.project_id ?? null });
      saveLastCodingFocus({
        project_id: session.project_id,
        workspace: session.workspace ?? path,
      });
      if (session.created) {
        prependSession(queryClient, session);
        if (session.project_id) {
          void queryClient.invalidateQueries({
            queryKey: queryKeys.team.sessions.project(session.project_id),
          });
        } else {
          prependWorkspaceSession(queryClient, path, session);
        }
      }
      await refreshWorkspaceTree();
      if (session.project_id) {
        const owner = projects.find((project) => project.id === session.project_id);
        useToastStore.getState().push({
          tone: "info",
          title: owner ? `Opened in ${owner.name}` : "Opened in project",
          description:
            "This repository belongs to a project, so its sessions are shown there instead of under standalone Workspaces.",
        });
      }
      const focusId = codingFocusId({
        project_id: session.project_id,
        workspace: session.workspace ?? path,
      });
      navigate(
        focusId
          ? { to: "/coding/$focusId/$sessionId", params: { focusId, sessionId: session.id } }
          : { to: "/coding" },
      );
    } catch (err) {
      setPendingWorkspace(null);
      setError(err instanceof Error ? err.message : "Unable to create session");
    }
  };

  const openProjectSession = async (project: CodingProject) => {
    if (!project.workspaces?.length) return;
    setPendingProject(project.id);
    try {
      const state = useTeamStore.getState();
      state.beginResolvedSession(null, { mode: "coding" });
      // Only carry the current model/thinking-level over when there's an
      // existing session to carry them FROM — see selectWorkspace above.
      const carryModel = state.sessionId ? state.sessionModel : null;
      const carryThinkingLevel = state.sessionId ? state.sessionThinkingLevel : null;
      // Backend derives workspace from project — no primaryPath passed from UI.
      const session = await resolveTeamSession({
        mode: "coding",
        project_id: project.id,
        model: carryModel,
        thinkingLevel: carryThinkingLevel,
        create: true,
      });
      const resolvedWorkspace = session.workspace ?? null;
      state.beginResolvedSession(session.id, {
        mode: "coding",
        workspace: resolvedWorkspace,
        model: session.model ?? carryModel,
        thinkingLevel: session.thinking_level ?? carryThinkingLevel,
        skipInitialRestore: session.created,
      });
      // beginResolvedSession resets projectId to null — restore it immediately.
      useTeamStore.setState({ projectId: project.id });
      if (session.created) {
        prependSession(queryClient, session);
        // Surface the freshly-created session in the project-scoped list
        // immediately instead of waiting for the query to go stale.
        void queryClient.invalidateQueries({
          queryKey: queryKeys.team.sessions.project(project.id),
        });
      }
      // A project session spans all repos — do NOT persist paths[0] as the
      // "last coding workspace" (a later restore would reopen it as a single
      // repo). projectId is what drives multi-repo context.
      if (resolvedWorkspace) {
        await refreshWorkspaceTree();
      }
      const focusId = codingFocusId({ project_id: project.id, workspace: resolvedWorkspace });
      navigate(
        focusId
          ? { to: "/coding/$focusId/$sessionId", params: { focusId, sessionId: session.id } }
          : { to: "/coding" },
      );
    } catch (err) {
      useToastStore.getState().push({
        tone: "error",
        title: "Couldn't open project session",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setPendingProject(null);
    }
  };

  // Purge a standalone workspace's app-owned sessions and indexes. The source
  // repository remains on disk and can later be opened as a clean workspace.
  const confirmRemoveWorkspace = () => {
    const path = removeWorkspaceTarget;
    if (!path) return;

    const isRemovingActiveWorkspace =
      path === activeWorkspace || params.focusId === path;

    // Do this before navigating: otherwise bare /coding immediately restores
    // the old local "last workspace" pointer and retries the missing folder.
    clearLastCodingFocus(path);
    setExpandedWorkspaces((current) => {
      if (!current.has(path)) return current;
      const next = new Set(current);
      next.delete(path);
      return next;
    });
    void setCodingWorkspaceVisibility(path, true)
      .then(() => {
        queryClient.removeQueries({ queryKey: queryKeys.codeGraph.all(path) });
        queryClient.removeQueries({ queryKey: queryKeys.coding.all(path) });
        void queryClient.invalidateQueries({
          queryKey: queryKeys.team.sessions.all(),
        });
        void refreshWorkspaceTree();
      })
      .catch((err) => {
        useToastStore.getState().push({
          tone: "error",
          title: "Couldn't remove workspace",
          description: err instanceof Error ? err.message : String(err),
        });
      });
    if (isRemovingActiveWorkspace) {
      // /coding is an empty/default view, but this layout stays mounted while
      // navigating between coding routes. Reset the store explicitly so the
      // deleted workspace's chat cannot remain visible under the empty URL.
      useTeamStore.getState().newSession();
      navigate({ to: "/coding", replace: true });
    }
    setRemoveWorkspaceTarget(null);
  };

  const loadWorktreesForTarget = useCallback(
    async (path: string) => {
      try {
        const items = await listWorktrees(path);
        setWorktreesBySource((current) => ({ ...current, [path]: items }));
        if (worktreeTarget === path) setWorktreeOptions(items);
        return items;
      } catch {
        setWorktreesBySource((current) => ({ ...current, [path]: [] }));
        if (worktreeTarget === path) setWorktreeOptions([]);
        return [];
      }
    },
    [worktreeTarget],
  );

  const openWorktreeDialog = async (path: string) => {
    setWorktreeTarget(path);
    setWorktreeName("");
    setWorktreeBranch("");
    setWorktreeOptions(worktreesBySource[path] ?? []);
    setWorktreeRemoving(null);
    setError(null);
    const items = await loadWorktreesForTarget(path);
    setWorktreeOptions(items);
  };

  const handleRemoveWorktree = async (item: WorktreeInfo) => {
    if (!item.managed) return;
    const directory = item.directory;
    setWorktreeRemoving(directory);
    setError(null);
    try {
      const source = worktreeSourceByDirectory.get(directory) ?? worktreeTarget;
      if (!source) return;
      await removeWorktree(source, directory);
      setRemovedWorktreePaths((current) => new Set(current).add(directory));
      setWorktreesBySource((current) => {
        const next = { ...current };
        delete next[directory];
        next[source] = (next[source] ?? []).filter(
          (worktree) => worktree.directory !== directory,
        );
        return next;
      });
      await loadWorktreesForTarget(source);
      await refreshWorkspaceTree();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to remove worktree",
      );
    } finally {
      setWorktreeRemoving(null);
    }
  };

  const submitWorktree = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!worktreeTarget) return;
    setWorktreeLoading(true);
    setError(null);
    try {
      const state = useTeamStore.getState();
      // Only carry the current model/thinking-level over when there's an
      // existing session to carry them FROM — see selectWorkspace above.
      const carryModel = state.sessionId ? state.sessionModel : null;
      const carryThinkingLevel = state.sessionId ? state.sessionThinkingLevel : null;
      const session = await resolveTeamSession({
        mode: "coding",
        worktreeFrom: worktreeTarget,
        worktreeName: worktreeName || "session",
        worktreeBranch: worktreeBranch || null,
        model: carryModel,
        thinkingLevel: carryThinkingLevel,
      });
      const path = session.workspace;
      if (!path) throw new Error("Worktree session did not return a workspace");
      setWorktreeTarget(null);
      saveLastCodingWorkspace(path);
      const nextState = useTeamStore.getState();
      nextState.beginResolvedSession(session.id, {
        mode: "coding",
        workspace: path,
        model: session.model ?? carryModel,
        thinkingLevel: session.thinking_level ?? carryThinkingLevel,
        skipInitialRestore: session.created,
      });
      useTeamStore.setState({ projectId: session.project_id ?? null });
      saveLastCodingFocus({ project_id: session.project_id, workspace: path });
      prependSession(queryClient, session);
      if (session.project_id) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.team.sessions.project(session.project_id),
        });
      } else {
        prependWorkspaceSession(queryClient, path, session);
      }
      await refreshWorkspaceTree();
      const focusId = codingFocusId({ project_id: session.project_id, workspace: path });
      navigate(
        focusId
          ? { to: "/coding/$focusId/$sessionId", params: { focusId, sessionId: session.id } }
          : { to: "/coding" },
      );
      onMobileClose?.();
    } catch (err) {
      if (isTransientNetworkError(err) && worktreeTarget) {
        const source = worktreeTarget;
        const expectedName = worktreeNameSlug(worktreeName || "session");
        const items = await loadWorktreesForTarget(source);
        const created = items.find((item) => item.name === expectedName);
        if (created) {
          setWorktreeTarget(null);
          saveLastCodingWorkspace(created.directory);
          setError(null);
          await refreshWorkspaceTree();
          navigate({ to: "/coding" });
          onMobileClose?.();
          return;
        }
      }
      setError(
        err instanceof Error ? err.message : "Unable to create worktree",
      );
    } finally {
      setWorktreeLoading(false);
    }
  };

  const deletedWorktreeSet = removedWorktreePaths;
  // A repo that belongs to ANY project is managed from within that project's
  // "Repos" list, not here — Workspaces is standalone-only (business rule:
  // sessions on a project's repo must go through the project, never per-repo).
  // project_id comes straight off the repo (a real FK lookup server-side),
  // so this is never at risk of drifting from a separately-fetched /projects
  // list the way path-string matching against it would be.
  const standaloneWorkspaces = workspaceTree
    .filter((repo) => repo.project_id === null && !deletedWorktreeSet.has(repo.path))
    .map((repo) => repo.path);
  const addRepoProject = addRepoDialogProjectId
    ? projects.find((p) => p.id === addRepoDialogProjectId) ?? null
    : null;

  const openSelectedFolder = async () => {
    if (!browserPath) return;
    try {
      const result = await validateWorkspace(browserPath);
      setTrustWorkspace(result.workspace);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Workspace is invalid");
    }
  };

  const confirmTrustedWorkspace = () => {
    if (!trustWorkspace) return;
    const workspaceToOpen = trustWorkspace;
    setTrustWorkspace(null);
    setDialogOpen(false);
    if (addRepoDialogProjectId) {
      const projectId = addRepoDialogProjectId;
      setAddRepoDialogProjectId(null);
      addWorkspaceMutation.mutate(
        { projectId, body: { workspace_path: workspaceToOpen } },
        {
          onSuccess: () => {
            setExpandedProjects((current) => {
              if (current.has(projectId)) return current;
              const next = new Set(current);
              next.add(projectId);
              return next;
            });
            const project = projects.find((item) => item.id === projectId);
            useToastStore.getState().push({
              tone: "success",
              title: "Repository added",
              description: project
                ? `It is now visible under ${project.name}.`
                : "It is now visible under the project.",
            });
          },
          onError: (err) => {
            useToastStore.getState().push({
              tone: "error",
              title: "Couldn't add repository",
              description: err instanceof Error ? err.message : String(err),
            });
          },
        },
      );
      return;
    }
    void selectWorkspace(workspaceToOpen);
  };

  // Opens the same folder-picker dialog used for standalone workspaces, but
  // tags it so the confirmation adds the chosen folder to this project
  // instead of starting a session.
  const openAddRepoDialog = (projectId: string) => {
    setAddRepoDialogProjectId(projectId);
    void openWorkspaceDialog();
  };

  const handleSessionSelect = (
    session: SessionResponse,
    workspacePath: string,
  ) => {
    // Only remember a single-repo workspace for non-project sessions — a
    // project session spans all repos and must not be pinned to one (rule 1/3).
    if (!session.project_id && (session.workspace ?? workspacePath))
      saveLastCodingWorkspace(session.workspace ?? workspacePath);
    // Prime projectId immediately so CodingWorkspacePanel shows multi-repo context
    // without waiting for the async history load.
    useTeamStore.setState({ projectId: session.project_id ?? null });
    const focusId = codingFocusId({
      project_id: session.project_id,
      workspace: session.workspace ?? workspacePath,
    });
    navigate(
      focusId
        ? { to: "/coding/$focusId/$sessionId", params: { focusId, sessionId: session.id } }
        : { to: "/coding" },
    );
    onMobileClose?.();
  };

  // Session-row side-chat icon: open the session (no-op when already active)
  // and ask TeamChatView to open its side chat panel.
  const handleSessionSideChat = (
    session: SessionResponse,
    workspacePath: string,
  ) => {
    useUIStore.getState().requestSideChat(session.id);
    handleSessionSelect(session, workspacePath);
  };

  const handleSessionDelete = (session: SessionResponse) => {
    setPendingDeleteSession(session);
  };

  const handleSessionEdit = (session: SessionResponse) => {
    setEditTarget(session);
    setEditTitle(session.title || "");
  };

  const confirmSessionDelete = () => {
    if (!pendingDeleteSession) return;
    const target = pendingDeleteSession;
    const fallbackSession =
      target.id === currentSessionId
        ? ((target.project_id
            ? codingSessions.find(
                (session) =>
                  session.id !== target.id &&
                  session.project_id === target.project_id,
              )
            : undefined) ??
          codingSessions.find(
            (session) =>
              session.id !== target.id &&
              session.workspace === target.workspace,
          ) ??
          codingSessions.find((session) => session.id !== target.id))
        : null;
    deleteSession.mutate(target.id);
    if (target.id === currentSessionId) {
      if (fallbackSession) {
        // Don't pin a project session to a single repo's last-workspace marker.
        if (fallbackSession.workspace && !fallbackSession.project_id)
          saveLastCodingWorkspace(fallbackSession.workspace);
        const focusId = codingFocusId({
          project_id: fallbackSession.project_id,
          workspace: fallbackSession.workspace,
        });
        navigate(
          focusId
            ? { to: "/coding/$focusId/$sessionId", params: { focusId, sessionId: fallbackSession.id }, replace: true }
            : { to: "/coding", replace: true },
        );
      } else {
        navigate({ to: "/coding", replace: true });
      }
    }
    setPendingDeleteSession(null);
  };

  // Collapsed icon rail — desktop only; mode switch + primary actions above,
  // footer trio below.
  const rail = (
    <>
      <SidebarCard
        className={`w-full shrink-0 items-center gap-0.5 px-1 pb-2 ${isMacOverlay ? 'pt-10' : 'pt-2'}`}
      >
        <SidebarModeRailSlot />
        {onCommandPalette && (
          <button
            type="button"
            onClick={onCommandPalette}
            title={`Search (${formatShortcutLabel("Ctrl+P")})`}
            aria-label="Search"
            className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
          >
            <Search size={15} aria-hidden="true" />
          </button>
        )}
        <button
          type="button"
          onClick={() => { void openWorkspaceDialog(); }}
          title="Open folder"
          aria-label="Open folder"
          className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
        >
          <Folder size={15} aria-hidden="true" />
        </button>
        <SidebarItem
          Icon={CalendarClock}
          label="Scheduler"
          kbd="^S"
          collapsed
          onClick={toggleScheduler}
        />
        <SidebarItem
          Icon={Blocks}
          label="Plugins"
          kbd="^K"
          collapsed
          onClick={() => togglePlugins("plugins")}
        />
        <SidebarItem
          Icon={GitBranch}
          label="Source Control"
          kbd="^G"
          collapsed
          onClick={() => toggleSourceControl("source-control")}
        />
      </SidebarCard>
      <div className="flex-1" />
      <SidebarCard className="w-full shrink-0">
        <SidebarFooter collapsed onCommandPalette={onCommandPalette} />
      </SidebarCard>
    </>
  );

  // The PROJECTS + WORKSPACES navigator — one copy shared by the desktop
  // floating card and the mobile drawer.
  const navigatorContent = (
    <>
      {/* PROJECTS */}
      <div className="px-2 pb-1 pt-2">
        <CollapsibleSection
          label="Projects"
          collapsed={projectsSectionCollapsed}
          onToggle={() => setProjectsSectionCollapsed((v) => !v)}
          count={projects.length || undefined}
          onAdd={() => setShowProjectModal(true)}
          addLabel="New multi-repo project"
          size="large"
          className="px-1 pb-1"
        />

        {!projectsSectionCollapsed && overviewQuery.isLoading && (
          <div className="flex items-center gap-1.5 px-2 py-1.5">
            <Loader2 size={11} className="animate-spin text-(--color-text-muted)" />
            <span className="text-xs text-(--color-text-muted)">Loading…</span>
          </div>
        )}

        {!projectsSectionCollapsed && overviewQuery.isError && (
          <div className="mx-2 my-1 rounded-md border border-(--color-error)/30 bg-(--color-error-subtle) px-2 py-2 text-xs text-(--color-error)">
            <p>Couldn&apos;t load projects and workspaces.</p>
            <button
              type="button"
              onClick={() => void overviewQuery.refetch()}
              className="mt-1 font-medium underline underline-offset-2"
            >
              Retry
            </button>
          </div>
        )}

        {!projectsSectionCollapsed && !overviewQuery.isLoading && !overviewQuery.isError && projects.length === 0 && (
          <p className="px-2 py-1.5 text-xs text-(--color-text-subtle)">
            No projects yet.{" "}
            <button
              type="button"
              onClick={() => setShowProjectModal(true)}
              className="text-(--color-accent) hover:underline"
            >
              Create one
            </button>{" "}
            to work across multiple repos.
          </p>
        )}

        {!projectsSectionCollapsed && (
        <div className="space-y-1">
          {projects.map((project) => {
            const isActive = currentProjectId === project.id;
            const isExpanded = expandedProjects.has(project.id);
            const isPending = pendingProject === project.id;
            const canCreateSession = (project.workspaces?.length ?? 0) > 0;
            const projectRunningSessions = codingSessions.filter(
              (s) => s.project_id === project.id && s.running === true,
            );
            const projectHasRunning = projectRunningSessions.length > 0;
            return (
              <div
                key={project.id}
                className={cn(
                  "overflow-hidden rounded-lg border transition-colors",
                  isActive
                    ? "border-(--color-border-strong) bg-(--bg-key)/70"
                    : isExpanded
                      ? "border-(--color-border) bg-(--bg-page)/45"
                      : "border-transparent hover:border-(--color-border)/70 hover:bg-(--bg-key)/35",
                )}
              >
                <div className="group flex min-h-9 items-center px-1">
                  <button
                    type="button"
                    onClick={() => toggleProjectExpanded(project.id)}
                    className={cn(
                      "flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1.5 text-left text-xs transition-colors hover:bg-(--bg-key)/70",
                      isActive ? "text-(--color-text)" : "text-(--color-text-2)",
                    )}
                    aria-expanded={isExpanded}
                    aria-label={`${isExpanded ? "Collapse" : "Expand"} project ${project.name}`}
                  >
                    {isExpanded ? (
                      <ChevronDown size={11} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
                    ) : (
                      <ChevronRight size={11} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
                    )}
                    <Layers3
                      size={13}
                      className={cn(
                        "shrink-0",
                        isActive ? "text-(--color-accent)" : "text-(--color-text-muted)",
                      )}
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 truncate font-semibold">
                      {project.name}
                    </span>
                    <span
                      className="flex shrink-0 items-center gap-1 rounded-full bg-(--bg-key) px-1.5 py-0.5 text-[9px] font-medium text-(--color-text-muted)"
                      aria-label={`${project.workspaces?.length ?? 0} repositories`}
                    >
                      <GitBranch size={9} aria-hidden="true" />
                      <span>{project.workspaces?.length ?? 0}</span>
                    </span>
                    {projectHasRunning && !isExpanded && (
                      <span
                        className="h-1.5 w-1.5 shrink-0 rounded-full bg-(--color-accent)"
                        aria-label="Project has running session"
                      />
                    )}
                  </button>
                  {isPending ? (
                    <Loader2 size={11} className="ml-1 shrink-0 animate-spin text-(--color-text-muted)" />
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => void openProjectSession(project)}
                        disabled={!canCreateSession}
                        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-[opacity,background-color,color] duration-(--motion-fast) hover:bg-(--bg-key) hover:text-(--color-text) disabled:cursor-not-allowed disabled:opacity-40 ${isMobile ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                        aria-label={canCreateSession ? `New session in ${project.name}` : `${project.name} has no repositories yet`}
                        title={canCreateSession ? `New session in ${project.name}` : "Add a repository to this project first"}
                      >
                        <Plus size={12} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setDeleteProjectTarget(project);
                        }}
                        disabled={deleteProjectMutation.isPending}
                        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-(--color-text-subtle) transition-[opacity,background-color,color] duration-(--motion-fast) hover:bg-(--color-error-subtle) hover:text-(--color-error) disabled:cursor-not-allowed disabled:opacity-40 ${isMobile ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                        aria-label={`Delete project ${project.name}`}
                        title={`Delete project ${project.name}`}
                      >
                        <Trash2 size={12} aria-hidden="true" />
                      </button>
                    </>
                  )}
                </div>
                {isExpanded && (
                  <div className="mx-2 mb-2 border-l border-(--color-border) pl-2">
                    <div className="flex h-6 items-center justify-between px-2">
                      <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
                        <GitBranch size={10} aria-hidden="true" />
                        Repositories
                      </span>
                      <button
                        type="button"
                        onClick={() => openAddRepoDialog(project.id)}
                        className="flex h-5 w-5 items-center justify-center rounded-md text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
                        title={`Add repository to ${project.name}`}
                        aria-label={`Add repository to ${project.name}`}
                      >
                        <Plus size={11} aria-hidden="true" />
                      </button>
                    </div>
                    {(project.workspaces ?? []).length === 0 && (
                      <p className="px-2 py-1.5 text-[11px] text-(--color-text-subtle)">
                        No repositories yet.
                      </p>
                    )}
                    {(project.workspaces ?? []).map((w) => (
                      <button
                        key={w.workspace_id}
                        type="button"
                        onClick={(event) => {
                          const pos = clampMenuPosition(event.clientX, event.clientY);
                          setProjectRepoActions({
                            project,
                            workspaceId: w.workspace_id,
                            path: w.path,
                            x: pos.x,
                            y: pos.y,
                          });
                        }}
                        onContextMenu={(event) => {
                          event.preventDefault();
                          const pos = clampMenuPosition(event.clientX, event.clientY);
                          setProjectRepoActions({
                            project,
                            workspaceId: w.workspace_id,
                            path: w.path,
                            x: pos.x,
                            y: pos.y,
                          });
                        }}
                        className="flex w-full min-w-0 items-center gap-2 truncate rounded-md px-2 py-1.5 text-left text-[11px] text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                        aria-label={`Actions for repository ${w.display_name || w.name || workspaceLabel(w.path)}`}
                        title={w.path}
                      >
                        <Folder size={11} className="shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
                        <span className="min-w-0 flex-1 truncate">
                          {w.display_name || w.name || workspaceLabel(w.path)}
                        </span>
                        <MoreHorizontal size={11} className="shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
                      </button>
                    ))}
                    <div className="my-1 border-t border-(--color-border)/60" aria-hidden="true" />
                    <ProjectSessionList
                      projectId={project.id}
                      currentSessionId={currentSessionId}
                      mobileLongPressActions={mobileLongPressActions}
                      onSessionSelect={(session) =>
                        handleSessionSelect(session, session.workspace ?? "")
                      }
                      onSessionSideChat={(session) =>
                        handleSessionSideChat(session, session.workspace ?? "")
                      }
                      onSessionDelete={handleSessionDelete}
                      pendingDeleteId={pendingDeleteSession?.id ?? null}
                      onCancelDelete={() => setPendingDeleteSession(null)}
                      onConfirmDelete={confirmSessionDelete}
                      onSessionEdit={handleSessionEdit}
                      onSessionLongPress={setMobileSessionActions}
                      onSessionContextActions={(session, event) => {
                        setDesktopSessionActions({
                          session,
                          x: event.clientX,
                          y: event.clientY,
                        });
                      }}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
        )}
      </div>

      {/* WORKSPACES section header — standalone repos only. A repo that
          belongs to a project lives in that project's own "Repos" list
          above, not here (a project's repo has no standalone session). */}
      <div className="border-t border-(--color-border)/60 px-2 pb-2 pt-2">
        <CollapsibleSection
          label="Workspaces"
          collapsed={workspacesSectionCollapsed}
          onToggle={() => setWorkspacesSectionCollapsed((v) => !v)}
          count={standaloneWorkspaces.length || undefined}
          onAdd={() => void openWorkspaceDialog()}
          addLabel="Open a standalone folder (not part of a project)"
          AddIcon={FolderPlus}
          size="large"
          className="px-1 pb-1"
        />

      {!workspacesSectionCollapsed && !overviewQuery.isLoading && !overviewQuery.isError && standaloneWorkspaces.length === 0 && (
        <p className="px-2 py-3 text-xs text-(--color-text-subtle)">
          No standalone workspaces. Use the + above to open a folder
          outside any project.
        </p>
      )}

      {!workspacesSectionCollapsed && standaloneWorkspaces.map((path) => {
        const sourceIsActive = path === activeWorkspace;
        const sourceIsPending = pendingWorkspace === path;
        const sourceHasRunningSession = codingSessions.some(
          (s) => s.workspace === path && s.running === true,
        );
        const isWorkspaceExpanded = expandedWorkspaces.has(path);

        return (
          <div
            key={path}
            className={cn(
              "relative mb-1 overflow-hidden rounded-lg border transition-colors",
              sourceIsActive
                ? "border-(--color-border-strong) bg-(--bg-key)/70"
                : isWorkspaceExpanded
                  ? "border-(--color-border) bg-(--bg-page)/45"
                  : "border-transparent hover:border-(--color-border)/70 hover:bg-(--bg-key)/35",
            )}
          >
            <div className="group flex min-h-9 items-center px-1">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleWorkspaceExpanded(path);
                }}
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
                aria-expanded={isWorkspaceExpanded}
                aria-label={`${isWorkspaceExpanded ? "Collapse" : "Expand"} session history for ${workspaceLabel(path)}`}
                title={isWorkspaceExpanded ? "Hide session history" : "Show session history"}
              >
                {isWorkspaceExpanded ? (
                  <ChevronDown size={11} aria-hidden="true" />
                ) : (
                  <ChevronRight size={11} aria-hidden="true" />
                )}
              </button>
              <LongPressButton
                enabled={mobileLongPressActions}
                onLongPress={() =>
                  setMobileWorkspaceActions({ path, kind: "main" })
                }
                type="button"
                onClick={() => void selectWorkspace(path)}
                onContextMenu={(event) => {
                  if (mobileLongPressActions) return;
                  event.preventDefault();
                  const pos = clampMenuPosition(event.clientX, event.clientY);
                  setDesktopWorkspaceActions({
                    path,
                    kind: "main",
                    x: pos.x,
                    y: pos.y,
                  });
                }}
                className="flex min-w-0 flex-1 items-center gap-2 truncate rounded-md px-1.5 py-1.5 text-left text-xs transition-colors hover:bg-(--bg-key)/70"
                aria-label={`Open workspace ${workspaceLabel(path)}`}
                title={path}
              >
                <Folder
                  size={13}
                  className={`shrink-0 ${sourceIsActive ? "text-(--color-accent)" : "text-(--color-text-subtle)"}`}
                  aria-hidden="true"
                />
                <span
                  className={`min-w-0 flex-1 truncate font-semibold ${sourceIsActive ? "text-(--color-text)" : "text-(--color-text-2) group-hover:text-(--color-text)"}`}
                >
                  {workspaceLabel(path)}
                </span>
                {(sourceIsPending || sourceHasRunningSession) && (
                  <span
                    aria-label={
                      sourceHasRunningSession
                        ? "Repository has running session"
                        : undefined
                    }
                  >
                    <Loader2
                      size={11}
                      className="shrink-0 animate-spin text-(--color-text-muted)"
                      aria-hidden="true"
                    />
                  </span>
                )}
              </LongPressButton>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  void selectWorkspace(path, { create: true });
                }}
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-[opacity,background-color,color] duration-(--motion-fast) hover:bg-(--bg-key) hover:text-(--color-text) ${isMobile ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                aria-label={`New session in ${workspaceLabel(path)}`}
                title={`New session in ${workspaceLabel(path)}`}
              >
                <Plus size={12} aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  if (isMobile) {
                    setMobileWorkspaceActions({ path, kind: "main" });
                    return;
                  }
                  const rect = event.currentTarget.getBoundingClientRect();
                  const pos = clampMenuPosition(rect.right, rect.bottom + 4);
                  setDesktopWorkspaceActions({
                    path,
                    kind: "main",
                    x: pos.x,
                    y: pos.y,
                  });
                }}
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-(--color-text-subtle) transition-[opacity,background-color,color] duration-(--motion-fast) hover:bg-(--bg-key) hover:text-(--color-text) ${isMobile ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                aria-label={`More actions for ${workspaceLabel(path)}`}
                title="More actions"
              >
                <MoreHorizontal size={13} aria-hidden="true" />
              </button>
            </div>
            {isWorkspaceExpanded && (
              <div className="mx-2 mb-2 border-l border-(--color-border) pl-2">
                <WorkspaceSessionList
                  workspace={path}
                  currentSessionId={currentSessionId}
                  mobileLongPressActions={mobileLongPressActions}
                  onSessionSelect={(session) =>
                    handleSessionSelect(session, session.workspace ?? path)
                  }
                  onSessionSideChat={(session) =>
                    handleSessionSideChat(session, session.workspace ?? path)
                  }
                  onSessionDelete={handleSessionDelete}
                  pendingDeleteId={pendingDeleteSession?.id ?? null}
                  onCancelDelete={() => setPendingDeleteSession(null)}
                  onConfirmDelete={confirmSessionDelete}
                  onSessionEdit={handleSessionEdit}
                  onSessionLongPress={setMobileSessionActions}
                  onSessionContextActions={(session, event) => {
                    setDesktopSessionActions({
                      session,
                      x: event.clientX,
                      y: event.clientY,
                    });
                  }}
                />
              </div>
            )}
          </div>
        );
      })}
      </div>
    </>
  );

  // Desktop: the shell owns width persistence, the resize handle, and the
  // collapse-to-rail animation; coding keeps its stacked separate cards.
  const desktopShell = (
    <SidebarShell
      collapsed={sidebarCollapsed}
      rail={rail}
      resizeLabel="Resize coding sidebar"
    >
      <SidebarCard
        className={`shrink-0 px-2.5 pb-1 ${isMacOverlay ? 'pt-10' : 'pt-1.5'}`}
      >
        <SidebarModeSlot />
        {onCommandPalette && (
          <div className="pt-2.5">
            <SidebarSearchTrigger onClick={onCommandPalette} />
          </div>
        )}
      </SidebarCard>

      {/* Scheduler toggle */}
      <SidebarCard className="shrink-0 px-1.5 py-0.5">
        <SidebarItem
          Icon={CalendarClock}
          label="Scheduler"
          kbd="^S"
          onClick={toggleScheduler}
        />
        <SidebarItem
          Icon={Blocks}
          label="Plugins"
          kbd="^K"
          onClick={() => togglePlugins("plugins")}
        />
        <SidebarItem
          Icon={GitBranch}
          label="Source Control"
          kbd="^G"
          onClick={() => toggleSourceControl("source-control")}
        />
      </SidebarCard>

      {/* Unified workspace navigator */}
      <SidebarCard className="flex-1">
        <div className="min-h-0 flex-1 overflow-y-auto">
          {navigatorContent}
        </div>
      </SidebarCard>

      {/* Footer trio — Settings · Help | HealthDot + ThemeToggle. */}
      <SidebarCard className="shrink-0">
        <SidebarFooter onCommandPalette={onCommandPalette} />
      </SidebarCard>
    </SidebarShell>
  );

  // Responsive overlay drawer. Mobile stays compact; constrained desktop
  // preserves the user's resizable sidebar width without consuming layout.
  // When closed it stays mounted for the spring close animation but is
  // inert + hidden from AT so focus cannot land inside an off-screen drawer.
  const mobileDrawer = (
    <motion.aside
      initial={false}
      animate={{
        x: mobileOpen ? 0 : -(drawerMode ? sidebarWidth + 8 : 280),
        width: drawerMode
          ? `min(${sidebarWidth}px, calc(100vw - 2rem))`
          : "min(272px, calc(100vw - 2rem))",
      }}
      transition={preset.spring}
      aria-hidden={!mobileOpen}
      aria-label="Coding navigation"
      aria-modal={mobileOpen ? true : undefined}
      data-modal-focus={mobileOpen ? 'true' : undefined}
      {...(!mobileOpen ? { inert: true } : {})}
      className={cn(
        "mobile-safe-top fixed bottom-0 left-0 z-(--z-overlay) flex w-[min(272px,calc(100vw-2rem))] shrink-0 flex-col overflow-hidden bg-(--bg-sidebar) shadow-xl",
        !mobileOpen && "pointer-events-none",
      )}
    >
      <div className="px-3 pt-3">
        <ModeSwitchTabs active="coding" onNavigate={onMobileClose} />
        {onCommandPalette && (
          <div className="pt-1.5">
            <SidebarSearchTrigger
              onClick={() => {
                onCommandPalette();
                onMobileClose?.();
              }}
            />
          </div>
        )}
      </div>

      {/* Scheduler toggle — mobile */}
      <div className="px-3 pt-2">
        <SidebarItem
          Icon={CalendarClock}
          label="Scheduler"
          kbd="^S"
          onClick={() => {
            toggleScheduler();
            onMobileClose?.();
          }}
        />
        <SidebarItem
          Icon={Blocks}
          label="Plugins"
          kbd="^K"
          onClick={() => {
            togglePlugins("plugins");
            onMobileClose?.();
          }}
        />
        <SidebarItem
          Icon={GitBranch}
          label="Source Control"
          kbd="^G"
          onClick={() => {
            toggleSourceControl("source-control");
            onMobileClose?.();
          }}
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        {navigatorContent}
      </div>

      <div className="shrink-0 border-t border-(--color-border)">
        <SidebarFooter
          onCommandPalette={onCommandPalette}
          onAction={onMobileClose}
        />
      </div>
    </motion.aside>
  );

  return (
    <>
      <AnimatePresence>
        {isDrawer && mobileOpen && (
          <MobileDrawerBackdrop
            onClose={() => onMobileClose?.()}
            closeLabel="Close coding navigation"
            desktopVisible={drawerMode}
          />
        )}
      </AnimatePresence>

      {isDrawer ? mobileDrawer : desktopShell}

      <ProjectSetupModal
        open={showProjectModal}
        onOpenChange={setShowProjectModal}
      />

      {workspacePickerPortal && createPortal(<AnimatePresence>
        {dialogOpen && !trustWorkspace && (
          <SidePanel
            storageKey={STORAGE_KEYS.panels.codingWorkspacePicker}
            defaultWidth={480}
            minWidth={400}
            maxWidth={720}
            mobileOverlay
            mobile={isMobile}
            title={addRepoProject ? `Add repository to ${addRepoProject.name}` : "Open workspace"}
            onClose={closeWorkspaceDialog}
            closeLabel="Close workspace picker"
            resizeLabel="Resize workspace picker"
            ariaLabel="Open workspace"
            className="bg-(--bg-card)"
          >
            <div className="flex min-h-0 flex-1 flex-col gap-4 p-4">
              <p className="text-sm text-(--color-text-subtle)">
                {nativeFolderPickerEnabled && !isTauriMobile
                  ? "Use the desktop folder picker to choose a local project folder."
                  : "Choose a server-local project folder."}
              </p>
              {nativeFolderPickerEnabled && !isTauriMobile ? (
            <>
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
              <div className="mt-auto flex items-center justify-end gap-2">
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
              </div>
            </>
          ) : (
            <>
              <div className="min-h-0 flex-1 space-y-2 overflow-auto">
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
              <div className="flex items-center justify-end gap-2">
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
                  Open this folder
                </Button>
              </div>
            </>
          )}
            </div>
          </SidePanel>
        )}
      </AnimatePresence>, workspacePickerPortal)}

      <Dialog open={trustWorkspace !== null} onOpenChange={(open) => {
        if (!open) setTrustWorkspace(null);
      }}>
        <DialogContent showCloseButton={false} className="min-w-0">
          <DialogHeader>
            <DialogTitle>Trust this workspace?</DialogTitle>
            <DialogDescription>
              {addRepoProject
                ? `Coding mode grants agents filesystem and shell access. The workspace directory is the primary working area, but agents may access other paths outside it (excluding system directories). Trusting adds this folder to ${addRepoProject.name}.`
                : "Coding mode grants agents filesystem and shell access. The workspace directory is the primary working area, but agents may access other paths outside it (excluding system directories)."}
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-lg border border-(--color-border) bg-(--bg-page) px-3 py-2">
            <p className="break-all font-mono text-xs text-(--color-text-muted)">
              {trustWorkspace}
            </p>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setTrustWorkspace(null)}>
              Back
            </Button>
            <Button type="button" onClick={confirmTrustedWorkspace}>
              {addRepoProject ? "Trust and add" : "Trust and open"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={mobileWorkspaceActions !== null}
        onOpenChange={(open) => {
          if (!open) setMobileWorkspaceActions(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {mobileWorkspaceActions
                ? workspaceLabel(mobileWorkspaceActions.path)
                : "Workspace actions"}
            </DialogTitle>
            <DialogDescription>
              {mobileWorkspaceActions?.kind === "worktree"
                ? "Choose a worktree action."
                : "Choose a main workspace action."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col items-stretch gap-2 p-3 sm:flex-col">
            <Button
              type="button"
              variant="outline"
              className="justify-start"
              onClick={() => {
                const action = mobileWorkspaceActions;
                setMobileWorkspaceActions(null);
                if (action)
                  void selectWorkspace(action.path, { create: true });
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
            ) : mobileWorkspaceActions?.worktree?.managed ? (
              <Button
                type="button"
                variant="outline"
                className="justify-start text-(--color-error)"
                onClick={() => {
                  const item = mobileWorkspaceActions.worktree;
                  setMobileWorkspaceActions(null);
                  if (item) void handleRemoveWorktree(item);
                }}
              >
                <Trash2 size={14} aria-hidden="true" />
                Remove worktree
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={worktreeTarget !== null}
        onOpenChange={(open) => {
          if (!open) setWorktreeTarget(null);
        }}
      >
        <DialogContent
          showCloseButton={false}
          className="flex max-h-[min(86dvh,600px)] w-[calc(100vw-1.5rem)] max-w-md flex-col overflow-hidden rounded-lg border border-(--color-border) bg-(--bg-card) p-0 shadow-xl sm:w-[min(680px,calc(100vw-2rem))] sm:max-w-none"
        >
          <form
            onSubmit={submitWorktree}
            className="flex h-full min-h-0 flex-col"
          >
            <DialogHeader className="shrink-0 border-b border-(--color-border) bg-(--bg-page) px-4 py-3 sm:px-5">
              <div className="flex items-start gap-2.5 sm:gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-(--color-border) bg-(--bg-key) text-(--color-accent)">
                  <GitBranch size={15} aria-hidden="true" />
                </div>
                <div className="min-w-0 flex-1">
                  <DialogTitle className="text-sm font-semibold leading-5 text-(--color-text)">
                    Create worktree
                  </DialogTitle>
                  <DialogDescription className="mt-0.5 text-xs leading-4 text-(--color-text-muted)">
                    Isolated checkout from{" "}
                    {worktreeTarget
                      ? workspaceLabel(worktreeTarget)
                      : "this workspace"}
                    .
                  </DialogDescription>
                </div>
                <button
                  type="button"
                  onClick={() => setWorktreeTarget(null)}
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                  aria-label="Close create worktree dialog"
                >
                  <X size={15} aria-hidden="true" />
                </button>
              </div>
            </DialogHeader>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3 sm:px-5">
              <div className="rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-2">
                <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-(--color-text-subtle)">
                  <Folder size={12} aria-hidden="true" />
                  Source workspace
                </div>
                <p
                  className="truncate font-mono text-xs text-(--color-text-muted)"
                  title={worktreeTarget ?? undefined}
                >
                  {worktreeTarget}
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block space-y-1 text-xs font-medium text-(--color-text-2)">
                  <span>Worktree name</span>
                  <input
                    value={worktreeName}
                    onChange={(e) => setWorktreeName(e.target.value)}
                    placeholder="feature-login"
                    className="h-9 w-full min-w-0 rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-1 font-mono text-sm text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-subtle) focus-visible:border-(--focus-ring) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25"
                    maxLength={80}
                    autoFocus
                  />
                  <p className="text-xs font-normal text-(--color-text-subtle)">
                    Blank uses "session".
                  </p>
                </label>
                <label className="block space-y-1 text-xs font-medium text-(--color-text-2)">
                  <span>Branch</span>
                  <input
                    value={worktreeBranch}
                    onChange={(e) => setWorktreeBranch(e.target.value)}
                    placeholder="EvoFlux/feature-login"
                    className="h-9 w-full min-w-0 rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-1 font-mono text-sm text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-subtle) focus-visible:border-(--focus-ring) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25"
                    maxLength={255}
                  />
                  <p className="text-xs font-normal text-(--color-text-subtle)">
                    Blank defaults to EvoFlux/name.
                  </p>
                </label>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="hidden gap-2 rounded-md border border-(--color-border) bg-(--bg-key)/30 px-3 py-2 text-xs leading-4 text-(--color-text-muted) sm:flex">
                  <CircleHelp
                    size={13}
                    className="mt-0.5 shrink-0 text-(--color-text-subtle)"
                    aria-hidden="true"
                  />
                  <p>
                    Stored in EvoFlux data, outside the source repo.
                    Uncommitted source changes are not copied.
                  </p>
                </div>
                <div className="rounded-md border border-(--color-border) bg-(--bg-page) px-3 py-2 text-xs text-(--color-text-muted)">
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <p className="font-medium text-(--color-text-2)">
                      Existing worktrees
                    </p>
                    <span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-xs text-(--color-text-subtle)">
                      {worktreeOptions.length}
                    </span>
                  </div>
                  {worktreeOptions.length === 0 ? (
                    <p className="py-1 text-(--color-text-subtle)">
                      No worktrees yet.
                    </p>
                  ) : (
                    <ul className="max-h-44 space-y-1 overflow-y-auto pr-1">
                      {worktreeOptions.map((item) => (
                        <li
                          key={item.directory}
                          className="group flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 hover:bg-(--bg-key)"
                          title={item.directory}
                        >
                          <GitBranch
                            size={12}
                            className="shrink-0 text-(--color-text-subtle)"
                            aria-hidden="true"
                          />
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-(--color-text-2)">
                              {item.name}
                            </p>
                            {item.branch && (
                              <p className="truncate text-xs text-(--color-text-subtle)">
                                {item.branch}
                              </p>
                            )}
                          </div>
                          {item.managed ? (
                            <button
                              type="button"
                              onClick={() => {
                                void handleRemoveWorktree(item);
                              }}
                              disabled={worktreeRemoving === item.directory}
                              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-(--color-text-subtle) opacity-100 transition-colors hover:bg-(--color-error-subtle) hover:text-(--color-error) disabled:opacity-50 md:opacity-0 md:group-hover:opacity-100"
                              aria-label={`Remove worktree ${item.name}`}
                              title="Remove managed worktree"
                            >
                              {worktreeRemoving === item.directory ? (
                                <Loader2
                                  size={12}
                                  className="animate-spin"
                                  aria-hidden="true"
                                />
                              ) : (
                                <Trash2 size={12} aria-hidden="true" />
                              )}
                            </button>
                          ) : (
                            <span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-xs text-(--color-text-subtle)">
                              external
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
              {error && (
                <p className="rounded-md border border-(--color-error)/35 bg-(--color-error-subtle) px-3 py-2 text-xs text-(--color-error)">
                  {error}
                </p>
              )}
            </div>
            <DialogFooter className="shrink-0 flex-row justify-end gap-2 border-t border-(--color-border) bg-(--bg-page) px-4 pb-5 pt-3 sm:pl-5 sm:pr-6 sm:pb-6">
              <Button
                type="button"
                variant="outline"
                onClick={() => setWorktreeTarget(null)}
                className="h-9 w-auto px-4"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={worktreeLoading}
                className="h-9 w-auto px-4"
              >
                {worktreeLoading ? "Creating…" : "Create and open"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {desktopWorkspaceActions && (
        <div
          className="fixed inset-0 z-(--z-modal)"
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

      {/* Actions menu for a project's own repo row — desktop floating menu.
          Never offers "new session": a project's repos are managed here,
          sessions live at the project level. */}
      {projectRepoActions && !isMobile && (
        <div
          className="fixed inset-0 z-(--z-modal)"
          onClick={() => setProjectRepoActions(null)}
          onContextMenu={(event) => {
            event.preventDefault();
            setProjectRepoActions(null);
          }}
        >
          <div
            role="menu"
            aria-label={`Actions for ${workspaceLabel(projectRepoActions.path)}`}
            className="fixed min-w-48 rounded-lg border border-(--color-border) bg-(--bg-card) p-1 text-sm text-(--color-text) shadow-xl"
            style={{ left: projectRepoActions.x, top: projectRepoActions.y }}
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-(--bg-key) focus-visible:bg-(--bg-key) focus-visible:outline-none"
              onClick={() => {
                const action = projectRepoActions;
                setProjectRepoActions(null);
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
                const action = projectRepoActions;
                setProjectRepoActions(null);
                setRemoveProjectWorkspaceTarget(action);
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
              Remove from project
            </button>
          </div>
        </div>
      )}

      {/* Same actions, mobile bottom sheet. */}
      <Dialog
        open={isMobile && projectRepoActions !== null}
        onOpenChange={(open) => {
          if (!open) setProjectRepoActions(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {projectRepoActions ? workspaceLabel(projectRepoActions.path) : "Repository actions"}
            </DialogTitle>
            <DialogDescription>Choose a repository action.</DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex-col items-stretch gap-2 p-3 sm:flex-col">
            <Button
              type="button"
              variant="outline"
              className="justify-start"
              onClick={() => {
                const action = projectRepoActions;
                setProjectRepoActions(null);
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
                const action = projectRepoActions;
                setProjectRepoActions(null);
                if (action) setRemoveProjectWorkspaceTarget(action);
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
              Remove from project
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <SessionContextMenu
        anchor={desktopSessionActions}
        onClose={() => setDesktopSessionActions(null)}
        onEdit={handleSessionEdit}
        onDelete={handleSessionDelete}
        pinned={
          desktopSessionActions
            ? pinnedIdSet.has(desktopSessionActions.session.id)
            : false
        }
        onTogglePin={() => {
          if (desktopSessionActions) togglePin(desktopSessionActions.session.id);
        }}
      />

      <SessionActionsDialog
        session={mobileSessionActions}
        onClose={() => setMobileSessionActions(null)}
        onEdit={handleSessionEdit}
        onDelete={handleSessionDelete}
        pinned={
          mobileSessionActions ? pinnedIdSet.has(mobileSessionActions.id) : false
        }
        onTogglePin={() => {
          if (mobileSessionActions) togglePin(mobileSessionActions.id);
        }}
      />

      <EditSessionTitleDialog
        session={editTarget}
        title={editTitle}
        onTitleChange={setEditTitle}
        onClose={() => setEditTarget(null)}
        onSubmit={(title) => {
          if (!editTarget) return;
          updateSessionTitle.mutate(
            { id: editTarget.id, title },
            { onSuccess: () => setEditTarget(null) },
          );
        }}
        isPending={updateSessionTitle.isPending}
        isError={updateSessionTitle.isError}
      />

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
              &rdquo; will be removed from EvoFlux. All chat sessions, uploads,
              snapshots, managed worktrees, and code graph/index data for it
              will be permanently deleted. The source repository stays on disk.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="p-3">
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
              Remove and delete data
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={removeProjectWorkspaceTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRemoveProjectWorkspaceTarget(null);
        }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Remove repository from project</DialogTitle>
            <DialogDescription>
              Removing &ldquo;
              {removeProjectWorkspaceTarget
                ? workspaceLabel(removeProjectWorkspaceTarget.path)
                : ""}
              &rdquo; resets all chat sessions for this project and deletes this
              repository&apos;s code graph/index cache. Source files stay on disk.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="p-3">
            <Button
              type="button"
              variant="outline"
              disabled={removeWorkspaceMutation.isPending}
              onClick={() => setRemoveProjectWorkspaceTarget(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={!removeProjectWorkspaceTarget || removeWorkspaceMutation.isPending}
              onClick={() => {
                const target = removeProjectWorkspaceTarget;
                if (!target) return;
                const isRemovingFromActiveProject =
                  currentProjectId === target.project.id ||
                  params.focusId === target.project.id;
                removeWorkspaceMutation.mutate(
                  {
                    projectId: target.project.id,
                    workspaceId: target.workspaceId,
                  },
                  {
                    onSuccess: () => {
                      queryClient.removeQueries({
                        queryKey: queryKeys.codeGraph.all(target.path),
                      });
                      clearLastCodingFocus(target.project.id);
                      if (isRemovingFromActiveProject) {
                        useTeamStore.getState().newSession();
                        navigate({ to: "/coding", replace: true });
                      }
                      setRemoveProjectWorkspaceTarget(null);
                    },
                    onError: (err) => {
                      useToastStore.getState().push({
                        tone: "error",
                        title: "Couldn't remove repository",
                        description:
                          err instanceof Error ? err.message : String(err),
                      });
                    },
                  },
                );
              }}
            >
              {removeWorkspaceMutation.isPending
                ? "Removing..."
                : "Remove and reset sessions"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={deleteProjectTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteProjectTarget(null);
        }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete project</DialogTitle>
            <DialogDescription>
              {deleteProjectTarget
                ? `Delete ${deleteProjectTarget.name}? All project chat sessions, scheduled tasks, generated session data, and unshared code graph/index caches will be permanently deleted. Source repositories stay on disk and remain available in Workspaces.`
                : "Delete this project?"}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="p-3">
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeleteProjectTarget(null)}
              disabled={deleteProjectMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={!deleteProjectTarget || deleteProjectMutation.isPending}
              onClick={() => {
                const target = deleteProjectTarget;
                if (!target) return;
                const isDeletingActiveProject =
                  currentProjectId === target.id || params.focusId === target.id;
                deleteProjectMutation.mutate(target.id, {
                  onSuccess: () => {
                    for (const workspace of target.workspaces ?? []) {
                      queryClient.removeQueries({
                        queryKey: queryKeys.codeGraph.all(workspace.path),
                      });
                    }
                    clearLastCodingFocus(target.id);
                    setExpandedProjects((current) => {
                      if (!current.has(target.id)) return current;
                      const next = new Set(current);
                      next.delete(target.id);
                      return next;
                    });
                    if (isDeletingActiveProject) {
                      // Route params are the reliable fallback when the
                      // active session is absent from paginated query data or
                      // its project binding has already been cleared.
                      useTeamStore.getState().newSession();
                      navigate({ to: "/coding", replace: true });
                    }
                    setDeleteProjectTarget(null);
                  },
                  onError: (err) => {
                    useToastStore.getState().push({
                      tone: "error",
                      title: "Couldn't delete project",
                      description: err instanceof Error ? err.message : String(err),
                    });
                  },
                });
              }}
            >
              {deleteProjectMutation.isPending ? "Deleting..." : "Delete project"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
