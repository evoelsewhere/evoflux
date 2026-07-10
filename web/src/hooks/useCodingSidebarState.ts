/**
 * useCodingSidebarState — custom hook that owns all coding-mode state,
 * queries, effects, and action handlers previously inlined in UnifiedSidebar.
 *
 * Keeps the main component focused on forge-mode logic, layout, and rendering.
 */
import { useState, useEffect, useMemo, useCallback } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import {
  browseWorkspaces,
  listWorktrees,
  removeWorktree,
  resolveTeamSession,
  setCodingWorkspaceVisibility,
  validateWorkspace,
} from "@/api/client";
import { apiBaseUrl } from "@/api/base-url";
import { getAppBackendStatus } from "@/lib/app-backend";
import { useTeamStore } from "@/stores/useTeamStore";
import { useToastStore } from "@/stores/useToastStore";
import {
  prependSession,
  prependWorkspaceSession,
} from "@/stores/cache-invalidation-bridge";
import { codingFocusId, saveLastCodingWorkspace } from "@/utils/workspace";
import { isTransientNetworkError } from "@/utils/errors";
import { queryKeys } from "@/queries";
import { useDeleteTeamSessionMutation } from "@/queries";
import type { CodingProject, SessionResponse, WorktreeInfo } from "@/api/types";
import {
  useCodingOverviewQuery,
  useAddWorkspaceMutation,
  useRemoveWorkspaceMutation,
} from "@/queries/useProjectsQuery";
import type {
  MobileWorkspaceAction,
  WorkspaceAction,
  SessionAction,
} from "@/components/UnifiedSidebarDialogs";

// ── Helpers ──────────────────────────────────────────────────────────────────

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

function toggleSetItem(prev: Set<string>, key: string): Set<string> {
  const next = new Set(prev);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return next;
}

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

// ── Types ────────────────────────────────────────────────────────────────────

export interface UseCodingSidebarStateOptions {
  /** Full flat session list (all modes) — used to derive codingSessions. */
  allSessions: SessionResponse[];
  /** Currently active session ID (may be undefined). */
  currentSessionId?: string;
  /** Current workspace path from route. */
  workspace?: string | null;
  /** Bump to programmatically open the workspace dialog. */
  openWorkspaceDialogKey?: number;
  /** Platform flags. */
  isTauri: boolean;
  isTauriMobile: boolean;
  /** Called when a mobile drawer should close. */
  onMobileClose?: () => void;
  /** Forge ↔ coding shared session edit state (setters only — state lives in parent). */
  setEditTarget: (target: SessionResponse | null) => void;
  setEditTitle: (title: string) => void;
  /** Forge ↔ coding shared delete state (setter only — state lives in parent). */
  pendingDeleteId: string | null;
  setPendingDeleteId: (id: string | null) => void;
  /** Shared mutation hook instance (state lives in parent for forge mode). */
  deleteSession: ReturnType<typeof useDeleteTeamSessionMutation>;
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export function useCodingSidebarState(opts: UseCodingSidebarStateOptions) {
  const {
    allSessions,
    currentSessionId,
    workspace,
    openWorkspaceDialogKey = 0,
    isTauri,
    isTauriMobile,
    onMobileClose,
    setEditTarget,
    setEditTitle,
    pendingDeleteId,
    setPendingDeleteId,
    deleteSession,
  } = opts;

  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // ── Queries & mutations ────────────────────────────────────────────────

  const removeWorkspaceMutation = useRemoveWorkspaceMutation();
  const addWorkspaceMutation = useAddWorkspaceMutation();
  const overviewQuery = useCodingOverviewQuery();
  const projects = overviewQuery.data?.projects ?? [];

  // ── Section / expansion state ──────────────────────────────────────────

  const [showProjectModal, setShowProjectModal] = useState(false);
  const [pendingProject, setPendingProject] = useState<string | null>(null);
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(
    () => new Set(),
  );
  const [expandedWorkspaces, setExpandedWorkspaces] = useState<Set<string>>(
    () => new Set(),
  );
  const [projectsSectionCollapsed, setProjectsSectionCollapsed] =
    useState(false);
  const [workspacesSectionCollapsed, setWorkspacesSectionCollapsed] =
    useState(false);

  // ── Derived data ───────────────────────────────────────────────────────

  const codingSessions = useMemo(
    () =>
      allSessions.filter(
        (session) => session.mode === "coding" && session.workspace,
      ),
    [allSessions],
  );

  const projectRunningMap = useMemo(() => {
    const map = new Map<string, boolean>();
    for (const s of codingSessions) {
      if (s.project_id && s.running === true) map.set(s.project_id, true);
    }
    return map;
  }, [codingSessions]);

  const storeProjectId = useTeamStore((s) => s.projectId);
  const currentProjectId =
    storeProjectId ??
    codingSessions.find((s) => s.id === currentSessionId)?.project_id ??
    null;

  const workspaceTree = overviewQuery.data?.repositories ?? [];
  const activeWorkspace = workspace ?? null;

  const worktreeSourceByDirectory = useMemo(() => {
    const map = new Map<string, string>();
    for (const repo of workspaceTree) {
      for (const item of repo.worktrees) {
        map.set(item.path, repo.path);
      }
    }
    return map;
  }, [workspaceTree]);

  const [removedWorktreePaths, setRemovedWorktreePaths] = useState<
    Set<string>
  >(() => new Set());

  const standaloneWorkspaces = useMemo(
    () =>
      workspaceTree
        .filter(
          (repo) =>
            repo.project_id === null && !removedWorktreePaths.has(repo.path),
        )
        .map((repo) => repo.path),
    [workspaceTree, removedWorktreePaths],
  );

  // ── Workspace dialog state ─────────────────────────────────────────────

  const [nativeFolderPickerEnabled, setNativeFolderPickerEnabled] =
    useState(isTauri);
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
  const [addRepoDialogProjectId, setAddRepoDialogProjectId] = useState<
    string | null
  >(null);

  // ── Action-menu / worktree state ───────────────────────────────────────

  const [mobileSessionActions, setMobileSessionActions] =
    useState<SessionResponse | null>(null);
  const [desktopSessionActions, setDesktopSessionActions] =
    useState<SessionAction | null>(null);
  const [desktopWorkspaceActions, setDesktopWorkspaceActions] =
    useState<WorkspaceAction | null>(null);
  const [mobileWorkspaceActions, setMobileWorkspaceActions] =
    useState<MobileWorkspaceAction | null>(null);
  const [removeWorkspaceTarget, setRemoveWorkspaceTarget] = useState<
    string | null
  >(null);
  const [worktreeTarget, setWorktreeTarget] = useState<string | null>(null);
  const [worktreeName, setWorktreeName] = useState("");
  const [worktreeBranch, setWorktreeBranch] = useState("");
  const [worktreeLoading, setWorktreeLoading] = useState(false);

  // ── Browser / folder picker ────────────────────────────────────────────

  const loadBrowser = useCallback(
    async (path?: string | null) => {
      setLoading(true);
      setError(null);
      try {
        const result = await browseWorkspaces(path);
        setBrowserPath(result.path);
        setParentPath(result.parent);
        setDirs(result.directories);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Unable to read directory",
        );
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const openWebWorkspaceDialog = useCallback(() => {
    setSelectedWorkspace(null);
    setTrustWorkspace(null);
    setDialogOpen(true);
    if (!browserPath) void loadBrowser(null);
  }, [browserPath, loadBrowser]);

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
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to open workspace",
      );
    } finally {
      setLoading(false);
    }
  }, [isTauri, isTauriMobile, openWebWorkspaceDialog]);

  // ── Workspace tree refresh ─────────────────────────────────────────────

  const refreshWorkspaceTree = useCallback(async () => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.codingOverview(),
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

  // ── Session creation / selection ───────────────────────────────────────

  const selectWorkspace = useCallback(
    async (path: string, opts: { create?: boolean } = {}) => {
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
        state.beginResolvedSession(null, {
          mode: "coding",
          workspace: path,
          model: state.sessionModel,
          thinkingLevel: state.sessionThinkingLevel,
        });
        const session = await resolveTeamSession({
          mode: "coding",
          workspace: path,
          model: state.sessionModel,
          thinkingLevel: state.sessionThinkingLevel,
          create,
        });
        state.beginResolvedSession(session.id, {
          mode: "coding",
          workspace: session.workspace ?? path,
          model: session.model ?? state.sessionModel,
          thinkingLevel:
            session.thinking_level ?? state.sessionThinkingLevel,
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
            ? {
                to: "/coding/$focusId/$sessionId",
                params: { focusId, sessionId: session.id },
              }
            : { to: "/coding" },
        );
      } catch (err) {
        setPendingWorkspace(null);
        setError(
          err instanceof Error ? err.message : "Unable to create session",
        );
      }
    },
    [currentSessionId, workspace, navigate, queryClient, refreshWorkspaceTree],
  );

  const openProjectSession = useCallback(
    async (project: CodingProject) => {
      if (!project.workspaces?.length) return;
      setPendingProject(project.id);
      try {
        const state = useTeamStore.getState();
        state.beginResolvedSession(null, { mode: "coding" });
        const session = await resolveTeamSession({
          mode: "coding",
          project_id: project.id,
          model: state.sessionModel,
          thinkingLevel: state.sessionThinkingLevel,
          create: true,
        });
        const resolvedWorkspace = session.workspace ?? null;
        state.beginResolvedSession(session.id, {
          mode: "coding",
          workspace: resolvedWorkspace,
          model: session.model ?? state.sessionModel,
          thinkingLevel:
            session.thinking_level ?? state.sessionThinkingLevel,
          skipInitialRestore: session.created,
        });
        useTeamStore.setState({ projectId: project.id });
        if (session.created) {
          prependSession(queryClient, session);
          void queryClient.invalidateQueries({
            queryKey: queryKeys.team.sessions.project(project.id),
          });
        }
        if (resolvedWorkspace) {
          await refreshWorkspaceTree();
        }
        const focusId = codingFocusId({
          project_id: project.id,
          workspace: resolvedWorkspace,
        });
        navigate(
          focusId
            ? {
                to: "/coding/$focusId/$sessionId",
                params: { focusId, sessionId: session.id },
              }
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
    },
    [navigate, queryClient, refreshWorkspaceTree],
  );

  // ── Session action handlers ────────────────────────────────────────────

  const handleSessionSelect = useCallback(
    (session: SessionResponse, workspacePath: string) => {
      if (!session.project_id && (session.workspace ?? workspacePath))
        saveLastCodingWorkspace(session.workspace ?? workspacePath);
      useTeamStore.setState({ projectId: session.project_id ?? null });
      const focusId = codingFocusId({
        project_id: session.project_id,
        workspace: session.workspace ?? workspacePath,
      });
      navigate(
        focusId
          ? {
              to: "/coding/$focusId/$sessionId",
              params: { focusId, sessionId: session.id },
            }
          : { to: "/coding" },
      );
      onMobileClose?.();
    },
    [navigate, onMobileClose],
  );

  const handleSessionEdit = useCallback(
    (session: SessionResponse) => {
      setEditTarget(session);
      setEditTitle(session.title || "");
    },
    [setEditTarget, setEditTitle],
  );

  const handleSessionDelete = useCallback(
    (session: SessionResponse) => {
      setPendingDeleteId(session.id);
    },
    [setPendingDeleteId],
  );

  const confirmSessionDelete = useCallback(() => {
    if (!pendingDeleteId) return;
    const target = codingSessions.find((s) => s.id === pendingDeleteId);
    if (!target) return;
    const fallbackSession =
      target.id === currentSessionId
        ? (target.project_id
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
          codingSessions.find((session) => session.id !== target.id)
        : null;
    deleteSession.mutate(target.id);
    if (target.id === currentSessionId) {
      if (fallbackSession) {
        if (fallbackSession.workspace && !fallbackSession.project_id)
          saveLastCodingWorkspace(fallbackSession.workspace);
        const focusId = codingFocusId({
          project_id: fallbackSession.project_id,
          workspace: fallbackSession.workspace,
        });
        navigate(
          focusId
            ? {
                to: "/coding/$focusId/$sessionId",
                params: {
                  focusId,
                  sessionId: fallbackSession.id,
                },
                replace: true,
              }
            : { to: "/coding", replace: true },
        );
      } else {
        navigate({ to: "/coding", replace: true });
      }
    }
    setPendingDeleteId(null);
  }, [
    pendingDeleteId,
    codingSessions,
    currentSessionId,
    deleteSession,
    navigate,
    setPendingDeleteId,
  ]);

  // ── Workspace removal ──────────────────────────────────────────────────

  const confirmRemoveWorkspace = useCallback(() => {
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
  }, [
    removeWorkspaceTarget,
    activeWorkspace,
    navigate,
    queryClient,
    refreshWorkspaceTree,
  ]);

  // ── Trust / folder dialog flow ─────────────────────────────────────────

  const openSelectedFolder = useCallback(async () => {
    if (!browserPath) return;
    try {
      const result = await validateWorkspace(browserPath);
      setTrustWorkspace(result.workspace);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Workspace is invalid");
    }
  }, [browserPath]);

  const confirmTrustedWorkspace = useCallback(() => {
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
          onError: (err: Error) => {
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
  }, [trustWorkspace, addRepoDialogProjectId, addWorkspaceMutation, selectWorkspace]);

  const openAddRepoDialog = useCallback(
    (projectId: string) => {
      setAddRepoDialogProjectId(projectId);
      void openWorkspaceDialog();
    },
    [openWorkspaceDialog],
  );

  // ── Worktree management ────────────────────────────────────────────────

  const loadWorktreesForTarget = useCallback(async (path: string) => {
    try {
      const items = await listWorktrees(path);
      return items;
    } catch {
      return [];
    }
  }, []);

  const openWorktreeDialog = useCallback(
    async (path: string) => {
      setWorktreeTarget(path);
      setWorktreeName("");
      setWorktreeBranch("");
      setError(null);
      await loadWorktreesForTarget(path);
    },
    [loadWorktreesForTarget],
  );

  const handleRemoveWorktree = useCallback(
    async (item: WorktreeInfo) => {
      if (!item.managed) return;
      const directory = item.directory;
      setError(null);
      try {
        const source =
          worktreeSourceByDirectory.get(directory) ?? worktreeTarget;
        if (!source) return;
        await removeWorktree(source, directory);
        setRemovedWorktreePaths((current) =>
          new Set(current).add(directory),
        );
        await refreshWorkspaceTree();
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Unable to remove worktree",
        );
      }
    },
    [worktreeSourceByDirectory, worktreeTarget, refreshWorkspaceTree],
  );

  const submitWorktree = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      if (!worktreeTarget) return;
      setWorktreeLoading(true);
      setError(null);
      try {
        const state = useTeamStore.getState();
        const session = await resolveTeamSession({
          mode: "coding",
          worktreeFrom: worktreeTarget,
          worktreeName: worktreeName || "session",
          worktreeBranch: worktreeBranch || null,
          model: state.sessionModel,
          thinkingLevel: state.sessionThinkingLevel,
        });
        const path = session.workspace;
        if (!path)
          throw new Error("Worktree session did not return a workspace");
        setWorktreeTarget(null);
        saveLastCodingWorkspace(path);
        const nextState = useTeamStore.getState();
        nextState.beginResolvedSession(session.id, {
          mode: "coding",
          workspace: path,
          model: session.model ?? nextState.sessionModel,
          thinkingLevel:
            session.thinking_level ?? nextState.sessionThinkingLevel,
          skipInitialRestore: session.created,
        });
        prependSession(queryClient, session);
        prependWorkspaceSession(queryClient, path, session);
        await refreshWorkspaceTree();
        const focusId = codingFocusId({
          project_id: session.project_id,
          workspace: path,
        });
        navigate(
          focusId
            ? {
                to: "/coding/$focusId/$sessionId",
                params: { focusId, sessionId: session.id },
              }
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
    },
    [
      worktreeTarget,
      worktreeName,
      worktreeBranch,
      navigate,
      queryClient,
      refreshWorkspaceTree,
      loadWorktreesForTarget,
      onMobileClose,
    ],
  );

  // ── Expansion toggles ──────────────────────────────────────────────────

  const toggleProjectExpanded = useCallback((projectId: string) => {
    setExpandedProjects((current) => toggleSetItem(current, projectId));
  }, []);

  useEffect(() => {
    if (!currentProjectId) return;
    setExpandedProjects((current) => {
      if (current.has(currentProjectId)) return current;
      const next = new Set(current);
      next.add(currentProjectId);
      return next;
    });
  }, [currentProjectId]);

  const toggleWorkspaceExpanded = useCallback((path: string) => {
    setExpandedWorkspaces((current) => toggleSetItem(current, path));
  }, []);

  useEffect(() => {
    if (!activeWorkspace) return;
    setExpandedWorkspaces((current) => {
      if (current.has(activeWorkspace)) return current;
      const next = new Set(current);
      next.add(activeWorkspace);
      return next;
    });
  }, [activeWorkspace]);

  // ── Return ─────────────────────────────────────────────────────────────

  return {
    // Queries
    overviewQuery,
    projects,
    removeWorkspaceMutation,

    // Section / expansion
    showProjectModal,
    setShowProjectModal,
    pendingProject,
    expandedProjects,
    expandedWorkspaces,
    projectsSectionCollapsed,
    setProjectsSectionCollapsed,
    workspacesSectionCollapsed,
    setWorkspacesSectionCollapsed,

    // Derived data
    codingSessions,
    projectRunningMap,
    currentProjectId,
    workspaceTree,
    activeWorkspace,
    standaloneWorkspaces,
    nativeFolderPickerEnabled,

    // Workspace dialog state
    dialogOpen,
    setDialogOpen,
    selectedWorkspace,
    browserPath,
    parentPath,
    dirs,
    error,
    loading,
    pendingWorkspace,
    trustWorkspace,
    setTrustWorkspace,

    // Action-menu / worktree state
    mobileSessionActions,
    setMobileSessionActions,
    desktopSessionActions,
    setDesktopSessionActions,
    desktopWorkspaceActions,
    setDesktopWorkspaceActions,
    mobileWorkspaceActions,
    setMobileWorkspaceActions,
    removeWorkspaceTarget,
    setRemoveWorkspaceTarget,
    worktreeTarget,
    setWorktreeTarget,
    worktreeName,
    setWorktreeName,
    worktreeBranch,
    setWorktreeBranch,
    worktreeLoading,

    // Browser / dialog handlers
    loadBrowser,
    closeWorkspaceDialog,
    openWorkspaceDialog,
    openSelectedFolder,
    confirmTrustedWorkspace,
    openAddRepoDialog,

    // Workspace tree
    refreshWorkspaceTree,

    // Session creation / selection
    selectWorkspace,
    openProjectSession,
    handleSessionSelect,
    handleSessionEdit,
    handleSessionDelete,
    confirmSessionDelete,

    // Workspace removal
    confirmRemoveWorkspace,

    // Worktree management
    openWorktreeDialog,
    handleRemoveWorktree,
    submitWorktree,

    // Expansion
    toggleProjectExpanded,
    toggleWorkspaceExpanded,
  };
}
