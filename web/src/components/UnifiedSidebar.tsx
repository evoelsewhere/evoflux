/**
 * UnifiedSidebar — single sidebar that works for both forge and coding modes.
 *
 * Mode switcher (Forge/Coding) at the top.
 * Search/command palette.
 * New Chat + Scheduler.
 * Content area:
 *   - Forge mode: Sessions grouped by date (Today, Yesterday, Older)
 *   - Coding mode: Projects and Workspaces sections with nested sessions
 * Footer: Settings, Theme toggle, Health dot.
 *
 * Replaces the separate Sidebar.tsx and CodingSidebar.tsx to avoid
 * desynchronization between the two sidebars.
 */
import { useState, useEffect, useMemo, useCallback, useRef, type TouchEvent } from "react";
import { useNavigate } from "@tanstack/react-router";
import { motion, AnimatePresence } from "framer-motion";
import { useIsMobile } from "@/hooks/use-mobile";
import { usePlatform } from "@/hooks/use-platform";
import { useResizableWidth } from "@/hooks/use-resizable-width";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useCodingSidebarState } from "@/hooks/useCodingSidebarState";
import {
  CalendarClock,
  ChevronDown,
  Code2,
  Folder,
  FolderPlus,
  Gauge,
  GitBranch,
  Loader2,
  Pencil,
  Plus,
  Search,
  Settings,
  Trash2,
  RefreshCw,
  HelpCircle,
  ChevronRight,
} from "lucide-react";
import { isToday, isYesterday } from "date-fns";
import {
  useTeamSessionsQuery,
  useDeleteTeamSessionMutation,
  useUpdateTeamSessionTitleMutation,
} from "@/queries";
import {
  useCodingWorkspaceSessionsQuery,
  useProjectSessionsQuery,
} from "@/queries/useSessionsQuery";
import { useUIStore } from "@/stores/useUIStore";
import { formatRelativeDate } from "@/utils/format";
import { workspaceLabel } from "@/utils/workspace";
import { ThemeToggle } from "./ThemeToggle";
import { HealthDot } from "./HealthDot";
import { SidebarItem } from "@/components/ui/sidebar-item";
import { Skeleton } from "./ui/skeleton";
import { LongPressButton } from "@/components/ui/long-press-button";
import type { SessionResponse } from "@/api/types";
import { UnifiedSidebarDialogs } from "./UnifiedSidebarDialogs";

// ── Helpers ──────────────────────────────────────────────────────────────────

function groupByDate(sessions: SessionResponse[]) {
  const today: SessionResponse[] = [];
  const yesterday: SessionResponse[] = [];
  const older: SessionResponse[] = [];

  for (const s of sessions) {
    const date = s.created_at ? new Date(s.created_at) : null;
    if (!date) {
      older.push(s);
      continue;
    }
    if (isToday(date)) today.push(s);
    else if (isYesterday(date)) yesterday.push(s);
    else older.push(s);
  }

  const groups: Array<{ label: string; sessions: SessionResponse[] }> = [];
  if (today.length) groups.push({ label: "Today", sessions: today });
  if (yesterday.length) groups.push({ label: "Yesterday", sessions: yesterday });
  if (older.length) groups.push({ label: "Older", sessions: older });
  return groups;
}

function SessionListSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="space-y-1 px-1 py-2" aria-label="Loading sessions">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="rounded-md px-2.5 py-2">
          <Skeleton className="h-3 w-[min(11rem,70%)] bg-(--bg-key)" />
          <Skeleton className="mt-2 h-2.5 w-20 bg-(--bg-key)" />
        </div>
      ))}
    </div>
  );
}

// ── Shared session list panel (used by project & workspace session lists) ────

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
  const projectSessions = allSessions.filter((s) => !s.scheduled_task_name);

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
                  className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center justify-center rounded-xs p-1 text-(--color-text-subtle) opacity-0 transition-all hover:bg-(--bg-key) hover:text-(--color-error) group-hover:opacity-100 pointer-coarse:opacity-100"
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

// ── Expand / collapse wrapper (simple height + opacity) ─────────────────────

function Expandable({
  open,
  children,
}: {
  open: boolean;
  children: React.ReactNode;
}) {
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.15, ease: "easeInOut" }}
          style={{ overflow: "hidden" }}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ── Extracted sidebar sub-components ─────────────────────────────────────────

function ModeSwitcher({
  mode,
  isIconOnly,
  isMacOverlay,
  onNavigate,
}: {
  mode: "forge" | "coding";
  isIconOnly: boolean;
  isMacOverlay: boolean;
  onNavigate: (to: string) => void;
}) {
  if (isIconOnly) {
    return (
      <div
        className={`flex flex-col items-center gap-0.5 pb-1 ${isMacOverlay ? "pt-10" : ""}`}
      >
        <button
          type="button"
          onClick={() => onNavigate("/")}
          title="Forge"
          className={`flex h-8 w-8 items-center justify-center rounded-md transition-all duration-200 ${
            mode === "forge"
              ? "bg-(--bg-key) text-(--color-accent) shadow-sm"
              : "text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text-2)"
          }`}
        >
          <Gauge size={16} aria-hidden="true" />
        </button>
        <button
          type="button"
          onClick={() => onNavigate("/coding")}
          title="Coding"
          className={`flex h-8 w-8 items-center justify-center rounded-md transition-all duration-200 ${
            mode === "coding"
              ? "bg-(--bg-key) text-(--color-accent) shadow-sm"
              : "text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text-2)"
          }`}
        >
          <Code2 size={16} aria-hidden="true" />
        </button>
      </div>
    );
  }

  return (
    <div className={`px-2 ${isMacOverlay ? "pt-10" : "pt-2"}`}>
      <div className="flex h-8 items-center rounded-md border border-(--color-border) bg-(--bg-page) p-0.5">
        <button
          type="button"
          onClick={() => onNavigate("/")}
          className={`flex h-full flex-1 items-center justify-center gap-1.5 rounded-[5px] px-2 text-xs font-medium transition-all duration-200 ${
            mode === "forge"
              ? "bg-(--bg-key) text-(--color-text) shadow-sm"
              : "text-(--color-text-muted) hover:text-(--color-text)"
          }`}
        >
          <Gauge size={12} aria-hidden="true" />
          Forge
        </button>
        <button
          type="button"
          onClick={() => onNavigate("/coding")}
          className={`flex h-full flex-1 items-center justify-center gap-1.5 rounded-[5px] px-2 text-xs font-medium transition-all duration-200 ${
            mode === "coding"
              ? "bg-(--bg-key) text-(--color-text) shadow-sm"
              : "text-(--color-text-muted) hover:text-(--color-text)"
          }`}
        >
          <Code2 size={12} aria-hidden="true" />
          Coding
        </button>
      </div>
    </div>
  );
}

function SearchTrigger({
  isIconOnly,
  onCommandPalette,
}: {
  isIconOnly: boolean;
  onCommandPalette?: () => void;
}) {
  if (!onCommandPalette) return null;
  if (isIconOnly) {
    return (
      <SidebarItem
        Icon={Search}
        label="Commands"
        kbd="^P"
        collapsed
        onClick={onCommandPalette}
      />
    );
  }

  return (
    <div className="px-2 pt-2">
      <button
        type="button"
        onClick={onCommandPalette}
        className="flex h-8 w-full items-center gap-2 rounded-md border border-(--color-border) bg-(--bg-page) px-2.5 text-left text-xs text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-2)"
        aria-label="Open command palette"
        title="Open command palette (Ctrl+P)"
      >
        <Search size={13} aria-hidden="true" />
        <span className="flex-1">Search…</span>
        <kbd className="font-mono text-xs text-(--color-text-subtle)">^P</kbd>
      </button>
    </div>
  );
}

/** Small icon button used in workspace rows for per-item actions. */
function WorkspaceActionButton({
  onClick,
  ariaLabel,
  title,
  isMobile,
  children,
  variant = "default",
}: {
  onClick: (e: React.MouseEvent) => void;
  ariaLabel: string;
  title: string;
  isMobile: boolean;
  children: React.ReactNode;
  variant?: "default" | "danger";
}) {
  const base = "ml-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-xs transition-all";
  const colors =
    variant === "danger"
      ? "text-(--color-text-subtle) hover:bg-(--color-error-subtle) hover:text-(--color-error)"
      : "border border-(--color-border) text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text-2)";
  const visibility = isMobile ? "opacity-100" : "opacity-0 group-hover:opacity-100";
  return (
    <button
      type="button"
      onClick={onClick}
      className={`${base} ${colors} ${visibility}`}
      aria-label={ariaLabel}
      title={title}
    >
      {children}
    </button>
  );
}

function SectionHeader({
  label,
  collapsed,
  onToggle,
  onAction,
  actionTitle,
}: {
  label: string;
  collapsed: boolean;
  onToggle: () => void;
  onAction: () => void;
  actionTitle: string;
}) {
  return (
    <div className="flex items-center justify-between px-1 pb-1">
      <button
        type="button"
        onClick={onToggle}
        className="flex min-w-0 flex-1 items-center gap-1 rounded-xs py-0.5 text-left hover:bg-(--bg-key)"
        aria-expanded={!collapsed}
        aria-label={`${collapsed ? "Expand" : "Collapse"} ${label} section`}
      >
        <ChevronRight
          size={10}
          className={`shrink-0 text-(--color-text-muted) transition-transform duration-200 ${!collapsed ? "rotate-90" : ""}`}
          aria-hidden="true"
        />
        <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-muted)">
          {label}
        </span>
      </button>
      <button
        type="button"
        onClick={onAction}
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text)"
        title={actionTitle}
      >
        <Plus size={12} />
      </button>
    </div>
  );
}

function SidebarFooter({
  isIconOnly,
  onCommandPalette,
  openSettings,
}: {
  isIconOnly: boolean;
  onCommandPalette?: () => void;
  openSettings: () => void;
}) {
  if (isIconOnly) {
    return (
      <div className="flex justify-center py-2 pb-safe px-1">
        <ThemeToggle collapsed />
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between gap-2 px-3 py-2 pb-safe">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={openSettings}
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
  );
}

// ── Main component ──────────────────────────────────────────────────────────

const COLLAPSE_KEY = "oa-sidebar-collapsed";

interface UnifiedSidebarProps {
  currentSessionId?: string;
  onCommandPalette?: () => void;
  /** New chat callback */
  onNewChat?: () => void;
  /** Current mode — 'forge' or 'coding' */
  mode?: "forge" | "coding";
  /** Coding mode: workspace path */
  workspace?: string | null;
  /** Coding mode: bump this counter to programmatically open the workspace dialog */
  openWorkspaceDialogKey?: number;
  /** Desktop only: when true, the inline panel collapses to width=0 */
  desktopCollapsed?: boolean;
  /** Mobile only: whether the overlay drawer is open */
  mobileOpen?: boolean;
  /** Mobile only: called when the drawer should close */
  onMobileClose?: () => void;
}

export function UnifiedSidebar({
  currentSessionId,
  onCommandPalette,
  onNewChat,
  mode = "forge",
  workspace,
  openWorkspaceDialogKey = 0,
  desktopCollapsed = false,
  mobileOpen = false,
  onMobileClose,
}: UnifiedSidebarProps) {
  const isMobile = useIsMobile();
  const { isTauri, os, isMacOverlay } = usePlatform();
  const isTauriMobile = isTauri && (os === "ios" || os === "android");
  const mobileLongPressActions = isMobile && isTauriMobile && mobileOpen;
  const prefersReducedMotion = useReducedMotion();
  const navigate = useNavigate();
   const toggleScheduler = useUIStore((s) => s.toggleScheduler);
   const openSettings = useUIStore((s) => s.openSettings);

  // ── Forge mode state ───────────────────────────────────────────────────

  const sessions = useTeamSessionsQuery();
  const deleteSession = useDeleteTeamSessionMutation();
  const updateSessionTitle = useUpdateTeamSessionTitleMutation();
  const sessionListRef = useRef<HTMLDivElement>(null);
  const loadMoreRef = useRef<HTMLDivElement>(null);

  const allSessions = useMemo(
    () => sessions.data?.pages.flatMap((p) => p.data) ?? [],
    [sessions.data],
  );
  const normalSessions = useMemo(
    () => allSessions.filter((s) => s.mode !== "coding"),
    [allSessions],
  );

  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "true";
    } catch {
      return false;
    }
  });

  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<SessionResponse | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const pullDistanceRef = useRef(0);
  const pullStartYRef = useRef<number | null>(null);

  const toggleCollapse = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(COLLAPSE_KEY, String(next));
      } catch {
        // ignore
      }
      return next;
    });
  }, []);

  const refetchSessions = sessions.refetch;
  const canPullRefresh = isMobile && mobileOpen;

  const handleSessionListTouchStart = useCallback(
    (event: TouchEvent<HTMLDivElement>) => {
      if (!canPullRefresh || sessionListRef.current?.scrollTop !== 0) return;
      pullStartYRef.current = event.touches[0]?.clientY ?? null;
    },
    [canPullRefresh],
  );

  const handleSessionListTouchMove = useCallback(
    (event: TouchEvent<HTMLDivElement>) => {
      if (!canPullRefresh || pullStartYRef.current === null) return;
      const delta = (event.touches[0]?.clientY ?? 0) - pullStartYRef.current;
      if (delta <= 0) {
        pullDistanceRef.current = 0;
        return;
      }
      pullDistanceRef.current = Math.min(72, delta * 0.5);
    },
    [canPullRefresh],
  );

  const handleSessionListTouchEnd = useCallback(() => {
    if (canPullRefresh && pullDistanceRef.current >= 54) {
      void refetchSessions();
    }
    pullStartYRef.current = null;
    pullDistanceRef.current = 0;
  }, [canPullRefresh, refetchSessions]);

  // Ctrl+B: collapse sidebar; Ctrl+R: refresh sessions.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.metaKey) return;
      if (e.key === "b") {
        e.preventDefault();
        toggleCollapse();
      }
      if (e.key === "r") {
        e.preventDefault();
        refetchSessions();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggleCollapse, refetchSessions]);

  const { hasNextPage, isFetchingNextPage, fetchNextPage } = sessions;

  // Intersection observer — load next page when sentinel scrolls into view.
  useEffect(() => {
    const sentinel = loadMoreRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage();
        }
      },
      { root: sessionListRef.current, threshold: 0.1 },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const handleDelete = (session: SessionResponse) => {
    setPendingDeleteId(session.id);
  };

  const handleEdit = (session: SessionResponse) => {
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

  const confirmDelete = () => {
    if (!pendingDeleteId) return;
    const target = allSessions.find((s) => s.id === pendingDeleteId);
    if (!target) return;
    const fallbackSession =
      target.id === currentSessionId
        ? normalSessions.find((session) => session.id !== target.id)
        : null;
    deleteSession.mutate(target.id);
    if (target.id === currentSessionId) {
      if (fallbackSession) {
        navigate({
          to: "/$sessionId",
          params: { sessionId: fallbackSession.id },
          replace: true,
        });
      } else {
        navigate({ to: "/", replace: true });
      }
    }
    setPendingDeleteId(null);
  };

  const handleSelect = (id: string) => {
    navigate({ to: "/$sessionId", params: { sessionId: id } });
    onMobileClose?.();
  };

  const handleNewChat = () => {
    if (onNewChat) {
      onNewChat();
    } else {
      navigate({ to: "/" });
    }
    onMobileClose?.();
  };

  const handleNavigateForMode = useCallback(
    (to: string) => {
      navigate({ to });
      onMobileClose?.();
    },
    [navigate, onMobileClose],
  );

  // ── Coding mode state (extracted to useCodingSidebarState hook) ────────

  const coding = useCodingSidebarState({
    allSessions,
    currentSessionId,
    workspace,
    openWorkspaceDialogKey,
    isTauri,
    isTauriMobile,
    onMobileClose,
    setEditTarget,
    setEditTitle,
    pendingDeleteId,
    setPendingDeleteId,
    deleteSession,
  });

  const {
    overviewQuery,
    projects,
    removeWorkspaceMutation,
    showProjectModal,
    setShowProjectModal,
    pendingProject,
    expandedProjects,
    expandedWorkspaces,
    projectsSectionCollapsed,
    setProjectsSectionCollapsed,
    workspacesSectionCollapsed,
    setWorkspacesSectionCollapsed,
    codingSessions,
    projectRunningMap,
    currentProjectId,
    activeWorkspace,
    standaloneWorkspaces,
    nativeFolderPickerEnabled,
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
    loadBrowser,
    closeWorkspaceDialog,
    openWorkspaceDialog,
    openSelectedFolder,
    confirmTrustedWorkspace,
    openAddRepoDialog,
    refreshWorkspaceTree,
    selectWorkspace,
    openProjectSession,
    handleSessionSelect,
    handleSessionEdit,
    handleSessionDelete,
    confirmSessionDelete,
    confirmRemoveWorkspace,
    openWorktreeDialog,
    handleRemoveWorktree,
    submitWorktree,
    toggleProjectExpanded,
    toggleWorkspaceExpanded,
  } = coding;

  const resizable = useResizableWidth({
    storageKey: "oa.sidebar.width",
    defaultWidth: 220,
    minWidth: 180,
    maxWidth: 360,
    edge: "right",
    disabled: isMobile || collapsed || desktopCollapsed,
  });

  const showIconOnly = !isMobile && (collapsed || desktopCollapsed);
  const desktopWidth = showIconOnly
    ? isMacOverlay ? 70 : 56
    : resizable.width;

  // ── Shared action handlers for coding sessions ─────────────────────────

  const codingSessionActions = useMemo<Omit<SessionListActionProps, "onSessionSelect">>(() => ({
    currentSessionId,
    mobileLongPressActions,
    onSessionDelete: handleSessionDelete,
    pendingDeleteId,
    onCancelDelete: () => setPendingDeleteId(null),
    onConfirmDelete: confirmSessionDelete,
    onSessionEdit: handleSessionEdit,
    onSessionLongPress: setMobileSessionActions,
    onSessionContextActions: (session, event) => {
      setDesktopSessionActions({
        session,
        x: event.clientX,
        y: event.clientY,
      });
    },
  }), [currentSessionId, mobileLongPressActions, handleSessionDelete, pendingDeleteId, confirmSessionDelete, handleSessionEdit, setMobileSessionActions, setDesktopSessionActions]);

  const sessionGroups = useMemo(
    () => groupByDate(normalSessions),
    [normalSessions],
  );

  // ── Forge sessions content ─────────────────────────────────────────────

  const forgeSessionsContent = (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between px-3 pb-1 pt-2.5">
        <span className="text-xs font-medium text-(--color-text-subtle)">
          Recent
        </span>
        <button
          onClick={() => refetchSessions()}
          className="rounded-xs p-1 text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-muted)"
          aria-label="Refresh sessions"
          title="Refresh sessions (Ctrl+R)"
        >
          <RefreshCw
            size={11}
            className={sessions.isFetching ? "animate-spin" : ""}
          />
        </button>
      </div>
      <div
        ref={sessionListRef}
        className="relative flex-1 overflow-y-auto px-2 pb-2"
        onTouchStart={handleSessionListTouchStart}
        onTouchMove={handleSessionListTouchMove}
        onTouchEnd={handleSessionListTouchEnd}
        onTouchCancel={handleSessionListTouchEnd}
      >
        {sessions.isLoading && <SessionListSkeleton />}
        {sessions.isError && (
          <p className="px-3 py-4 text-center text-xs text-(--color-error)">
            Failed to load sessions
          </p>
        )}
        {sessions.isSuccess && normalSessions.length === 0 && (
          <p className="px-3 py-4 text-center text-xs text-(--color-text-subtle)">
            No sessions yet
          </p>
        )}
        {sessions.isSuccess && normalSessions.length > 0 && (
          <div className="space-y-0.5">
            {sessionGroups.map(({ label, sessions: group }) => (
              <div key={label}>
                <p className="px-3 pb-1 pt-3 text-xs font-medium text-(--color-text-subtle) first:pt-1.5">
                  {label}
                </p>
                {group.map((session) => {
                  const isCurrent = session.id === currentSessionId;
                  const isRunning = session.running === true;
                  const isPendingDelete = pendingDeleteId === session.id;
                  return (
                    <div key={session.id} className="group relative">
                      <button
                        type="button"
                        onClick={() => handleSelect(session.id)}
                        onDoubleClick={(e) => {
                          e.stopPropagation();
                          handleEdit(session);
                        }}
                        className={`w-full rounded-md px-2 py-1 text-left text-xs transition-colors ${
                          isCurrent
                            ? "bg-(--bg-key) text-(--color-text) shadow-sm"
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
                      </button>
                      {!isPendingDelete && (
                        <>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleEdit(session);
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
                              handleDelete(session);
                            }}
                            className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center justify-center rounded-xs p-1 text-(--color-text-subtle) opacity-0 transition-all hover:bg-(--bg-key) hover:text-(--color-error) group-hover:opacity-100 pointer-coarse:opacity-100"
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
                              setPendingDeleteId(null);
                            }}
                            className="rounded-xs border border-(--color-border) bg-(--bg-card) px-2 py-1 text-xs text-(--color-text) hover:bg-(--bg-key)"
                          >
                            Cancel
                          </button>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              confirmDelete();
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
              </div>
            ))}
            <div ref={loadMoreRef} className="h-1" aria-hidden />
            {isFetchingNextPage && <SessionListSkeleton count={3} />}
          </div>
        )}
      </div>
    </div>
  );

  // ── Coding mode content ────────────────────────────────────────────────

  const codingContent = (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      {/* PROJECTS section */}
      <div className="px-2 pt-2 pb-1">
        <SectionHeader
          label="Projects"
          collapsed={projectsSectionCollapsed}
          onToggle={() => setProjectsSectionCollapsed((v) => !v)}
          onAction={() => setShowProjectModal(true)}
          actionTitle="New multi-repo project"
        />

        <Expandable open={!projectsSectionCollapsed}>
          {overviewQuery.isLoading && (
            <div className="flex items-center gap-1.5 px-2 py-1.5">
              <Loader2
                size={11}
                className="animate-spin text-(--color-text-muted)"
              />
              <span className="text-xs text-(--color-text-muted)">
                Loading…
              </span>
            </div>
          )}

          {!overviewQuery.isLoading && projects.length === 0 && (
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

          <div className="space-y-0.5">
            {projects.map((project) => {
              const isActive = currentProjectId === project.id;
              const isExpanded = expandedProjects.has(project.id);
              const projectHasRunning = projectRunningMap.get(project.id) === true;
              const isPending = pendingProject === project.id;
              const canCreateSession = (project.workspaces?.length ?? 0) > 0;

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
                    {/* I6: pendingProject loading spinner */}
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
                      {/* I5: Project repo listing */}
                      {(project.workspaces ?? []).length === 0 && (
                        <p className="px-2 py-1 text-xs text-(--color-text-subtle)">
                          No repos yet.
                        </p>
                      )}
                      {(project.workspaces ?? []).map((w) => (
                        <div
                          key={w.workspace_id}
                          className="group/repo flex w-full min-w-0 items-center gap-1.5 truncate rounded-xs px-2 py-1 text-left text-xs text-(--color-text-2)"
                          title={w.path}
                        >
                          <Folder size={11} className="shrink-0 text-(--color-text-subtle)" aria-hidden="true" />
                          <span className="min-w-0 flex-1 truncate">
                            {w.display_name || w.name || workspaceLabel(w.path)}
                          </span>
                          {/* I3: Remove repo from project */}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              removeWorkspaceMutation.mutate(
                                { projectId: project.id, workspaceId: w.workspace_id },
                                { onSuccess: () => void refreshWorkspaceTree() },
                              );
                            }}
                            className="ml-auto flex h-4 w-4 shrink-0 items-center justify-center rounded-xs text-(--color-text-subtle) opacity-0 transition-all hover:bg-(--color-error-subtle) hover:text-(--color-error) group-hover/repo:opacity-100"
                            aria-label={`Remove ${w.display_name || w.name || workspaceLabel(w.path)} from project`}
                            title="Remove from project"
                          >
                            <Trash2 size={10} aria-hidden="true" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  <Expandable open={isExpanded}>
                    <ProjectSessionList
                      projectId={project.id}
                      {...codingSessionActions}
                      onSessionSelect={(session) =>
                        handleSessionSelect(session, session.workspace ?? "")
                      }
                    />
                  </Expandable>
                </div>
              );
            })}
          </div>
        </Expandable>
      </div>

      <div className="shrink-0 h-px bg-(--color-border) mx-3" />

      {/* WORKSPACES section */}
      <div className="px-2 pt-2 pb-1">
        <SectionHeader
          label="Workspaces"
          collapsed={workspacesSectionCollapsed}
          onToggle={() => setWorkspacesSectionCollapsed((v) => !v)}
          onAction={() => void openWorkspaceDialog()}
          actionTitle="Open folder"
        />

        <Expandable open={!workspacesSectionCollapsed}>
          {standaloneWorkspaces.length === 0 && (
            <p className="px-2 py-1.5 text-xs text-(--color-text-subtle)">
              No workspaces yet.
            </p>
          )}

          <div className="space-y-0.5">
            {standaloneWorkspaces.map((workspacePath) => {
              const isActive = activeWorkspace === workspacePath;
              const isExpanded = expandedWorkspaces.has(workspacePath);
              const sourceIsPending = pendingWorkspace === workspacePath;
              const sourceHasRunningSession = codingSessions.some(
                (s) => s.workspace === workspacePath && s.running === true,
              );

              return (
                <div key={workspacePath}>
                  <div className="group flex h-8 items-center pr-2">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleWorkspaceExpanded(workspacePath);
                      }}
                      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-xs text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)"
                      aria-expanded={isExpanded}
                      aria-label={`${isExpanded ? "Collapse" : "Expand"} session history for ${workspaceLabel(workspacePath)}`}
                    >
                      {isExpanded ? (
                        <ChevronDown size={10} aria-hidden="true" />
                      ) : (
                        <ChevronRight size={10} aria-hidden="true" />
                      )}
                    </button>
                    <LongPressButton
                      enabled={mobileLongPressActions}
                      onLongPress={() =>
                        setMobileWorkspaceActions({ path: workspacePath, kind: "main" })
                      }
                      type="button"
                      onClick={() => void selectWorkspace(workspacePath)}
                      onContextMenu={(event) => {
                        if (mobileLongPressActions) return;
                        event.preventDefault();
                        setDesktopWorkspaceActions({
                          path: workspacePath,
                          kind: "main",
                          x: event.clientX,
                          y: event.clientY,
                        });
                      }}
                      className="flex min-w-0 flex-1 items-center gap-1.5 truncate rounded-xs px-2 py-1 text-left text-xs transition-colors hover:bg-(--bg-key)"
                      aria-label={`Open workspace ${workspaceLabel(workspacePath)}`}
                      title={workspacePath}
                    >
                      <Folder
                        size={12}
                        className={`shrink-0 ${isActive ? "text-(--color-accent)" : "text-(--color-text-subtle)"}`}
                        aria-hidden="true"
                      />
                      <span
                        className={`min-w-0 flex-1 truncate font-medium ${isActive ? "text-(--color-text)" : "text-(--color-text-2) group-hover:text-(--color-text)"}`}
                      >
                        {workspaceLabel(workspacePath)}
                      </span>
                      {(sourceIsPending || sourceHasRunningSession) && (
                        <Loader2
                          size={11}
                          className="shrink-0 animate-spin text-(--color-text-muted)"
                          aria-hidden="true"
                        />
                      )}
                    </LongPressButton>
                    {/* I4: Per-workspace action buttons */}
                    <WorkspaceActionButton
                      isMobile={isMobile}
                      onClick={(e) => {
                        e.stopPropagation();
                        void selectWorkspace(workspacePath, { create: true });
                      }}
                      ariaLabel={`New session in ${workspaceLabel(workspacePath)}`}
                      title={`New session in ${workspaceLabel(workspacePath)}`}
                    >
                      <Plus size={11} aria-hidden="true" />
                    </WorkspaceActionButton>
                    <WorkspaceActionButton
                      isMobile={isMobile}
                      onClick={() => void openWorktreeDialog(workspacePath)}
                      ariaLabel={`Create worktree from ${workspaceLabel(workspacePath)}`}
                      title="Create worktree"
                    >
                      <GitBranch size={11} aria-hidden="true" />
                    </WorkspaceActionButton>
                    <WorkspaceActionButton
                      isMobile={isMobile}
                      variant="danger"
                      onClick={() => setRemoveWorkspaceTarget(workspacePath)}
                      ariaLabel={`Hide repository ${workspaceLabel(workspacePath)} from sidebar`}
                      title="Hide repository from sidebar"
                    >
                      <Trash2 size={11} aria-hidden="true" />
                    </WorkspaceActionButton>
                  </div>
                  <Expandable open={isExpanded}>
                    <WorkspaceSessionList
                      workspace={workspacePath}
                      {...codingSessionActions}
                      onSessionSelect={(session) =>
                        handleSessionSelect(session, session.workspace ?? workspacePath)
                      }
                    />
                  </Expandable>
                </div>
              );
            })}
          </div>
        </Expandable>
      </div>
    </div>
  );

  // ── Mobile backdrop ────────────────────────────────────────────────────

  const mobileBackdrop = (
    <AnimatePresence>
      {isMobile && mobileOpen && (
        <motion.div
          key="sidebar-backdrop"
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
  );

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <>
      {mobileBackdrop}

      <motion.aside
        initial={false}
        animate={
          isMobile
            ? {
                x: mobileOpen ? 0 : -280,
                width: "min(272px, calc(100vw - 2rem))",
              }
            : { width: desktopWidth }
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
        style={isMobile ? undefined : { minWidth: desktopWidth }}
      >
        {/* Resize handle — desktop only */}
        {!isMobile && !showIconOnly && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize sidebar"
            title="Drag to resize · double-click to reset"
            className="absolute right-0 top-0 z-20 h-full w-1 cursor-col-resize transition-colors hover:bg-(--color-accent)/40"
            onPointerDown={resizable.startResize}
            onDoubleClick={resizable.resetWidth}
          />
        )}

        {/* Collapsed icon strip — desktop only */}
        {!isMobile && showIconOnly && (
          <div className="flex h-full flex-col items-center gap-1 overflow-hidden p-1">
            <div className="flex w-full shrink-0 flex-col items-center gap-0.5 rounded-[10px] bg-(--bg-sidebar)/80 px-1 pb-2 shadow-sm backdrop-blur-xl">
              <ModeSwitcher mode={mode} isIconOnly isMacOverlay={isMacOverlay} onNavigate={handleNavigateForMode} />
              <SearchTrigger isIconOnly onCommandPalette={onCommandPalette} />
            </div>
            <div className="flex-1" />
            <div className="flex w-full shrink-0 flex-col items-center gap-1 rounded-[10px] bg-(--bg-sidebar)/80 px-1 py-2 shadow-sm backdrop-blur-xl">
              <SidebarFooter isIconOnly onCommandPalette={onCommandPalette} openSettings={openSettings} />
            </div>
          </div>
        )}

        {/* Content sections — desktop gets floating cards, mobile stays flat. */}
        <div
          className={
            !isMobile && showIconOnly
              ? "hidden"
              : !isMobile
                ? "flex h-full flex-col gap-1 overflow-hidden p-1"
                : "flex flex-1 flex-col overflow-hidden"
          }
        >
          {/* Mobile: mode switch at top */}
          {isMobile && (
            <div className="px-3 pt-3"><ModeSwitcher mode={mode} isIconOnly={false} isMacOverlay={isMacOverlay} onNavigate={handleNavigateForMode} /></div>
          )}

          {/* Desktop: mode switch card */}
          {!isMobile && (
            <div className="shrink-0 rounded-[10px] bg-(--bg-sidebar)/80 shadow-sm backdrop-blur-xl">
              <ModeSwitcher mode={mode} isIconOnly={false} isMacOverlay={isMacOverlay} onNavigate={handleNavigateForMode} />
            </div>
          )}

          {/* Search trigger */}
          <div
            className={
              isMobile
                ? "px-3 pt-3"
                : "shrink-0 rounded-[10px] bg-(--bg-sidebar)/80 px-2 py-2 shadow-sm backdrop-blur-xl"
            }
          >
            <SearchTrigger isIconOnly={false} onCommandPalette={onCommandPalette} />
          </div>

          {/* Nav items: New Chat + Scheduler (forge mode only) */}
          {mode === "forge" && (
            <div className="shrink-0 rounded-[10px] bg-(--bg-sidebar)/80 px-2 pb-2 shadow-sm backdrop-blur-xl">
              <nav aria-label="Primary" className="space-y-0.5">
                <SidebarItem
                  Icon={Plus}
                  label="New Chat"
                  kbd="^N"
                  onClick={handleNewChat}
                />
                <SidebarItem
                  Icon={CalendarClock}
                  label="Scheduler"
                  kbd="^S"
                  onClick={() => { toggleScheduler(); onMobileClose?.(); }}
                />
              </nav>
            </div>
          )}

          {/* Main content area — animate mode switch */}
          <div
            className={`flex min-h-0 flex-1 flex-col overflow-hidden${
              !isMobile
                ? " rounded-[10px] bg-(--bg-sidebar)/80 shadow-sm backdrop-blur-xl"
                : ""
            }`}
          >
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={mode}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: prefersReducedMotion ? 0.01 : 0.15 }}
                className="flex min-h-0 flex-1 flex-col"
              >
                {mode === "forge" ? forgeSessionsContent : codingContent}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Footer — plain div, no animation */}
          {!isMobile && (
            <div className="shrink-0 rounded-[10px] bg-(--bg-sidebar)/80 shadow-sm backdrop-blur-xl">
              <SidebarFooter isIconOnly={false} onCommandPalette={onCommandPalette} openSettings={openSettings} />
            </div>
          )}
        </div>

        {/* Mobile footer */}
        {isMobile && (
          <div className="shrink-0 border-t border-(--color-border) bg-(--bg-sidebar) px-3 py-2 pb-safe">
            <SidebarFooter isIconOnly={false} onCommandPalette={onCommandPalette} openSettings={openSettings} />
          </div>
        )}
      </motion.aside>

      <UnifiedSidebarDialogs
        editTarget={editTarget}
        setEditTarget={setEditTarget}
        editTitle={editTitle}
        setEditTitle={setEditTitle}
        submitSessionTitle={submitSessionTitle}
        showProjectModal={showProjectModal}
        setShowProjectModal={setShowProjectModal}
        dialogOpen={dialogOpen}
        setDialogOpen={setDialogOpen}
        closeWorkspaceDialog={closeWorkspaceDialog}
        trustWorkspace={trustWorkspace}
        setTrustWorkspace={setTrustWorkspace}
        nativeFolderPickerEnabled={nativeFolderPickerEnabled}
        isTauriMobile={isTauriMobile}
        selectedWorkspace={selectedWorkspace}
        error={error}
        loading={loading}
        browserPath={browserPath}
        parentPath={parentPath}
        dirs={dirs}
        loadBrowser={loadBrowser}
        openSelectedFolder={openSelectedFolder}
        openWorkspaceDialog={openWorkspaceDialog}
        confirmTrustedWorkspace={confirmTrustedWorkspace}
        mobileWorkspaceActions={mobileWorkspaceActions}
        setMobileWorkspaceActions={setMobileWorkspaceActions}
        selectWorkspace={selectWorkspace}
        openWorktreeDialog={openWorktreeDialog}
        setRemoveWorkspaceTarget={setRemoveWorkspaceTarget}
        mobileSessionActions={mobileSessionActions}
        setMobileSessionActions={setMobileSessionActions}
        handleSessionEdit={handleSessionEdit}
        setPendingDeleteId={setPendingDeleteId}
        desktopWorkspaceActions={desktopWorkspaceActions}
        setDesktopWorkspaceActions={setDesktopWorkspaceActions}
        handleRemoveWorktree={handleRemoveWorktree}
        desktopSessionActions={desktopSessionActions}
        setDesktopSessionActions={setDesktopSessionActions}
        removeWorkspaceTarget={removeWorkspaceTarget}
        confirmRemoveWorkspace={confirmRemoveWorkspace}
        worktreeTarget={worktreeTarget}
        setWorktreeTarget={setWorktreeTarget}
        submitWorktree={submitWorktree}
        worktreeName={worktreeName}
        setWorktreeName={setWorktreeName}
        worktreeBranch={worktreeBranch}
        setWorktreeBranch={setWorktreeBranch}
        worktreeLoading={worktreeLoading}
      />
    </>
  );
}
