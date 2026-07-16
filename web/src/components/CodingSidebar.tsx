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
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useIsMobile } from "@/hooks/use-mobile";
import { usePlatform } from "@/hooks/use-platform";
import { useResizableWidth } from "@/hooks/use-resizable-width";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import {
  ArrowRightLeft,
  ChevronDown,
  ChevronRight,
  Code2,
  Folder,
  FolderPlus,
  Gauge,
  GitBranch,
  HelpCircle,
  CircleHelp,
  Loader2,
  Pencil,
  Plus,
  Search,
  Settings,
  Trash2,
  X,
} from "lucide-react";
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
import {
  prependSession,
  prependWorkspaceSession,
} from "@/stores/cache-invalidation-bridge";
import { formatRelativeDate } from "@/utils/format";
import { codingFocusId, saveLastCodingWorkspace, workspaceLabel } from "@/utils/workspace";
import { isTransientNetworkError } from "@/utils/errors";
import { useUIStore } from "@/stores/useUIStore";
import { ThemeToggle } from "./ThemeToggle";
import { HealthDot } from "./HealthDot";
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
  useRemoveWorkspaceMutation,
} from "@/queries/useProjectsQuery";
import { ProjectSetupModal } from "@/components/ProjectSetupModal";


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

interface CodingSidebarProps {
  currentSessionId?: string;
  workspace?: string | null;
  onCollapse?: () => void;
  /** Bump this counter to programmatically open the workspace dialog
   *  (e.g. from a "no workspace attached" CTA). */
  openWorkspaceDialogKey?: number;
  /** Open the command palette (search input + footer help). */
  onCommandPalette?: () => void;
  /** Desktop only: when true, the inline panel collapses to width=0. */
  desktopCollapsed?: boolean;
  /** Mobile only: whether the overlay drawer is open. */
  mobileOpen?: boolean;
  /** Mobile only: called when the drawer should close (backdrop tap, navigation). */
  onMobileClose?: () => void;
}

interface SessionListActionProps {
  currentSessionId?: string;
  mobileLongPressActions?: boolean;
  onSessionSelect: (session: SessionResponse) => void;
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
  const projectSessions = allSessions.filter(
    (s) => !s.scheduled_task_name,
  );

  return (
    <div className="space-y-0.5 pb-2 pl-4 pr-2">
      {projectSessions.length === 0 && !sessions.isLoading && (
        <p className="px-2 py-1 text-xs text-(--color-text-subtle)">
          No sessions yet.
        </p>
      )}
      {sessions.isLoading && (
        <div className="flex items-center gap-1.5 px-2 py-1">
          <Loader2 size={10} className="animate-spin text-(--color-text-muted)" />
          <span className="text-xs text-(--color-text-muted)">Loading…</span>
        </div>
      )}
      {projectSessions.map((session) => {
        const isCurrent = session.id === currentSessionId;
        const isRunning = session.running === true;
        const isPendingDelete = pendingDeleteId === session.id;
        return (
          <div key={session.id} className="group relative">
            <LongPressButton
              enabled={mobileLongPressActions}
              onLongPress={() => onSessionLongPress(session)}
              type="button"
              onClick={() => onSessionSelect(session)}
              onDoubleClick={(e) => {
                e.stopPropagation();
                onSessionEdit(session);
              }}
              onContextMenu={(e) => {
                if (mobileLongPressActions) return;
                e.preventDefault();
                onSessionContextActions(session, e);
              }}
              className={`w-full rounded-md px-2 py-1 text-left text-xs transition-colors ${
                isCurrent
                  ? "bg-(--bg-key) text-(--color-text)"
                  : "text-(--color-text-2) hover:bg-(--bg-key)/50 hover:text-(--color-text)"
              }`}
            >
              <div className="flex min-w-0 items-center gap-1.5">
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${isRunning ? "bg-(--color-accent)" : "bg-(--color-border)"}`}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1 truncate font-medium">
                  {session.title || "Untitled"}
                </span>
                <span className="shrink-0 text-[10px] text-(--color-text-subtle)">
                  {formatRelativeDate(session.created_at)}
                </span>
              </div>
            </LongPressButton>
            {!isPendingDelete && (
              <>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSessionEdit(session);
                  }}
                  className="absolute right-6 top-1/2 flex -translate-y-1/2 items-center justify-center rounded-xs p-1 text-(--color-text-subtle) opacity-0 transition-all hover:bg-(--bg-key) hover:text-(--color-text) group-hover:opacity-100 pointer-coarse:opacity-100"
                  aria-label={`Edit session ${session.title || "Untitled"}`}
                >
                  <Pencil size={11} />
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSessionDelete(session);
                  }}
                  className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center justify-center rounded-xs p-1 text-(--color-text-subtle) opacity-0 transition-all hover:bg-(--color-error-subtle) hover:text-(--color-error) group-hover:opacity-100 pointer-coarse:opacity-100"
                  aria-label={`Delete session ${session.title || "Untitled"}`}
                >
                  <Trash2 size={11} />
                </button>
              </>
            )}
            {isPendingDelete && (
              <div className="absolute inset-y-0 right-1 z-10 flex items-center gap-1">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onCancelDelete();
                  }}
                  className="rounded-xs border border-(--color-border) bg-(--bg-card) px-2 py-1 text-xs text-(--color-text) hover:bg-(--bg-key)"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onConfirmDelete();
                  }}
                  className="rounded-xs bg-(--color-error) px-2 py-1 text-xs text-(--color-text-on-accent) hover:bg-(--color-error)/90"
                >
                  Delete
                </button>
              </div>
            )}
          </div>
        );
      })}
      {sessions.hasNextPage && (
        <button
          type="button"
          onClick={() => void sessions.fetchNextPage()}
          disabled={sessions.isFetchingNextPage}
          className="mt-1 flex w-full items-center justify-center gap-1 rounded-md px-2 py-1.5 text-xs text-(--color-accent) transition-colors hover:bg-(--bg-key) disabled:opacity-60"
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
  onCollapse,
  openWorkspaceDialogKey = 0,
  onCommandPalette,
  desktopCollapsed = false,
  mobileOpen = false,
  onMobileClose,
}: CodingSidebarProps) {
  const isMobile = useIsMobile();
  const { isTauri, os, isMacOverlay } = usePlatform();
  const [nativeFolderPickerEnabled, setNativeFolderPickerEnabled] =
    useState(isTauri);
  const isTauriMobile = isTauri && (os === "ios" || os === "android");
  const mobileLongPressActions = isMobile && isTauriMobile && mobileOpen;
  const prefersReducedMotion = useReducedMotion();
  // ``onCollapse`` is wired by TeamChatView's left-chrome hamburger.
  // We don't render an inline collapse toggle anymore — the topbar
  // hamburger and Ctrl+B own that surface.
  void onCollapse;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const sessions = useTeamSessionsQuery();
  const deleteSession = useDeleteTeamSessionMutation();
  const updateSessionTitle = useUpdateTeamSessionTitleMutation();
  // One merged query for both Projects and standalone Workspaces — see
  // useCodingOverviewQuery's doc comment for why this replaced two
  // independently-fetched lists reconciled by path-string matching.
  const overviewQuery = useCodingOverviewQuery();
  const projects = overviewQuery.data?.projects ?? [];
  const addWorkspaceMutation = useAddWorkspaceMutation();
  const removeWorkspaceMutation = useRemoveWorkspaceMutation();
  const [showProjectModal, setShowProjectModal] = useState(false);
  const [pendingProject, setPendingProject] = useState<string | null>(null);
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(
    () => new Set(),
  );
  const [expandedWorkspaces, setExpandedWorkspaces] = useState<Set<string>>(
    () => new Set(),
  );
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
  // (primed synchronously in forge.tsx), so it survives even when the active
  // session lives on an unloaded page of the paginated global list. Prefer it,
  // falling back to the list lookup only before the store is primed.
  const storeProjectId = useTeamStore((s) => s.projectId);
  const currentProjectId =
    storeProjectId ??
    codingSessions.find((s) => s.id === currentSessionId)?.project_id ??
    null;

  const workspaceTree = overviewQuery.data?.repositories ?? [];
  const activeWorkspace = workspace ?? null;
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
  const editTitleInputRef = useRef<HTMLInputElement>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [mobileSessionActions, setMobileSessionActions] =
    useState<SessionResponse | null>(null);
  const [desktopSessionActions, setDesktopSessionActions] = useState<{
    session: SessionResponse;
    x: number;
    y: number;
  } | null>(null);
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
      if (typeof selected !== "string") return;
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
    await queryClient.invalidateQueries({ queryKey: queryKeys.codingOverview() });
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

  useEffect(() => {
    if (editTarget) editTitleInputRef.current?.focus();
  }, [editTarget]);

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
    saveLastCodingWorkspace(path);
    setPendingWorkspace(path);
    try {
      // Only carry the current model/thinking-level over when there's an
      // existing session to carry them FROM — otherwise a stale value left
      // over from a different mode's session gets sent here and can be
      // rejected as "Choose a model from the registry." (see forge.tsx).
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
        skipInitialRestore: create && session.created,
      });
      if (create && session.created) {
        prependSession(queryClient, session);
        prependWorkspaceSession(queryClient, path, session);
      }
      await refreshWorkspaceTree();
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

  // Remove a workspace from the sidebar. Sessions stay in the backend —
  // reopening the same folder later resurfaces them. If the removed
  // workspace was the active one, navigate back to the empty /coding
  // route so the URL doesn't reference a workspace that no longer
  // appears in the sidebar. Called from the confirmation dialog below.
  const confirmRemoveWorkspace = () => {
    const path = removeWorkspaceTarget;
    if (!path) return;
    void setCodingWorkspaceVisibility(path, true)
      .then(() => {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.team.sessions.all(),
        });
        void refreshWorkspaceTree();
      })
      .catch(() => undefined);
    if (path === activeWorkspace) {
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
      prependSession(queryClient, session);
      prependWorkspaceSession(queryClient, path, session);
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
  const resizable = useResizableWidth({
    storageKey: "oa.codingSidebar.width",
    defaultWidth: 256,
    minWidth: 220,
    maxWidth: 420,
    edge: "right",
    disabled: isMobile || desktopCollapsed,
  });

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

  const handleSessionDelete = (session: SessionResponse) => {
    setPendingDeleteId(session.id);
  };

  const handleSessionEdit = (session: SessionResponse) => {
    setEditTarget(session);
    setEditTitle(session.title || "");
  };

  const submitSessionTitle = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editTarget) return;
    const title = editTitle.trim();
    if (!title) return;
    updateSessionTitle.mutate(
      { id: editTarget.id, title },
      { onSuccess: () => setEditTarget(null) },
    );
  };

  const confirmSessionDelete = () => {
    if (!pendingDeleteId) return;
    const target = codingSessions.find((s) => s.id === pendingDeleteId);
    if (!target) return;
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
    setPendingDeleteId(null);
  };

  return (
    <>
      {/* Mobile backdrop — closes the drawer on tap. */}
      <AnimatePresence>
        {isMobile && mobileOpen && (
          <motion.div
            key="coding-sidebar-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: prefersReducedMotion ? 0.01 : 0.2 }}
            className="mobile-safe-top fixed inset-x-0 bottom-0 z-30 bg-(--color-overlay) md:hidden"
            aria-hidden="true"
            onClick={onMobileClose}
          />
        )}
      </AnimatePresence>

      <motion.aside
        initial={false}
        animate={
          isMobile
            ? {
                x: mobileOpen ? 0 : -280,
                width: "min(272px, calc(100vw - 2rem))",
              }
            : { width: desktopCollapsed ? (isMacOverlay ? 70 : 56) : resizable.width }
        }
        transition={{
          duration: prefersReducedMotion ? 0.01 : 0.22,
          ease: [0.4, 0, 0.2, 1],
        }}
        className={
          isMobile
            ? "mobile-safe-top fixed bottom-0 left-0 z-40 flex w-[min(272px,calc(100vw-2rem))] shrink-0 flex-col overflow-hidden bg-(--bg-sidebar) shadow-xl"
            : "relative flex shrink-0 flex-col overflow-hidden"
        }
      >
        {!isMobile && !desktopCollapsed && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize coding sidebar"
            title="Drag to resize · double-click to reset"
            className="absolute right-0 top-0 z-20 h-full w-1 cursor-col-resize transition-colors hover:bg-(--color-accent)/40"
            onPointerDown={resizable.startResize}
            onDoubleClick={resizable.resetWidth}
          />
        )}

        {/* Collapsed icon strip — desktop only, mirrors Forge sidebar collapsed state */}
        {!isMobile && desktopCollapsed && (
          <div className="flex h-full flex-col items-center gap-1 overflow-hidden p-1">
            <div
              className={`flex w-full shrink-0 flex-col items-center gap-0.5 rounded-[10px] bg-(--bg-sidebar)/80 px-1 pb-2 shadow-sm backdrop-blur-xl ${isMacOverlay ? 'pt-10' : 'pt-2'}`}
            >
              <button
                type="button"
                onClick={() => navigate({ to: '/' })}
                title="Forge"
                className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
              >
                <Gauge size={16} aria-hidden="true" />
              </button>
              <button
                type="button"
                title="Coding"
                className="flex h-8 w-8 items-center justify-center rounded-md bg-(--bg-key) text-(--color-accent)"
              >
                <Code2 size={16} aria-hidden="true" />
              </button>
              {onCommandPalette && (
                <button
                  type="button"
                  onClick={onCommandPalette}
                  title="Search (Ctrl+P)"
                  className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
                >
                  <Search size={15} aria-hidden="true" />
                </button>
              )}
              <button
                type="button"
                onClick={() => { void openWorkspaceDialog(); }}
                title="Open folder"
                className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
              >
                <Folder size={15} aria-hidden="true" />
              </button>
            </div>
            <div className="flex-1" />
            <div className="flex w-full shrink-0 flex-col items-center gap-1 rounded-[10px] bg-(--bg-sidebar)/80 px-1 py-2 shadow-sm backdrop-blur-xl">
              <button
                type="button"
                onClick={() => { useUIStore.getState().openSettings(); }}
                className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                aria-label="Settings"
                title="Settings"
              >
                <Settings size={14} aria-hidden="true" />
              </button>
              {onCommandPalette && (
                <button
                  type="button"
                  onClick={onCommandPalette}
                  className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                  aria-label="Help and shortcuts"
                  title="Help and shortcuts"
                >
                  <HelpCircle size={14} aria-hidden="true" />
                </button>
              )}
              <ThemeToggle collapsed />
              <HealthDot />
            </div>
          </div>
        )}

        {/* Content sections — desktop gets floating cards, mobile stays flat. */}
        <div
          className={
            !isMobile && desktopCollapsed
              ? "hidden"
              : !isMobile
                ? "flex h-full flex-col gap-1 overflow-hidden p-1"
                : "flex flex-1 flex-col overflow-hidden"
          }
        >
        {isMobile && (
          <div className="px-3 pt-3">
            <div className="flex h-8 items-center rounded-md border border-(--color-border) bg-(--bg-page) p-0.5">
              <button
                type="button"
                onClick={() => { navigate({ to: "/" }); onMobileClose?.(); }}
                className="flex h-full flex-1 items-center justify-center gap-1.5 rounded-[5px] px-2 text-xs font-medium text-(--color-text-muted) transition-colors hover:text-(--color-text)"
              >
                <Gauge size={12} aria-hidden="true" />
                Forge
              </button>
              <button
                type="button"
                onClick={() => {}}
                className="flex h-full flex-1 items-center justify-center gap-1.5 rounded-[5px] px-2 text-xs font-medium bg-(--bg-key) text-(--color-text) shadow-sm transition-colors"
              >
                <Code2 size={12} aria-hidden="true" />
                Coding
              </button>
              <button
                type="button"
                onClick={() => { navigate({ to: "/aim" }); onMobileClose?.(); }}
                className="flex h-full flex-1 items-center justify-center gap-1.5 rounded-[5px] px-2 text-xs font-medium text-(--color-text-muted) transition-colors hover:text-(--color-text)"
              >
                <ArrowRightLeft size={12} aria-hidden="true" />
                AIM
              </button>
            </div>
          </div>
        )}

        {/* Mode switch — desktop */}
        {!isMobile && (
          <div
            className={`shrink-0 rounded-[10px] bg-(--bg-sidebar)/80 px-2 pb-2 shadow-sm backdrop-blur-xl ${isMacOverlay ? 'pt-10' : 'pt-2'}`}
          >
            <div className="flex h-8 items-center rounded-md border border-(--color-border) bg-(--bg-page) p-0.5">
              <button
                type="button"
                onClick={() => navigate({ to: "/" })}
                className="flex h-full flex-1 items-center justify-center gap-1.5 rounded-[5px] px-2 text-xs font-medium text-(--color-text-muted) transition-colors hover:text-(--color-text)"
              >
                <Gauge size={12} aria-hidden="true" />
                Forge
              </button>
              <button
                type="button"
                onClick={() => {}}
                className="flex h-full flex-1 items-center justify-center gap-1.5 rounded-[5px] px-2 text-xs font-medium bg-(--bg-key) text-(--color-text) shadow-sm transition-colors"
              >
                <Code2 size={12} aria-hidden="true" />
                Coding
              </button>
              <button
                type="button"
                onClick={() => navigate({ to: "/aim" })}
                className="flex h-full flex-1 items-center justify-center gap-1.5 rounded-[5px] px-2 text-xs font-medium text-(--color-text-muted) transition-colors hover:text-(--color-text)"
              >
                <ArrowRightLeft size={12} aria-hidden="true" />
                AIM
              </button>
            </div>
          </div>
        )}

        {/* Search trigger — opens the command palette (Ctrl+P). */}
        {onCommandPalette && (
          <div
            className={
              isMobile
                ? "px-3 pt-3"
                : "shrink-0 rounded-[10px] bg-(--bg-sidebar)/80 px-2 py-2 shadow-sm backdrop-blur-xl"
            }
          >
            <button
              type="button"
              onClick={onCommandPalette}
              className="flex h-8 w-full items-center gap-2 rounded-md border border-(--color-border) bg-(--bg-key)/60 px-2.5 text-left text-xs text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
              aria-label="Open command palette"
              title="Open command palette (Ctrl+P)"
            >
              <Search size={13} aria-hidden="true" />
              <span className="flex-1">Search…</span>
              <kbd className="font-mono text-xs text-(--color-text-subtle)">
                ^P
              </kbd>
            </button>
          </div>
        )}

        {/* Unified workspace navigator */}
        <div
          className={`flex min-h-0 flex-1 flex-col overflow-y-auto${!isMobile ? " rounded-[10px] bg-(--bg-sidebar)/80 shadow-sm backdrop-blur-xl" : ""}`}
        >
          {/* PROJECTS */}
          <div className="px-2 pt-2 pb-1">
            <div className="flex items-center justify-between px-1 pb-1">
              <button
                type="button"
                onClick={() => setProjectsSectionCollapsed((v) => !v)}
                className="flex min-w-0 flex-1 items-center gap-1 rounded-xs py-0.5 text-left hover:bg-(--bg-key)"
                aria-expanded={!projectsSectionCollapsed}
                aria-label={`${projectsSectionCollapsed ? "Expand" : "Collapse"} Projects section`}
              >
                {projectsSectionCollapsed ? (
                  <ChevronRight size={10} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
                ) : (
                  <ChevronDown size={10} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
                )}
                <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Projects
                </span>
              </button>
              <button
                type="button"
                onClick={() => setShowProjectModal(true)}
                className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
                title="New multi-repo project"
              >
                <Plus size={12} />
              </button>
            </div>

            {!projectsSectionCollapsed && overviewQuery.isLoading && (
              <div className="flex items-center gap-1.5 px-2 py-1.5">
                <Loader2 size={11} className="animate-spin text-(--color-text-muted)" />
                <span className="text-xs text-(--color-text-muted)">Loading…</span>
              </div>
            )}

            {!projectsSectionCollapsed && !overviewQuery.isLoading && projects.length === 0 && (
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
            <div className="space-y-0.5">
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
                  <div key={project.id}>
                    <div className="group flex h-8 items-center pr-2">
                      <button
                        type="button"
                        onClick={() => toggleProjectExpanded(project.id)}
                        className={`flex min-w-0 flex-1 items-center gap-1.5 rounded-xs px-1 py-1 text-left text-xs transition-colors hover:bg-(--bg-key) ${isActive ? "text-(--color-accent)" : "text-(--color-text-2)"}`}
                        aria-expanded={isExpanded}
                        aria-label={`${isExpanded ? "Collapse" : "Expand"} project ${project.name}`}
                      >
                        {isExpanded ? (
                          <ChevronDown size={10} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
                        ) : (
                          <ChevronRight size={10} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
                        )}
                        <FolderPlus
                          size={12}
                          className={`shrink-0 ${isActive ? "text-(--color-accent)" : "text-(--color-text-subtle)"}`}
                          aria-hidden="true"
                        />
                        <span className={`min-w-0 flex-1 truncate font-medium ${isActive ? "text-(--color-text)" : ""}`}>
                          {project.name}
                        </span>
                        <span className="shrink-0 rounded-full bg-(--bg-key) px-1.5 py-0.5 text-[10px] text-(--color-text-muted)">
                          {project.workspaces?.length ?? 0}
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
                        <button
                          type="button"
                          onClick={() => void openProjectSession(project)}
                          disabled={!canCreateSession}
                          className={`ml-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-xs border border-(--color-border) text-(--color-text-muted) transition-all hover:bg-(--bg-key) hover:text-(--color-text-2) disabled:cursor-not-allowed disabled:opacity-40 ${isMobile ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                          aria-label={canCreateSession ? `New session in ${project.name}` : `${project.name} has no repositories yet`}
                          title={canCreateSession ? `New session in ${project.name}` : "Add a repository to this project first"}
                        >
                          <Plus size={11} aria-hidden="true" />
                        </button>
                      )}
                    </div>
                    {isExpanded && (
                      <div className="pb-1 pl-4 pr-2">
                        <div className="flex items-center justify-between px-2 py-1">
                          <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
                            Repos
                          </span>
                          <button
                            type="button"
                            onClick={() => openAddRepoDialog(project.id)}
                            className="flex h-4 w-4 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
                            title={`Add repository to ${project.name}`}
                            aria-label={`Add repository to ${project.name}`}
                          >
                            <Plus size={10} aria-hidden="true" />
                          </button>
                        </div>
                        {(project.workspaces ?? []).length === 0 && (
                          <p className="px-2 py-1 text-xs text-(--color-text-subtle)">
                            No repos yet.
                          </p>
                        )}
                        {(project.workspaces ?? []).map((w) => (
                          <button
                            key={w.workspace_id}
                            type="button"
                            onClick={(event) =>
                              setProjectRepoActions({
                                project,
                                workspaceId: w.workspace_id,
                                path: w.path,
                                x: event.clientX,
                                y: event.clientY,
                              })
                            }
                            onContextMenu={(event) => {
                              event.preventDefault();
                              setProjectRepoActions({
                                project,
                                workspaceId: w.workspace_id,
                                path: w.path,
                                x: event.clientX,
                                y: event.clientY,
                              });
                            }}
                            className="flex w-full min-w-0 items-center gap-1.5 truncate rounded-xs px-2 py-1 text-left text-xs text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                            aria-label={`Actions for repository ${w.display_name || w.name || workspaceLabel(w.path)}`}
                            title={w.path}
                          >
                            <Folder size={11} className="shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
                            <span className="min-w-0 flex-1 truncate">
                              {w.display_name || w.name || workspaceLabel(w.path)}
                            </span>
                          </button>
                        ))}
                      </div>
                    )}
                    {isExpanded && (
                      <ProjectSessionList
                        projectId={project.id}
                        currentSessionId={currentSessionId}
                        mobileLongPressActions={mobileLongPressActions}
                        onSessionSelect={(session) =>
                          handleSessionSelect(session, session.workspace ?? "")
                        }
                        onSessionDelete={handleSessionDelete}
                        pendingDeleteId={pendingDeleteId}
                        onCancelDelete={() => setPendingDeleteId(null)}
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
                    )}
                  </div>
                );
              })}
            </div>
            )}
          </div>

          {/* Divider between Projects and Workspaces */}
          <div className="mx-2 my-1.5 border-t border-(--color-border)/50" />

          {/* WORKSPACES section header — standalone repos only. A repo that
              belongs to a project lives in that project's own "Repos" list
              above, not here (a project's repo has no standalone session). */}
          <div className="flex items-center justify-between px-3 pb-1">
            <button
              type="button"
              onClick={() => setWorkspacesSectionCollapsed((v) => !v)}
              className="flex min-w-0 flex-1 items-center gap-1 rounded-xs py-0.5 text-left hover:bg-(--bg-key)"
              aria-expanded={!workspacesSectionCollapsed}
              aria-label={`${workspacesSectionCollapsed ? "Expand" : "Collapse"} Workspaces section`}
            >
              {workspacesSectionCollapsed ? (
                <ChevronRight size={10} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
              ) : (
                <ChevronDown size={10} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
              )}
              <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-muted)">
                Workspaces
              </span>
            </button>
            <button
              type="button"
              onClick={() => void openWorkspaceDialog()}
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
              title="Open a standalone folder (not part of a project)"
              aria-label="Open a standalone folder"
            >
              <FolderPlus size={12} />
            </button>
          </div>

          {!workspacesSectionCollapsed && standaloneWorkspaces.length === 0 && (
            <p className="px-3 py-3 text-xs text-(--color-text-subtle)">
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
              <div key={path} className="relative">
                <div className="group flex h-8 items-center pl-2 pr-2">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleWorkspaceExpanded(path);
                    }}
                    className="flex h-5 w-5 shrink-0 items-center justify-center rounded-xs text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
                    aria-expanded={isWorkspaceExpanded}
                    aria-label={`${isWorkspaceExpanded ? "Collapse" : "Expand"} session history for ${workspaceLabel(path)}`}
                    title={isWorkspaceExpanded ? "Hide session history" : "Show session history"}
                  >
                    {isWorkspaceExpanded ? (
                      <ChevronDown size={10} aria-hidden="true" />
                    ) : (
                      <ChevronRight size={10} aria-hidden="true" />
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
                      setDesktopWorkspaceActions({
                        path,
                        kind: "main",
                        x: event.clientX,
                        y: event.clientY,
                      });
                    }}
                    className="flex min-w-0 flex-1 items-center gap-1.5 truncate rounded-xs px-2 py-1 text-left text-xs transition-colors hover:bg-(--bg-key)"
                    aria-label={`Open workspace ${workspaceLabel(path)}`}
                    title={path}
                  >
                    <Folder
                      size={12}
                      className={`shrink-0 ${sourceIsActive ? "text-(--color-accent)" : "text-(--color-text-subtle)"}`}
                      aria-hidden="true"
                    />
                    <span
                      className={`min-w-0 flex-1 truncate font-medium ${sourceIsActive ? "text-(--color-text)" : "text-(--color-text-2) group-hover:text-(--color-text)"}`}
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
                    className={`ml-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-xs border border-(--color-border) text-(--color-text-muted) transition-all hover:bg-(--bg-key) hover:text-(--color-text-2) ${isMobile ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                    aria-label={`New session in ${workspaceLabel(path)}`}
                    title={`New session in ${workspaceLabel(path)}`}
                  >
                    <Plus size={11} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void openWorktreeDialog(path);
                    }}
                    className={`ml-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-xs border border-(--color-border) text-(--color-text-muted) transition-all hover:bg-(--bg-key) hover:text-(--color-text-2) ${isMobile ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                    aria-label={`Create worktree from ${workspaceLabel(path)}`}
                    title="Create worktree"
                  >
                    <GitBranch size={11} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setRemoveWorkspaceTarget(path)}
                    className={`ml-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-xs text-(--color-text-subtle) transition-all hover:bg-(--color-error-subtle) hover:text-(--color-error) ${isMobile ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
                    aria-label={`Hide repository ${workspaceLabel(path)} from sidebar`}
                    title="Hide repository from sidebar"
                  >
                    <Trash2 size={11} aria-hidden="true" />
                  </button>
                </div>
                {isWorkspaceExpanded && (
                  <WorkspaceSessionList
                    workspace={path}
                    currentSessionId={currentSessionId}
                    mobileLongPressActions={mobileLongPressActions}
                    onSessionSelect={(session) =>
                      handleSessionSelect(session, session.workspace ?? path)
                    }
                    onSessionDelete={handleSessionDelete}
                    pendingDeleteId={pendingDeleteId}
                    onCancelDelete={() => setPendingDeleteId(null)}
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
                )}
              </div>
            );
          })}

        </div>

        <ProjectSetupModal
          open={showProjectModal}
          onOpenChange={setShowProjectModal}
        />

        {/* Footer trio — Settings · Help · HealthDot + ThemeToggle. Mirrors
          the forge sidebar so both feel like the same shell. */}
        <div
          className={`flex shrink-0 items-center justify-between gap-2 px-3 py-2 pb-safe${!isMobile ? " rounded-[10px] bg-(--bg-sidebar)/80 shadow-sm backdrop-blur-xl" : " border-t border-(--color-border)"}`}
        >
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => {
                useUIStore.getState().openSettings();
                onMobileClose?.();
              }}
              className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
              aria-label="Settings"
              title="Settings"
            >
              <Settings size={14} aria-hidden="true" />
            </button>
            {onCommandPalette && (
              <button
                type="button"
                onClick={onCommandPalette}
                className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
                aria-label="Help and shortcuts"
                title="Help and shortcuts (Ctrl+P)"
              >
                <HelpCircle size={14} aria-hidden="true" />
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <HealthDot />
            <ThemeToggle collapsed />
          </div>
        </div>
        </div>

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
                    {addRepoProject
                      ? `Coding mode grants agents filesystem and shell access. The workspace directory is the primary working area, but agents may access other paths outside it (excluding system directories). Once added to ${addRepoProject.name}.`
                      : "Coding mode grants agents filesystem and shell access. The workspace directory is the primary working area, but agents may access other paths outside it (excluding system directories)."}
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
                    {addRepoProject ? "Trust and add" : "Trust and open"}
                  </Button>
                </DialogFooter>
              </>
            ) : nativeFolderPickerEnabled && !isTauriMobile ? (
              <>
                <DialogHeader>
                  <DialogTitle>
                    {addRepoProject ? `Add repository to ${addRepoProject.name}` : "Open workspace"}
                  </DialogTitle>
                  <DialogDescription>
                    Use the desktop folder picker to choose a local project
                    folder.
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
                  <DialogTitle>
                    {addRepoProject ? `Add repository to ${addRepoProject.name}` : "Open workspace"}
                  </DialogTitle>
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
                    Open this folder
                  </Button>
                </DialogFooter>
              </>
            )}
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
                  <p className="rounded-md border border-(--color-error)/30 bg-(--color-error-subtle) px-3 py-2 text-xs text-(--color-error)">
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

        {/* Actions menu for a project's own repo row — desktop floating menu.
            Never offers "new session": a project's repos are managed here,
            sessions live at the project level. */}
        {projectRepoActions && !isMobile && (
          <div
            className="fixed inset-0 z-50"
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
                  removeWorkspaceMutation.mutate(
                    { projectId: action.project.id, workspaceId: action.workspaceId },
                    {
                      onError: (err) => {
                        useToastStore.getState().push({
                          tone: "error",
                          title: "Couldn't remove repository",
                          description: err instanceof Error ? err.message : String(err),
                        });
                      },
                    },
                  );
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
                  if (action)
                    removeWorkspaceMutation.mutate(
                      { projectId: action.project.id, workspaceId: action.workspaceId },
                      {
                        onError: (err) => {
                          useToastStore.getState().push({
                            tone: "error",
                            title: "Couldn't remove repository",
                            description: err instanceof Error ? err.message : String(err),
                          });
                        },
                      },
                    );
                }}
              >
                <Trash2 size={14} aria-hidden="true" />
                Remove from project
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

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

        <Dialog
          open={editTarget !== null}
          onOpenChange={(open) => {
            if (!open) setEditTarget(null);
          }}
        >
          <DialogContent showCloseButton={false}>
            <form onSubmit={submitSessionTitle}>
              <DialogHeader>
                <DialogTitle>Edit session title</DialogTitle>
                <DialogDescription>
                  Rename this session in the sidebar.
                </DialogDescription>
              </DialogHeader>
              <div className="px-3 py-2">
                <input
                  ref={editTitleInputRef}
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="h-9 w-full min-w-0 rounded-[10px] border border-(--color-border) bg-(--bg-page) px-3 py-1 text-sm text-(--color-text) outline-none focus-visible:border-(--focus-ring) focus-visible:ring-2 focus-visible:ring-(--focus-ring)/25"
                  aria-label="Session title"
                  maxLength={255}
                />
                {updateSessionTitle.isError && (
                  <p className="mt-2 text-xs text-(--color-error)">
                    Failed to update title.
                  </p>
                )}
              </div>
              <DialogFooter className="p-3">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setEditTarget(null)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={!editTitle.trim() || updateSessionTitle.isPending}
                >
                  {updateSessionTitle.isPending ? "Saving…" : "Save"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>

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
                &rdquo; will be hidden from the sidebar. Its sessions stay on
                disk — reopening this folder later restores the list.
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
                Remove from sidebar
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </motion.aside>
    </>
  );
}
