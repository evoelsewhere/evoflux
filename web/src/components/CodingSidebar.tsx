/**
 * CodingSidebar — selector-driven navigator for coding mode.
 *
 * PROJECTS is the only section: Coding is project-only.
 *   Sessions belong to the PROJECT, not to individual repos. A project
 *   session spans all repos in the project — the agent gets access to every
 *   workspace path via project_id. A select chooses one project; only that
 *   project's sessions render below it. Repository management stays in a
 *   compact, optional details row and never starts per-repository sessions.
 *
 *   Opening (or cloning) a folder creates a single-repo project named after
 *   it and starts a session there; a folder that already belongs to a
 *   project just opens that project. Multi-repo projects are set up in
 *   ProjectSetupModal, and repos can be added to any project later.
 *
 * The desktop chrome (resizable width, collapse-to-zero, search trigger,
 * footer, section headers, session rows, session action surfaces) comes
 * from the shared `@/components/shell/` primitives — same as the work
 * sidebar. Coding keeps its stacked-cards layout (mode switch,
 * search, navigator, footer as separate floating cards) and all of its
 * workspace/worktree dialogs in-file.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useIsMobile } from "@/hooks/use-mobile";
import { useModalFocus } from "@/hooks/useModalFocus";
import { usePlatform } from "@/hooks/use-platform";
import { useMotionPreset, useListEnterIndex } from "@/lib/motion";
import { STORAGE_KEYS } from "@/lib/storage-keys";
import {
  AlertTriangle,
  Blocks,
  CalendarClock,
  ChevronRight,
  Download,
  Folder,
  FolderPlus,
  GitBranch,
  CircleHelp,
  Layers3,
  Loader2,
  MoreHorizontal,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { ModeSwitchTabs } from "@/components/ModeSwitchTabs";
import { queryKeys, useSandboxSettingsQuery } from "@/queries";
import {
  useDeleteTeamSessionMutation,
  useDuplicateTeamSessionMutation,
  useProjectSessionsQuery,
  useTeamSessionsQuery,
  useUpdateTeamSessionTitleMutation,
} from "@/queries/useSessionsQuery";
import { apiBaseUrl } from "@/api/base-url";
import {
  browseWorkspaces,
  getCodingWorkspaceTree,
  gitClone,
  listWorktrees,
  removeWorktree,
  resolveTeamSession,
  validateWorkspace,
} from "@/api/client";
import { getAppBackendStatus } from "@/lib/app-backend";
import { useTeamStore } from "@/stores/useTeamStore";
import { useToastStore } from "@/stores/useToastStore";
import { useUIStore } from "@/stores/useUIStore";
import { usePinnedSessions } from "@/stores/usePinnedSessions";
import { prependSession } from "@/stores/cache-invalidation-bridge";
import {
  clearLastCodingFocus,
  saveLastCodingFocus,
  workspaceLabel,
} from "@/utils/workspace";
import { isTransientNetworkError } from "@/utils/errors";
import {
  SidebarShell,
  SidebarCard,
  SidebarNavGroup,
  SidebarSearchTrigger,
  SidebarFooter,
  SidebarModeSlot,
} from "@/components/shell/SidebarShell";
import { SidebarItem } from "@/components/ui/sidebar-item";
import { SessionRow } from "@/components/shell/SessionRow";
import {
  SessionContextMenu,
  SessionActionsDialog,
  type SessionMenuAnchor,
} from "@/components/shell/SessionContextMenu";
import { EditSessionTitleDialog } from "@/components/shell/EditSessionTitleDialog";
import { MobileDrawerBackdrop } from "@/components/shell/MobileDrawerBackdrop";
import { Button } from "@/components/ui/button";
import { Combobox } from "@/components/ui/combobox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
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
  CodingWorkspaceTreeResponse,
  SessionResponse,
  WorktreeInfo,
} from "@/api/types";
import {
  useAddWorkspaceMutation,
  useCodingOverviewQuery,
  useCreateProjectMutation,
  useDeleteProjectMutation,
  useRemoveWorkspaceMutation,
} from "@/queries/useProjectsQuery";
import { ProjectSetupModal } from "@/components/ProjectSetupModal";
import { cn } from "@/lib/utils";
import { resolveCodingSidebarSelection } from "@/utils/coding-sidebar-selection";

/**
 * Remember which coding project was open, the way the last workspace already
 * is. Storage throws in restricted webviews and in private windows, so both
 * helpers must tolerate failure and simply forget.
 */
function readLastCodingProject(): string | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEYS.coding.lastProject);
    return stored && stored.trim() ? stored : null;
  } catch {
    return null;
  }
}

function writeLastCodingProject(projectId: string | null): void {
  try {
    if (projectId) localStorage.setItem(STORAGE_KEYS.coding.lastProject, projectId);
    else localStorage.removeItem(STORAGE_KEYS.coding.lastProject);
  } catch {
    // Remembering the last project is a convenience, never a requirement.
  }
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

/**
 * Projects that already own *path*: those listing it as a repository, or else
 * the project of the repository it is a worktree of. Opening the folder opens
 * the first of them instead of creating a project.
 */
function projectsOwningFolder(
  overview: CodingWorkspaceTreeResponse | undefined,
  path: string,
): CodingProject[] {
  if (!overview) return [];
  const direct = overview.projects.filter((project) =>
    (project.workspaces ?? []).some((repository) => repository.path === path),
  );
  if (direct.length > 0) return direct;
  const worktreeOwnerId = overview.repositories.find((repository) =>
    repository.worktrees.some((worktree) => worktree.path === path),
  )?.project_id;
  const owner = worktreeOwnerId
    ? overview.projects.find((project) => project.id === worktreeOwnerId)
    : undefined;
  return owner ? [owner] : [];
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

interface CodingSidebarProps {
  currentSessionId?: string;
  /** Bump this counter to programmatically open the folder picker that
   *  creates a project (e.g. from the empty Coding page's CTA). */
  openWorkspaceDialogKey?: number;
  /** Open the command palette (search input + footer help). */
  onCommandPalette?: () => void;
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

const SESSION_SKELETON_WIDTHS = ["72%", "58%", "66%"];

function SessionRowsSkeleton() {
  return (
    <div aria-hidden="true">
      {SESSION_SKELETON_WIDTHS.map((width, index) => (
        <div key={index} className="flex min-h-8 items-center gap-1.5 px-2.5 py-2">
          <Skeleton className="h-3" style={{ width }} />
          <Skeleton className="ml-auto h-2.5 w-6 shrink-0" />
        </div>
      ))}
    </div>
  );
}

/** Stand-in for a project or workspace card while the Coding overview loads. */
function ScopeCardSkeleton({ label }: { label: string }) {
  return (
    <div
      role="status"
      aria-label={label}
      className="overflow-hidden rounded-lg border border-(--color-border) bg-(--bg-page)/45"
    >
      <div className="flex min-h-9 items-center gap-2 px-2">
        <Skeleton className="size-3.5 shrink-0 rounded-sm" />
        <Skeleton className="h-3 w-28" />
        <Skeleton className="h-2.5 w-10" />
        <Skeleton className="ml-auto size-5 shrink-0" />
      </div>
      <div className="border-t border-(--color-border)/60 px-1 pb-1 pt-1.5">
        <div className="flex h-6 items-center px-2">
          <Skeleton className="h-2 w-10" />
        </div>
        <SessionRowsSkeleton />
      </div>
    </div>
  );
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

  // Lazy-load the next page as the list's end nears, instead of a
  // "Load more" button. The root is the card's own scroller, so the margin
  // prefetches inside it rather than against the window.
  const loadMoreRef = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = sessions;
  useEffect(() => {
    const sentinel = loadMoreRef.current;
    if (!sentinel || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      {
        root: sentinel.closest("[data-session-scroll]"),
        rootMargin: "0px 0px 160px 0px",
        threshold: 0,
      },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return (
    <div className="space-y-0.5 pb-1">
      <div className="sticky top-0 z-1 flex h-7 items-center gap-1.5 bg-(--bg-sidebar) px-2 text-[10px] font-medium uppercase tracking-wide text-(--color-text-subtle)">
        <span>Chats</span>
        {!sessions.isLoading && projectSessions.length > 0 && (
          <span className="ml-auto font-normal normal-case tracking-normal tabular-nums">
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
        <div role="status" aria-label="Loading sessions">
          <SessionRowsSkeleton />
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
        <div ref={loadMoreRef} className="h-px" aria-hidden="true" />
      )}
      {sessions.isFetchingNextPage && (
        <div role="status" aria-label="Loading more sessions">
          <SessionRowsSkeleton />
        </div>
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

export function CodingSidebar({
  currentSessionId,
  openWorkspaceDialogKey = 0,
  onCommandPalette,
  mobileOpen = false,
  onMobileClose,
  drawerMode = false,
}: CodingSidebarProps) {
  const isMobile = useIsMobile();
  const consumedWorkspaceDialogKey = useRef(openWorkspaceDialogKey);
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
  const duplicateSession = useDuplicateTeamSessionMutation();
  const updateSessionTitle = useUpdateTeamSessionTitleMutation();
  // One merged query for projects and their repos' worktrees — see
  // useCodingOverviewQuery's doc comment.
  const overviewQuery = useCodingOverviewQuery();
  const projects = overviewQuery.data?.projects ?? [];
  const createProjectMutation = useCreateProjectMutation();
  const addWorkspaceMutation = useAddWorkspaceMutation();
  const deleteProjectMutation = useDeleteProjectMutation();
  const removeWorkspaceMutation = useRemoveWorkspaceMutation();
  const [showProjectModal, setShowProjectModal] = useState(false);
  const [deleteProjectTarget, setDeleteProjectTarget] =
    useState<CodingProject | null>(null);
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(
    () => new Set(),
  );
  // Seed from the last project this browser had open. Without it a reload
  // resolves to options[0], silently dropping the user onto another project.
  // The project switcher popup lines up with the whole header row, not just
  // the name inside it.
  const projectRowRef = useRef<HTMLDivElement>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    () => readLastCodingProject(),
  );
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
  // When set, the folder picker is in "add repo to project" mode: confirming
  // adds the folder to this project instead of creating a new project.
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

  const [dialogOpen, setDialogOpen] = useState(false);
  const [workspacePickerMode, setWorkspacePickerMode] =
    useState<"open" | "clone">("open");
  const [selectedWorkspace, setSelectedWorkspace] = useState<string | null>(
    null,
  );
  const [browserPath, setBrowserPath] = useState<string | null>(null);
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [dirs, setDirs] = useState<Array<{ name: string; path: string }>>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [trustWorkspace, setTrustWorkspace] = useState<string | null>(null);
  // Set while a trusted folder is being turned into (or matched to) a
  // project; the ref blocks re-entry before React re-renders the button.
  const [openingFolder, setOpeningFolder] = useState(false);
  const openingFolderRef = useRef(false);
  const [cloneUrl, setCloneUrl] = useState("");
  const [cloneDirectory, setCloneDirectory] = useState("");
  const [cloneBranch, setCloneBranch] = useState("");
  const [cloneParent, setCloneParent] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<SessionResponse | null>(null);
  const [editTitle, setEditTitle] = useState("");
  // Keep the full session — project lists are separate queries and the
  // deleted row may not be on a loaded page of the global coding list.
  const [pendingDeleteSession, setPendingDeleteSession] =
    useState<SessionResponse | null>(null);
  const [mobileSessionActions, setMobileSessionActions] =
    useState<SessionResponse | null>(null);
  const [desktopSessionActions, setDesktopSessionActions] =
    useState<SessionMenuAnchor | null>(null);
  const [worktreeTarget, setWorktreeTarget] = useState<string | null>(null);
  // Where Create worktree puts the checkout (Settings → Sandbox); the
  // dialog used to say "outside the source repo" whatever it was set to.
  const worktreeLocation = useSandboxSettingsQuery().data?.worktree_location;
  // The project the worktree was asked for from — a repository can belong to
  // several, and the new session must land in the one the user was in.
  const [worktreeProjectId, setWorktreeProjectId] = useState<string | null>(null);
  const [worktreeName, setWorktreeName] = useState("");
  const [worktreeBranch, setWorktreeBranch] = useState("");
  const [worktreeLoading, setWorktreeLoading] = useState(false);
  const [worktreeOptions, setWorktreeOptions] = useState<WorktreeInfo[]>([]);
  const [worktreeRemoving, setWorktreeRemoving] = useState<string | null>(null);
  const [worktreesBySource, setWorktreesBySource] = useState<
    Record<string, WorktreeInfo[]>
  >({});
  // Tracks the last folder chosen via the native picker so the next dialog
  // open can start at its parent directory rather than inside it.
  const [lastPickPath, setLastPickPath] = useState<string | null>(null);

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
    // Navigate to the parent of the last-browsed directory so siblings are
    // visible. Fall back to root when there is no prior browse state.
    void loadBrowser(parentPath ?? null);
  }, [loadBrowser, parentPath]);

  // Closes the folder-picker dialog and clears every mode flag it can be in
  // ("create a project from a folder" vs. "add a repo to project X") so a
  // cancelled dialog never leaves stale state for the next open.
  const closeWorkspaceDialog = useCallback(() => {
    setDialogOpen(false);
    setTrustWorkspace(null);
    setAddRepoDialogProjectId(null);
    setWorkspacePickerMode("open");
    setCloneParent(null);
  }, []);

  const openWorkspaceDialog = useCallback(async () => {
    setError(null);
    setSelectedWorkspace(null);
    setTrustWorkspace(null);
    setWorkspacePickerMode("open");

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
  }, [isTauri, isTauriMobile, openWebWorkspaceDialog]);

  const pickNativeFolder = useCallback(async (purpose: "workspace" | "clone") => {
    setLoading(true);
    setError(null);
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const wantMultiple =
        purpose === "workspace" && addRepoDialogProjectId !== null;
      // Open at the parent of the last selection so siblings are visible,
      // falling back to the OS default when there is no prior pick.
      const defaultPath =
        lastPickPath?.replace(/[\\/][^\\/]*$/, "") || undefined;
      const selected = await open({
        directory: true,
        multiple: wantMultiple,
        defaultPath,
        title: purpose === "clone"
          ? "Choose clone destination"
          : wantMultiple
            ? "Add repositories"
            : "Open folder as project",
      });
      if (purpose === "clone") {
        if (typeof selected !== "string") return;
        setCloneParent(selected);
        return;
      }
      // Multi-select: add every selected folder to the project directly.
      if (Array.isArray(selected) && selected.length > 0) {
        const projectId = addRepoDialogProjectId!;
        for (const folder of selected) {
          addWorkspaceMutation.mutate(
            { projectId, body: { workspace_path: folder } },
            {
              onSuccess: () => {
                setExpandedProjects((current) => {
                  if (current.has(projectId)) return current;
                  const next = new Set(current);
                  next.add(projectId);
                  return next;
                });
              },
              onError: (err) => {
                useToastStore.getState().push({
                  tone: "error",
                  title: "Couldn't add repository",
                  description: `${folder}: ${err instanceof Error ? err.message : String(err)}`,
                });
              },
            },
          );
        }
        setLastPickPath(selected[selected.length - 1]);
        return;
      }
      // Single-select: a folder to create a project from.
      if (typeof selected !== "string") return;
      setSelectedWorkspace(selected);
      setLastPickPath(selected);
      const result = await validateWorkspace(selected);
      setTrustWorkspace(result.workspace);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to choose folder");
    } finally {
      setLoading(false);
    }
  }, [addRepoDialogProjectId, addWorkspaceMutation, lastPickPath, setExpandedProjects]);

  const refreshWorkspaceTree = useCallback(async () => {
    // Force the projects snapshot to be fetched even if
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
    if (
      openWorkspaceDialogKey <= 0 ||
      openWorkspaceDialogKey === consumedWorkspaceDialogKey.current
    ) return;
    consumedWorkspaceDialogKey.current = openWorkspaceDialogKey;
    void openWorkspaceDialog();
  }, [openWorkspaceDialogKey, openWorkspaceDialog]);

  // Project "+": a draft bound to the project. Its primary repo is the
  // project's to derive, so the draft names only the project and the first
  // message resolves the rest server-side.
  const openProjectSession = (project: CodingProject) => {
    if (!project.workspaces?.length) return;
    const state = useTeamStore.getState();
    if (state.isEmptyIdleSession() && state.projectId === project.id) return;
    // Only carry the current model/thinking-level over when there's an
    // existing session to carry them FROM — otherwise a stale value left
    // over from a different mode's session gets sent here and can be
    // rejected as "Choose a model from the registry." (see work.tsx).
    state.beginResolvedSession(null, {
      mode: "coding",
      // The project's primary repo, same first entry the backend derives.
      workspace: project.workspaces[0]?.path ?? null,
      projectId: project.id,
      model: state.sessionId ? state.sessionModel : null,
      thinkingLevel: state.sessionId ? state.sessionThinkingLevel : null,
    });
    setSelectedProjectId(project.id);
    writeLastCodingProject(project.id);
    saveLastCodingFocus({ project_id: project.id });
    navigate({ to: "/coding/$focusId", params: { focusId: project.id } });
    onMobileClose?.();
  };

  // "Open folder" / clone: Coding is project-only, so a folder becomes a
  // single-repo project named after it, and a new chat opens there. A folder
  // some project already has just opens that project instead of making a
  // second one around the same repository.
  //
  // Ownership is read from a fresh overview, never the rendered one: a list
  // that is still loading, failed, or predates a project created a moment ago
  // would otherwise make a second project around the same repository — and a
  // repo with two owners can no longer be opened by path at all. A managed
  // worktree folder belongs to its source repository's project.
  //
  // Returns whether the folder is now open, so the caller can keep the
  // dialog up (and the folder picked) when it is not.
  const openFolderAsProject = async (path: string): Promise<boolean> => {
    try {
      const overview = await queryClient.fetchQuery({
        queryKey: queryKeys.codingOverview(),
        queryFn: getCodingWorkspaceTree,
        staleTime: 0,
      });
      const owner = projectsOwningFolder(overview, path)[0];
      if (owner) {
        openProjectSession(owner);
        return true;
      }
      const created = await createProjectMutation.mutateAsync({
        name: workspaceLabel(path),
        workspace_paths: [path],
      });
      openProjectSession(created);
      return true;
    } catch (err) {
      useToastStore.getState().push({
        tone: "error",
        title: "Couldn't create a project for this folder",
        description: err instanceof Error ? err.message : String(err),
      });
      return false;
    }
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

  const openWorktreeDialog = async (path: string, projectId: string) => {
    setWorktreeTarget(path);
    setWorktreeProjectId(projectId);
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
      // existing session to carry them FROM — see openProjectSession above.
      const carryModel = state.sessionId ? state.sessionModel : null;
      const carryThinkingLevel = state.sessionId ? state.sessionThinkingLevel : null;
      const session = await resolveTeamSession({
        mode: "coding",
        project_id: worktreeProjectId,
        worktreeFrom: worktreeTarget,
        worktreeName: worktreeName || "session",
        worktreeBranch: worktreeBranch || null,
        model: carryModel,
        thinkingLevel: carryThinkingLevel,
      });
      const path = session.workspace;
      if (!path) throw new Error("Worktree session did not return a workspace");
      // The server files a worktree session under its source repo's project.
      const projectId = session.project_id;
      if (!projectId) throw new Error("Worktree session did not return a project");
      setWorktreeTarget(null);
      const nextState = useTeamStore.getState();
      nextState.beginResolvedSession(session.id, {
        mode: "coding",
        workspace: path,
        projectId,
        model: session.model ?? carryModel,
        thinkingLevel: session.thinking_level ?? carryThinkingLevel,
        skipInitialRestore: session.created,
      });
      saveLastCodingFocus({ project_id: projectId });
      prependSession(queryClient, session);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.team.sessions.project(projectId),
      });
      await refreshWorkspaceTree();
      navigate({
        to: "/coding/$focusId/$sessionId",
        params: { focusId: projectId, sessionId: session.id },
      });
      onMobileClose?.();
    } catch (err) {
      if (isTransientNetworkError(err) && worktreeTarget) {
        const source = worktreeTarget;
        const expectedName = worktreeNameSlug(worktreeName || "session");
        const items = await loadWorktreesForTarget(source);
        const created = items.find((item) => item.name === expectedName);
        if (created) {
          setWorktreeTarget(null);
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

  const projectIdsKey = projects.map((project) => project.id).join("\0");

  useEffect(() => {
    const options = projectIdsKey ? projectIdsKey.split("\0") : [];
    setSelectedProjectId((selected) =>
      resolveCodingSidebarSelection(
        options,
        currentProjectId,
        selected ?? readLastCodingProject(),
      ),
    );
  }, [currentProjectId, projectIdsKey]);

  // A project or repository hit in the command palette asks the sidebar to
  // scope itself the way clicking that row would.
  const codingScopeRequest = useUIStore((s) => s.codingScopeRequest);
  useEffect(() => {
    if (!codingScopeRequest) return;
    if (codingScopeRequest.projectId) {
      setSelectedProjectId(codingScopeRequest.projectId);
      writeLastCodingProject(codingScopeRequest.projectId);
    }
    useUIStore.getState().clearCodingScopeRequest(codingScopeRequest.id);
  }, [codingScopeRequest]);

  const selectedProject =
    projects.find((project) => project.id === selectedProjectId) ?? null;
  // The Coding home page offers "New chat in <project>": it must name the
  // project shown here, which the remembered last project could lag behind.
  const selectedProjectIdForHome = selectedProject?.id ?? null;
  useEffect(() => {
    useUIStore.getState().setCodingSelectedProjectId(selectedProjectIdForHome);
  }, [selectedProjectIdForHome]);
  const addRepoProject = addRepoDialogProjectId
    ? projects.find((p) => p.id === addRepoDialogProjectId) ?? null
    : null;
  // Trusting a folder some project already owns opens that project rather
  // than creating one; the dialog says so before the user confirms.
  const trustOwners = trustWorkspace
    ? projectsOwningFolder(overviewQuery.data, trustWorkspace)
    : [];

  const openSelectedFolder = async () => {
    if (!browserPath) return;
    try {
      const result = await validateWorkspace(browserPath);
      setTrustWorkspace(result.workspace);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Workspace is invalid");
    }
  };

  const cloneRepositoryFromDialog = async () => {
    const parent = nativeFolderPickerEnabled && !isTauriMobile
      ? cloneParent
      : browserPath;
    if (!parent || !cloneUrl.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await gitClone({
        parent,
        url: cloneUrl.trim(),
        directory: cloneDirectory.trim() || undefined,
        branch: cloneBranch.trim() || undefined,
      });
      setSelectedWorkspace(result.workspace);
      const validation = await validateWorkspace(result.workspace);
      setTrustWorkspace(validation.workspace);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to clone repository");
    } finally {
      setLoading(false);
    }
  };

  const confirmTrustedWorkspace = async () => {
    if (!trustWorkspace || openingFolderRef.current) return;
    const workspaceToOpen = trustWorkspace;
    if (!addRepoDialogProjectId) {
      // Stay on the trust dialog, busy, until the project exists: closing it
      // first gave no feedback, and a second pick of the same folder in the
      // meantime made a duplicate project.
      openingFolderRef.current = true;
      setOpeningFolder(true);
      try {
        if (!(await openFolderAsProject(workspaceToOpen))) return;
      } finally {
        openingFolderRef.current = false;
        setOpeningFolder(false);
      }
      setTrustWorkspace(null);
      setDialogOpen(false);
      return;
    }
    setTrustWorkspace(null);
    setDialogOpen(false);
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
  };

  // Opens the same folder-picker dialog used to create a project, but tags
  // it so the confirmation adds the chosen folder to this project instead.
  const openAddRepoDialog = (projectId: string) => {
    setAddRepoDialogProjectId(projectId);
    void openWorkspaceDialog();
  };

  const handleSessionSelect = (session: SessionResponse) => {
    // Prime projectId immediately so CodingWorkspacePanel shows multi-repo context
    // without waiting for the async history load.
    useTeamStore.setState({ projectId: session.project_id ?? null });
    navigate(
      session.project_id
        ? {
            to: "/coding/$focusId/$sessionId",
            params: { focusId: session.project_id, sessionId: session.id },
          }
        : { to: "/coding" },
    );
    onMobileClose?.();
  };

  // Session-row side-chat icon: open the session (no-op when already active)
  // and ask TeamChatView to open its side chat panel.
  const handleSessionSideChat = (session: SessionResponse) => {
    useUIStore.getState().requestSideChat(session.id);
    handleSessionSelect(session);
  };

  const handleSessionDelete = (session: SessionResponse) => {
    setPendingDeleteSession(session);
  };

  const handleSessionEdit = (session: SessionResponse) => {
    setEditTarget(session);
    setEditTitle(session.title || "");
  };

  const handleSessionDuplicate = (session: SessionResponse) => {
    duplicateSession.mutate(session.id, {
      onSuccess: (copy) => {
        handleSessionSelect(copy);
      },
      onError: (err) =>
        useToastStore.getState().push({
          tone: "error",
          title: "Could not duplicate session",
          description: err instanceof Error ? err.message : "Please try again.",
        }),
    });
  };

  const confirmSessionDelete = () => {
    if (!pendingDeleteSession) return;
    const target = pendingDeleteSession;
    const fallbackSession =
      target.id === currentSessionId
        ? (codingSessions.find(
            (session) =>
              session.id !== target.id &&
              session.project_id === target.project_id,
          ) ??
          codingSessions.find(
            (session) => session.id !== target.id && session.project_id,
          ))
        : null;
    deleteSession.mutate(target.id);
    if (target.id === currentSessionId) {
      if (fallbackSession?.project_id) {
        navigate({
          to: "/coding/$focusId/$sessionId",
          params: {
            focusId: fallbackSession.project_id,
            sessionId: fallbackSession.id,
          },
          replace: true,
        });
      } else {
        navigate({ to: "/coding", replace: true });
      }
    }
    setPendingDeleteSession(null);
  };

  // The PROJECTS navigator — one copy shared by the desktop floating card and
  // the mobile drawer.
  const navigatorContent = (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {/* No "Projects" section header: the project picker below is the
          header, and opening or setting up projects lives in its footer. */}
      <div
        className={cn(
          "flex min-h-0 flex-1 flex-col px-1.5 pb-2",
          isDrawer ? "pt-2" : "pt-1",
        )}
      >
        {overviewQuery.isLoading && (
          <ScopeCardSkeleton label="Loading projects" />
        )}

        {overviewQuery.isError && (
          <div className="mx-2 my-1 rounded-md border border-(--color-error)/30 bg-(--color-error-subtle) px-2 py-2 text-xs text-(--color-error)">
            <p>Couldn&apos;t load projects.</p>
            <button
              type="button"
              onClick={() => void overviewQuery.refetch()}
              className="mt-1 font-medium underline underline-offset-2"
            >
              Retry
            </button>
          </div>
        )}

        {!overviewQuery.isLoading && !overviewQuery.isError && projects.length === 0 && (
          <p className="px-2 py-1.5 text-xs text-(--color-text-subtle)">
            No projects yet.{" "}
            <button
              type="button"
              onClick={() => void openWorkspaceDialog()}
              className="text-(--color-accent) hover:underline"
            >
              Open a folder
            </button>{" "}
            to start one, or{" "}
            <button
              type="button"
              onClick={() => setShowProjectModal(true)}
              className="text-(--color-accent) hover:underline"
            >
              set up a multi-repo project
            </button>
            .
          </p>
        )}

        {selectedProject && (
          <div className="flex min-h-0 flex-1 flex-col">
            {(() => {
              const project = selectedProject;
              const repositories = project.workspaces ?? [];
              const repositoriesExpanded = expandedProjects.has(project.id);
              const canCreateSession = repositories.length > 0;
              const projectHasRunning = codingSessions.some(
                (session) => session.project_id === project.id && session.running === true,
              );
              return (
                <>
                  {/* Project switcher — the project is the scope, so it reads
                      as the header of everything below rather than a card. */}
                  {/* Insets are balanced by eye-line, not by box: the picker's
                      own 10px trigger padding + pl-1 puts the project icon
                      14px in, and pr-[7px] + the ⋯ button's 7px centring puts
                      the last icon 14px from the right edge. Everything below
                      (repositories chevron, Chats label, chat titles) starts
                      on that same 14px line. */}
                  <div
                    ref={projectRowRef}
                    className="flex h-9 shrink-0 items-center gap-1 rounded-lg bg-(--bg-key)/50 pl-1 pr-[7px]"
                  >
                    <Combobox
                      items={projects.map((option) => ({
                        value: option.id,
                        label: option.name,
                        meta: `${option.workspaces?.length ?? 0} ${option.workspaces?.length === 1 ? "repo" : "repos"}`,
                        keywords: option.workspaces
                          ?.map((workspace) => `${workspace.name ?? ""} ${workspace.display_name ?? ""} ${workspace.path}`)
                          .join(" "),
                      }))}
                      value={project.id}
                      onValueChange={(value) => {
                        if (!value) return;
                        setSelectedProjectId(value);
                        // Only an explicit pick is remembered. Persisting every
                        // resolved value also persisted the first-project
                        // fallback, which then overwrote the real choice.
                        writeLastCodingProject(value);
                      }}
                      ariaLabel="Select project"
                      searchPlaceholder="Search projects or repositories…"
                      emptyText="No matching projects."
                      size="sm"
                      clearable={false}
                      className="min-w-0 flex-1 border-0 bg-transparent font-medium shadow-none hover:bg-(--bg-key) focus-within:ring-0"
                      anchor={projectRowRef}
                      footer={(close) => (
                        <>
                          <button
                            type="button"
                            onClick={() => { close(); void openWorkspaceDialog(); }}
                            className="flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-xs text-(--color-text-2) outline-none hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:bg-(--bg-key)"
                          >
                            <FolderPlus size={13} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
                            Open folder as project…
                          </button>
                          <button
                            type="button"
                            onClick={() => { close(); setShowProjectModal(true); }}
                            className="flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-xs text-(--color-text-2) outline-none hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:bg-(--bg-key)"
                          >
                            <Layers3 size={13} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
                            Set up a multi-repo project…
                          </button>
                        </>
                      )}
                      renderLeadingIcon={(option) => (
                        <Layers3
                          size={13}
                          className={
                            option.value === currentProjectId
                              ? "text-(--color-accent)"
                              : "text-(--color-text-muted)"
                          }
                          aria-hidden="true"
                        />
                      )}
                    />
                    {projectHasRunning && (
                      <span className="size-1.5 shrink-0 rounded-full bg-(--color-accent)" aria-label="Project has running session" />
                    )}
                    <button
                      type="button"
                      onClick={() => openProjectSession(project)}
                      disabled={!canCreateSession}
                      className="flex size-7 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) outline-none hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:ring-1 focus-visible:ring-(--color-border-strong) disabled:cursor-not-allowed disabled:opacity-40"
                      aria-label={canCreateSession ? `New session in ${project.name}` : `${project.name} has no repositories yet`}
                      title={canCreateSession ? `New chat in ${project.name}` : "Add a repository first"}
                    >
                      <Plus size={14} aria-hidden="true" />
                    </button>
                    {/* Rare and destructive project actions live behind one
                        menu instead of a row of 12px icons beside the name. */}
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        className="flex size-7 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) outline-none hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:ring-1 focus-visible:ring-(--color-border-strong) data-popup-open:bg-(--bg-key)"
                        aria-label={`Project actions for ${project.name}`}
                        title="Project actions"
                      >
                        <MoreHorizontal size={14} aria-hidden="true" />
                      </DropdownMenuTrigger>
                      {/* Only actions on *this* project; creating projects
                          lives in the switcher's footer. */}
                      <DropdownMenuContent align="end" className="w-56">
                        <DropdownMenuItem onClick={() => openAddRepoDialog(project.id)}>
                          <GitBranch aria-hidden="true" />
                          Add repository…
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          variant="destructive"
                          disabled={deleteProjectMutation.isPending}
                          onClick={() => setDeleteProjectTarget(project)}
                        >
                          <Trash2 aria-hidden="true" />
                          Delete project
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>

                  <button
                    type="button"
                    onClick={() => toggleProjectExpanded(project.id)}
                    className="mt-1 flex h-7 shrink-0 items-center gap-1.5 rounded-md px-3.5 text-xs text-(--color-text-muted) outline-none hover:bg-(--bg-key)/60 hover:text-(--color-text) focus-visible:ring-1 focus-visible:ring-(--color-border-strong)"
                    aria-expanded={repositoriesExpanded}
                    aria-label={`${repositoriesExpanded ? "Hide" : "Show"} repositories in ${project.name}`}
                  >
                    <ChevronRight
                      size={12}
                      aria-hidden="true"
                      className={cn("shrink-0 transition-transform duration-(--motion-fast)", repositoriesExpanded && "rotate-90")}
                    />
                    <Folder size={12} className="shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
                    <span className="tabular-nums">
                      {repositories.length} {repositories.length === 1 ? "repository" : "repositories"}
                    </span>
                  </button>

                  {repositoriesExpanded && (
                    <div className="max-h-32 shrink-0 overflow-y-auto pb-1 pl-6">
                      {repositories.length === 0 && (
                        <p className="px-2 py-1 text-[11px] text-(--color-text-subtle)">No repositories yet.</p>
                      )}
                      {repositories.map((repository) => (
                        <button
                          key={repository.workspace_id}
                          type="button"
                          onClick={(event) => {
                            const pos = clampMenuPosition(event.clientX, event.clientY);
                            setProjectRepoActions({
                              project,
                              workspaceId: repository.workspace_id,
                              path: repository.path,
                              x: pos.x,
                              y: pos.y,
                            });
                          }}
                          onContextMenu={(event) => {
                            event.preventDefault();
                            const pos = clampMenuPosition(event.clientX, event.clientY);
                            setProjectRepoActions({
                              project,
                              workspaceId: repository.workspace_id,
                              path: repository.path,
                              x: pos.x,
                              y: pos.y,
                            });
                          }}
                          className="group/repo flex h-7 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left text-xs text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)"
                          aria-label={`Actions for repository ${repository.display_name || repository.name || workspaceLabel(repository.path)}`}
                          title={repository.path}
                        >
                          <GitBranch size={12} className="shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
                          <span className="min-w-0 flex-1 truncate">
                            {repository.display_name || repository.name || workspaceLabel(repository.path)}
                          </span>
                          <MoreHorizontal size={12} className="shrink-0 text-(--color-text-subtle) opacity-0 transition-opacity group-hover/repo:opacity-100" aria-hidden="true" />
                        </button>
                      ))}
                    </div>
                  )}

                  {/* Chats take the rest of the height and scroll on their own;
                      the list's header is sticky so no row slides under it. */}
                  <div data-session-scroll className="mt-1 min-h-0 flex-1 overflow-y-auto overscroll-contain border-t border-(--color-border-subtle) px-1.5">
                    <ProjectSessionList
                      projectId={project.id}
                      currentSessionId={currentSessionId}
                      mobileLongPressActions={mobileLongPressActions}
                      onSessionSelect={handleSessionSelect}
                      onSessionSideChat={handleSessionSideChat}
                      onSessionDelete={handleSessionDelete}
                      pendingDeleteId={pendingDeleteSession?.id ?? null}
                      onCancelDelete={() => setPendingDeleteSession(null)}
                      onConfirmDelete={confirmSessionDelete}
                      onSessionEdit={handleSessionEdit}
                      onSessionLongPress={setMobileSessionActions}
                      onSessionContextActions={(session, event) => {
                        setDesktopSessionActions({ session, x: event.clientX, y: event.clientY });
                      }}
                    />
                  </div>
                </>
              );
            })()}
          </div>
        )}
      </div>
    </div>
  );

  // Desktop: the shell owns width persistence, the resize handle, and the
  // collapse-to-zero animation; coding keeps its stacked separate cards.
  const desktopShell = (
    <SidebarShell
      collapsed={sidebarCollapsed}
      resizeLabel="Resize coding sidebar"
    >
      <SidebarCard
        className={`shrink-0 px-1.5 pb-0 ${isMacOverlay ? 'pt-10' : 'pt-1.5'}`}
      >
        <SidebarModeSlot />
        {onCommandPalette && (
          <div className="pt-2">
            <SidebarSearchTrigger onClick={onCommandPalette} compact />
          </div>
        )}
      </SidebarCard>

      {/* Scheduler toggle */}
      <SidebarCard className="shrink-0">
        <SidebarNavGroup ariaLabel="Primary" grid className="px-1.5 pb-1 pt-2">
          <SidebarItem
            Icon={CalendarClock}
            label="Scheduler"
            kbd="^S"
            tile
            onClick={toggleScheduler}
          />
          <SidebarItem
            Icon={Blocks}
            label="Plugins"
            kbd="^K"
            tile
            onClick={() => togglePlugins("plugins")}
          />
          <SidebarItem
            Icon={GitBranch}
            label="Source Control"
            kbd="^G"
            tile
            onClick={() => toggleSourceControl("source-control")}
          />
        </SidebarNavGroup>
      </SidebarCard>

      {/* Unified workspace navigator */}
      <SidebarCard className="flex-1">
        <div className="min-h-0 flex-1 overflow-hidden">
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
        x: mobileOpen ? 0 : -(drawerMode ? sidebarWidth + 8 : 340),
        width: drawerMode
          ? `min(${sidebarWidth}px, calc(100vw - 2rem))`
          : "min(340px, calc(100vw - 1rem))",
      }}
      transition={preset.spring}
      aria-hidden={!mobileOpen}
      aria-label="Coding navigation"
      aria-modal={mobileOpen ? true : undefined}
      data-modal-focus={mobileOpen ? 'true' : undefined}
      {...(!mobileOpen ? { inert: true } : {})}
      className={cn(
        "mobile-nav-drawer mobile-safe-top fixed bottom-0 left-0 z-(--z-overlay) flex w-[min(340px,calc(100vw-1rem))] shrink-0 flex-col overflow-hidden rounded-r-2xl border-r border-(--color-border) bg-(--bg-sidebar) pb-safe shadow-2xl",
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
      <SidebarNavGroup ariaLabel="Primary" grid className="px-3 pt-2">
        <SidebarItem
          Icon={CalendarClock}
          label="Scheduler"
          kbd="^S"
          tile
          onClick={() => {
            toggleScheduler();
            onMobileClose?.();
          }}
        />
        <SidebarItem
          Icon={Blocks}
          label="Plugins"
          kbd="^K"
          tile
          onClick={() => {
            togglePlugins("plugins");
            onMobileClose?.();
          }}
        />
        <SidebarItem
          Icon={GitBranch}
          label="Source Control"
          kbd="^G"
          tile
          onClick={() => {
            toggleSourceControl("source-control");
            onMobileClose?.();
          }}
        />
      </SidebarNavGroup>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
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
        // Select what was just created. Without this the sidebar stayed on the
        // previous project and the new one looked like it had not been made.
        onCreated={(projectId) => {
          setSelectedProjectId(projectId);
          writeLastCodingProject(projectId);
        }}
      />

      {/* A centred modal: picking a folder is a one-off decision, not a
          panel to keep beside the chat. It closes while the trust dialog
          asks about the chosen folder, and Back reopens it. */}
      <Dialog
        open={dialogOpen && !trustWorkspace}
        onOpenChange={(open) => {
          if (!open) closeWorkspaceDialog();
        }}
      >
        <DialogContent className="flex max-h-[min(90dvh,720px)] w-[calc(100vw-1.5rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-xl">
          <DialogHeader className="shrink-0 border-b border-(--color-border) px-4 py-3 pr-10">
            <DialogTitle className="text-sm font-semibold">
              {workspacePickerMode === "clone"
                ? addRepoProject
                  ? `Clone repository into ${addRepoProject.name}`
                  : "Clone repository"
                : addRepoProject
                  ? `Add repository to ${addRepoProject.name}`
                  : "Open folder as project"}
            </DialogTitle>
            <DialogDescription className="text-xs leading-4">
              {addRepoProject
                ? `Add an existing folder or clone a remote repository into ${addRepoProject.name}.`
                : "Open an existing folder or clone a remote repository. It becomes a project named after the folder; you can add more repositories to it later."}
            </DialogDescription>
          </DialogHeader>
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
              {!addRepoProject && (
                <button
                  type="button"
                  onClick={() => {
                    closeWorkspaceDialog();
                    setShowProjectModal(true);
                  }}
                  className="self-start text-xs text-(--color-accent) hover:underline"
                >
                  Set up a multi-repo project instead
                </button>
              )}
              <div className="grid grid-cols-2 gap-1 rounded-lg border border-(--color-border) bg-(--bg-key)/60 p-1">
                <button
                  type="button"
                  onClick={() => setWorkspacePickerMode("open")}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-medium",
                    workspacePickerMode === "open"
                      ? "bg-(--bg-card) text-(--color-text) shadow-sm"
                      : "text-(--color-text-muted) hover:text-(--color-text)",
                  )}
                >
                  Open folder
                </button>
                <button
                  type="button"
                  onClick={() => setWorkspacePickerMode("clone")}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-medium",
                    workspacePickerMode === "clone"
                      ? "bg-(--bg-card) text-(--color-text) shadow-sm"
                      : "text-(--color-text-muted) hover:text-(--color-text)",
                  )}
                >
                  Clone repository
                </button>
              </div>
              {workspacePickerMode === "clone" ? (
                <div className="flex shrink-0 flex-col gap-3">
                  <label className="space-y-1.5 text-xs text-(--color-text-muted)">
                    <span>Repository URL</span>
                    <input
                      value={cloneUrl}
                      onChange={(event) => setCloneUrl(event.target.value)}
                      placeholder="https://github.com/org/repository.git"
                      spellCheck={false}
                      className="h-9 w-full rounded-md border border-(--color-border) bg-(--bg-page) px-3 font-mono text-xs text-(--color-text) outline-none focus:border-(--color-accent)"
                    />
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <label className="space-y-1.5 text-xs text-(--color-text-muted)">
                      <span>Folder name (optional)</span>
                      <input
                        value={cloneDirectory}
                        onChange={(event) => setCloneDirectory(event.target.value)}
                        placeholder="Auto-detect"
                        className="h-9 w-full rounded-md border border-(--color-border) bg-(--bg-page) px-3 text-xs text-(--color-text) outline-none focus:border-(--color-accent)"
                      />
                    </label>
                    <label className="space-y-1.5 text-xs text-(--color-text-muted)">
                      <span>Branch (optional)</span>
                      <input
                        value={cloneBranch}
                        onChange={(event) => setCloneBranch(event.target.value)}
                        placeholder="Default branch"
                        className="h-9 w-full rounded-md border border-(--color-border) bg-(--bg-page) px-3 font-mono text-xs text-(--color-text) outline-none focus:border-(--color-accent)"
                      />
                    </label>
                  </div>
                  <div className="space-y-2">
                    <span className="text-xs text-(--color-text-muted)">Clone into</span>
                    <div className="rounded-lg border border-(--color-border) bg-(--bg-page) px-3 py-2 font-mono text-xs text-(--color-text-muted) [overflow-wrap:anywhere]">
                      {(nativeFolderPickerEnabled && !isTauriMobile ? cloneParent : browserPath) ?? "Choose a destination folder"}
                    </div>
                    {nativeFolderPickerEnabled && !isTauriMobile ? (
                      <Button
                        type="button"
                        variant="outline"
                        disabled={loading}
                        onClick={() => void pickNativeFolder("clone")}
                      >
                        <Folder size={13} />
                        Choose destination…
                      </Button>
                    ) : (
                      <div className="max-h-44 space-y-1 overflow-y-auto rounded-lg border border-(--color-border) p-1">
                        {parentPath && (
                          <button type="button" className="w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-(--bg-key)" onClick={() => void loadBrowser(parentPath)}>..</button>
                        )}
                        {dirs.map((dir) => (
                          <button type="button" key={dir.path} className="flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-(--bg-key)" onClick={() => void loadBrowser(dir.path)}>
                            <Folder size={14} className="shrink-0" />
                            <span className="min-w-0 truncate">{dir.name}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  {error && <p className="text-xs text-(--color-error)">{error}</p>}
                  <p className="text-[11px] text-(--color-text-subtle)">
                    HTTPS clones reuse matching credentials from Git & reviews. SSH URLs use your SSH agent; credentials in URLs are rejected.
                  </p>
                  <div className="flex items-center justify-end gap-2">
                    <Button type="button" variant="outline" onClick={closeWorkspaceDialog}>Cancel</Button>
                    <Button
                      type="button"
                      disabled={loading || !cloneUrl.trim() || !(nativeFolderPickerEnabled && !isTauriMobile ? cloneParent : browserPath)}
                      onClick={() => void cloneRepositoryFromDialog()}
                    >
                      {loading ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                      {loading ? "Cloning…" : "Clone repository"}
                    </Button>
                  </div>
                </div>
              ) : nativeFolderPickerEnabled && !isTauriMobile ? (
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
                    void pickNativeFolder("workspace");
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
        </DialogContent>
      </Dialog>

      <Dialog open={trustWorkspace !== null} onOpenChange={(open) => {
        if (!open && !openingFolder) setTrustWorkspace(null);
      }}>
        <DialogContent showCloseButton={false} className="min-w-0">
          <DialogHeader>
            <DialogTitle>Trust this folder?</DialogTitle>
            <DialogDescription>
              {addRepoProject
                ? `Coding mode grants agents filesystem and shell access. The project's repositories are the primary working area, but agents may access other paths outside them (excluding system directories). Trusting adds this folder to ${addRepoProject.name}.`
                : trustOwners.length > 0
                  // The notice below says which project opens instead.
                  ? "Coding mode grants agents filesystem and shell access. The project's repositories are the primary working area, but agents may access other paths outside them (excluding system directories)."
                  : "Coding mode grants agents filesystem and shell access. The project's repositories are the primary working area, but agents may access other paths outside them (excluding system directories). Trusting creates a project for this folder."}
            </DialogDescription>
          </DialogHeader>
          {!addRepoProject && trustOwners.length > 0 && (
            <div
              role="status"
              className="flex gap-2 rounded-lg border border-(--color-warning)/40 bg-(--color-warning)/10 px-3 py-2 text-xs leading-4 text-(--color-text)"
            >
              <AlertTriangle
                size={14}
                className="mt-px shrink-0 text-(--color-warning)"
                aria-hidden="true"
              />
              <p>
                {trustOwners.length === 1
                  ? `This folder is already in the project ${trustOwners[0].name}. Trusting opens that project; no new project is created.`
                  : `This folder is already in ${trustOwners.length} projects (${trustOwners.map((project) => project.name).join(", ")}). Trusting opens ${trustOwners[0].name}; no new project is created.`}
              </p>
            </div>
          )}
          <div className="rounded-lg border border-(--color-border) bg-(--bg-page) px-3 py-2">
            <p className="break-all font-mono text-xs text-(--color-text-muted)">
              {trustWorkspace}
            </p>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={openingFolder}
              onClick={() => setTrustWorkspace(null)}
            >
              Back
            </Button>
            <Button
              type="button"
              onClick={() => void confirmTrustedWorkspace()}
              disabled={openingFolder}
            >
              {openingFolder && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}
              {addRepoProject
                ? "Trust and add"
                : openingFolder
                  ? "Opening project…"
                  : trustOwners.length > 0
                    ? "Trust and open project"
                    : "Trust and create project"}
            </Button>
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
                    {worktreeLocation === "user_data"
                      ? "Stored in EvoFlux data, outside the source repo. Uncommitted source changes are not copied."
                      : "Stored in the source repo under .evoflux/worktrees. Uncommitted source changes are not copied."}
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
                void openWorktreeDialog(action.path, action.project.id);
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
                if (action) void openWorktreeDialog(action.path, action.project.id);
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
        onDuplicate={handleSessionDuplicate}
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
        onDuplicate={handleSessionDuplicate}
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
              repository&apos;s app-owned session data. Source files stay on disk.
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
                      // Drop only the removed repository's cached tree/diff/
                      // status; an empty filter wiped every query in the app.
                      queryClient.removeQueries({
                        queryKey: queryKeys.coding.all(target.path),
                      });
                      if (isRemovingFromActiveProject) {
                        clearLastCodingFocus(target.project.id);
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
                ? `Delete ${deleteProjectTarget.name}? All project chat sessions, scheduled tasks, generated session data, and managed worktrees will be permanently deleted. Source repositories stay on disk and can be opened as a project again.`
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
