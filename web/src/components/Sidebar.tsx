import {
  useState,
  useEffect,
  useCallback,
  useRef,
  type TouchEvent,
} from "react";
import { useNavigate } from "@tanstack/react-router";
import { motion, AnimatePresence } from "framer-motion";
import { useIsMobile } from "@/hooks/use-mobile";
import { useModalFocus } from "@/hooks/useModalFocus";
import { useMotionPreset, useListEnterIndex } from "@/lib/motion";

import {
  Blocks,
  CalendarClock,
  Plus,
  RefreshCw,
} from "lucide-react";
import { ModeSwitchTabs } from "@/components/ModeSwitchTabs";
import { isToday, isYesterday } from "date-fns";
import {
  useTeamSessionsQuery,
  useDeleteTeamSessionMutation,
  useDuplicateTeamSessionMutation,
  useUpdateTeamSessionTitleMutation,
  useSessionFoldersQuery,
  useCreateSessionFolderMutation,
  useLoadMoreFolderSessionsMutation,
  useSetSessionFolderMutation,
  queryKeys,
} from "@/queries";
import { Skeleton } from "./ui/skeleton";
import { SidebarItem } from "@/components/ui/sidebar-item";
import { usePlatform } from "@/hooks/use-platform";
import { useUIStore } from "@/stores/useUIStore";
import { usePinnedSessions } from "@/stores/usePinnedSessions";
import {
  SidebarShell,
  SidebarCard,
  SidebarNavGroup,
  SidebarShellDivider,
  SidebarSearchTrigger,
  SidebarFooter,
  SidebarModeSlot,
} from "@/components/shell/SidebarShell";
import { SessionRow } from "@/components/shell/SessionRow";
import {
  SessionContextMenu,
  SessionActionsDialog,
  type SessionMenuAnchor,
} from "@/components/shell/SessionContextMenu";
import { EditSessionTitleDialog } from "@/components/shell/EditSessionTitleDialog";
import { MobileDrawerBackdrop } from "@/components/shell/MobileDrawerBackdrop";
import { SessionFolders } from "@/components/shell/SessionFolders";
import { CollapsibleSection } from "@/components/shell/CollapsibleSection";
import { MoveToFolderDialog } from "@/components/shell/MoveToFolderDialog";
import {
  clearSessionDropTarget,
  clearSessionDragPayload,
  isSessionDrag,
  markSessionDropHandled,
  readSessionDropTarget,
  readSessionDropTargetFromElement,
  readSessionDragPayload,
  setSessionDropTarget,
  setSessionDragPayload,
  wasSessionDropHandled,
} from "@/components/shell/session-drag";
import { resolveTeamSession } from "@/api/client";
import { prependSession } from "@/stores/cache-invalidation-bridge";
import { useQueryClient } from "@tanstack/react-query";
import { useToastStore } from "@/stores/useToastStore";
import { useTeamStore } from "@/stores/useTeamStore";
import type { SessionFolder, SessionResponse } from "@/api/types";
import { cn } from "@/lib/utils";
import { STORAGE_KEYS } from "@/lib/storage-keys";
import { formatShortcutLabel, isPrimaryShortcut } from "@/lib/keyboard-shortcuts";

interface DateGroup {
  label: string;
  sessions: SessionResponse[];
}

function SessionListSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="space-y-1 px-1 py-2" aria-label="Loading sessions">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="rounded-md px-2.5 py-2">
          <Skeleton className="h-3 w-[min(11rem,70%)]" />
          <Skeleton className="mt-2 h-2.5 w-20" />
        </div>
      ))}
    </div>
  );
}

function groupByDate(sessions: SessionResponse[]): DateGroup[] {
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

  const groups: DateGroup[] = [];
  if (today.length) groups.push({ label: "Today", sessions: today });
  if (yesterday.length)
    groups.push({ label: "Yesterday", sessions: yesterday });
  if (older.length) groups.push({ label: "Older", sessions: older });
  return groups;
}

function loadRecentCollapsed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEYS.work.recentCollapsed) === "true";
  } catch {
    return false;
  }
}

interface SidebarProps {
  currentSessionId?: string;
  onCommandPalette?: () => void;
  onNewChat?: () => void;
  /** Current mode — 'work' or 'coding' */
  mode?: 'work' | 'coding';
  /** Whether the mobile/responsive overlay drawer is open. */
  mobileOpen?: boolean;
  /** Called when the drawer should close (backdrop tap, Escape, navigation). */
  onMobileClose?: () => void;
  /** Render the navigation as a modal drawer at constrained desktop widths. */
  drawerMode?: boolean;
}

export function Sidebar({
  currentSessionId,
  onCommandPalette,
  onNewChat,
  mode = 'work',
  mobileOpen = false,
  onMobileClose,
  drawerMode = false,
}: SidebarProps) {
  const isMobile = useIsMobile();
  const isDrawer = isMobile || drawerMode;
  const { isTauri, os, isMacOverlay } = usePlatform();
  const isTauriMobile = isTauri && (os === "ios" || os === "android");
  const mobileLongPressActions = isMobile && isTauriMobile && mobileOpen;
  const preset = useMotionPreset();
  useModalFocus(isDrawer && mobileOpen, onMobileClose);
  const navigate = useNavigate();
  const toggleScheduler = useUIStore((s) => s.toggleScheduler);
  const togglePlugins = useUIStore((s) => s.toggleWorkbenchTool);
  // Server-filtered to work — coding sessions live in their own sidebar.
  const sessions = useTeamSessionsQuery("work");
  const folders = useSessionFoldersQuery("work");
  const deleteSession = useDeleteTeamSessionMutation();
  const duplicateSession = useDuplicateTeamSessionMutation();
  const updateSessionTitle = useUpdateTeamSessionTitleMutation();
  const setSessionFolder = useSetSessionFolderMutation("work");
  const createFolder = useCreateSessionFolderMutation("work");
  const loadMoreFolderSessions = useLoadMoreFolderSessionsMutation("work");
  const queryClient = useQueryClient();
  const pushToast = useToastStore((s) => s.push);
  const sessionListRef = useRef<HTMLDivElement>(null);
  const loadMoreRef = useRef<HTMLDivElement>(null);

  // Flatten pages into a single list of sessions
  const normalSessions = sessions.data?.pages.flatMap((p) => p.data) ?? [];

  // Folders own their sessions (fetched whole, not paginated), so the date
  // groups below show only what is still unfiled. A folder's sessions are
  // matched by id as well as by folder_id: the folders query is the
  // authority right after a drag, before the paged list refetches.
  const folderList = folders.data?.folders ?? [];
  const folderSessions = folderList.flatMap((folder) => folder.sessions);
  const folderedIds = new Set(folderSessions.map((s) => s.id));
  const sessionById = new Map<string, SessionResponse>();
  for (const session of [...normalSessions, ...folderSessions]) {
    sessionById.set(session.id, session);
  }
  const unfiledSessions = normalSessions.filter(
    (s) => !s.folder_id && !folderedIds.has(s.id),
  );

  // Pinned sessions (persisted in usePinnedSessions) surface in a "Pinned"
  // section above the date groups; only ids present in the already-loaded
  // pages can render — a pinned session older than the loaded pages simply
  // doesn't appear until it loads into view.
  const pinnedIds = usePinnedSessions((s) => s.pinnedIds);
  const togglePin = usePinnedSessions((s) => s.togglePin);
  const pinnedIdSet = new Set(pinnedIds);
  const pinnedSessions = pinnedIds
    .map((id) => sessionById.get(id))
    .filter(
      (session): session is SessionResponse =>
        session !== undefined && !session.folder_id,
    );
  const unpinnedSessions = unfiledSessions.filter((s) => !pinnedIdSet.has(s.id));
  const sessionEnterIndex = useListEnterIndex([
    ...normalSessions.map((s) => s.id),
    ...folderSessions.map((s) => s.id),
  ]);

  // Collapse state is shared by all three mode sidebars and owned by
  // useUIStore (persisted); AppShell owns the toggle button + Ctrl+B.
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const sidebarWidth = useUIStore((s) => s.sidebarWidth);

  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<SessionResponse | null>(null);
  const [mobileSessionActions, setMobileSessionActions] =
    useState<SessionResponse | null>(null);
  const [desktopSessionActions, setDesktopSessionActions] =
    useState<SessionMenuAnchor | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [moveTarget, setMoveTarget] = useState<SessionResponse | null>(null);
  const [unfileDropActive, setUnfileDropActive] = useState(false);
  const [recentCollapsed, setRecentCollapsed] = useState(loadRecentCollapsed);
  const [pullDistance, setPullDistance] = useState(0);
  const pullStartYRef = useRef<number | null>(null);

  const refetchSessions = sessions.refetch;
  const refetchFolders = folders.refetch;
  const refreshSidebar = useCallback(
    () => Promise.all([refetchSessions(), refetchFolders()]),
    [refetchFolders, refetchSessions],
  );
  const canPullRefresh = isMobile && mobileOpen;

  useEffect(() => {
    try {
      localStorage.setItem(
        STORAGE_KEYS.work.recentCollapsed,
        String(recentCollapsed),
      );
    } catch {
      // Ignore storage failures; the section still works for this session.
    }
  }, [recentCollapsed]);

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
        setPullDistance(0);
        return;
      }
      setPullDistance(Math.min(72, delta * 0.5));
    },
    [canPullRefresh],
  );

  const handleSessionListTouchEnd = useCallback(() => {
    if (canPullRefresh && pullDistance >= 54) {
      void refreshSidebar();
    }
    pullStartYRef.current = null;
    setPullDistance(0);
  }, [canPullRefresh, pullDistance, refreshSidebar]);

  // Ctrl+R: refresh sessions (data refresh — a sidebar concern, not shell).
  // Ctrl+B (collapse) is owned once by AppShell; Ctrl+M (wiki) / Ctrl+S
  // (scheduler) live in TeamChatView — those panels moved out of the sidebar
  // per the topbar-redesign wireframe and their open-state is in useUIStore.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!isPrimaryShortcut(e)) return;
      if (e.key === "r") {
        e.preventDefault();
        void refreshSidebar();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [refreshSidebar]);

  const { hasNextPage, isFetchingNextPage, fetchNextPage } = sessions;

  // Intersection observer — load next page when sentinel scrolls into view.
  useEffect(() => {
    const sentinel = loadMoreRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      {
        root: sessionListRef.current,
        // Start fetching before the user reaches the final visible rows so
        // fast wheel/trackpad scrolling does not expose a loading gap.
        rootMargin: "0px 0px 320px 0px",
        threshold: 0,
      },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, recentCollapsed]);

  const handleDelete = (session: SessionResponse) => {
    setPendingDeleteId(session.id);
  };

  const handleEdit = (session: SessionResponse) => {
    setEditTarget(session);
    setEditTitle(session.title || "");
  };

  const handleDuplicate = (session: SessionResponse) => {
    duplicateSession.mutate(session.id, {
      onSuccess: (copy) => {
        pushToast({
          tone: "success",
          title: "Session duplicated",
          description: `Opened ${copy.title || "the copied session"}.`,
        });
        handleSelect(copy.id);
      },
      onError: (err) =>
        pushToast({
          tone: "error",
          title: "Could not duplicate session",
          description: err instanceof Error ? err.message : "Please try again.",
        }),
    });
  };

  const confirmDelete = () => {
    if (!pendingDeleteId) return;
    const target = sessionById.get(pendingDeleteId);
    if (!target) return;
    const fallbackSession =
      target.id === currentSessionId
        ? normalSessions.find((session) => session.id !== target.id)
        : null;
    deleteSession.mutate(target.id);
    if (target.id === currentSessionId) {
      // Reset the team store so the deleted session's UI state is cleared
      // before navigating away.  Without this, the store keeps the stale
      // session id and the chat view continues to render the deleted session.
      useTeamStore.getState().beginResolvedSession(null, { mode });
      if (fallbackSession) {
        useTeamStore.getState().beginResolvedSession(fallbackSession.id, { mode });
        navigate({
          to: "/$sessionId",
          params: { sessionId: fallbackSession.id },
          replace: true,
        });
      } else {
        // Navigate to "/" — TeamLayoutBase will auto-resolve a new empty session.
        navigate({ to: "/", replace: true });
      }
    }
    setPendingDeleteId(null);
  };

  const handleSelect = (id: string) => {
    navigate({ to: "/$sessionId", params: { sessionId: id } });
    onMobileClose?.();
  };

  // Session-row side-chat icon: open the session (no-op when already active)
  // and ask TeamChatView to open its side chat panel.
  const handleSideChat = (id: string) => {
    useUIStore.getState().requestSideChat(id);
    handleSelect(id);
  };

  const handleNewChat = () => {
    if (onNewChat) {
      onNewChat();
    } else {
      navigate({ to: "/" });
    }
    onMobileClose?.();
  };

  // Folder "+" button: create the session already filed in the folder rather
  // than creating it loose and moving it, so it never flashes in Recent.
  const handleNewChatInFolder = async (folder: SessionFolder) => {
    try {
      const session = await resolveTeamSession({
        mode: "work",
        workspace: null,
        folder_id: folder.id,
        create: true,
      });
      prependSession(queryClient, session);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.team.sessionFolders("work"),
      });
      navigate({ to: "/$sessionId", params: { sessionId: session.id } });
      onMobileClose?.();
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Could not start a chat in this folder",
        description: err instanceof Error ? err.message : "Please try again.",
      });
    }
  };

  const moveSessionToFolder = (
    sessionId: string,
    folderId: string | null,
    onSuccess?: () => void,
  ) => {
    const session = sessionById.get(sessionId);
    if (session && (session.folder_id ?? null) === folderId) {
      onSuccess?.();
      return;
    }
    setSessionFolder.mutate(
      { sessionId, folderId, session },
      {
        onSuccess,
        onError: (err) =>
          pushToast({
            tone: "error",
            title: "Could not move the chat",
            description: err instanceof Error ? err.message : "Please try again.",
          }),
      },
    );
  };

  const renderSessionRow = (session: SessionResponse) => (
    <SessionRow
      key={session.id}
      session={session}
      isActive={session.id === currentSessionId}
      density={isDrawer ? 'comfortable' : 'dense'}
      enterIndex={sessionEnterIndex(session.id)}
      onSelect={(s) => handleSelect(s.id)}
      onOpenSideChat={(s) => handleSideChat(s.id)}
      onDelete={handleDelete}
      pendingDelete={pendingDeleteId === session.id}
      onCancelDelete={() => setPendingDeleteId(null)}
      onConfirmDelete={confirmDelete}
      onEdit={handleEdit}
      mobileLongPressActions={mobileLongPressActions}
      onLongPress={setMobileSessionActions}
      // Touch drags don't emit HTML5 drag events, so mobile files sessions
      // through the actions sheet's "Move to folder…" instead.
      draggable={!isMobile}
      onDragStart={(s, event) => setSessionDragPayload(event, s.id)}
      onDragEnd={(s, event) => {
        let fallbackTarget = readSessionDropTarget();
        // WKWebView can finish a native drag without dispatching React's
        // `drop`. Resolve the element under the release point so a preceding
        // `dragleave` cannot erase an otherwise valid destination.
        if (event.clientX !== 0 || event.clientY !== 0) {
          const element = document.elementFromPoint(event.clientX, event.clientY);
          fallbackTarget = readSessionDropTargetFromElement(element);
        }
        if (!wasSessionDropHandled() && fallbackTarget !== undefined) {
          moveSessionToFolder(s.id, fallbackTarget);
        }
        clearSessionDragPayload();
        setUnfileDropActive(false);
      }}
      onContextActions={(session, event) => {
        setDesktopSessionActions({
          session,
          x: event.clientX,
          y: event.clientY,
        });
      }}
    />
  );

  const ungroupedList = (
    <>
      {sessions.isLoading && <SessionListSkeleton />}
      {sessions.isError && (
        <p className="px-3 py-4 text-center text-xs text-(--color-error)">Failed to load sessions</p>
      )}
      {sessions.isSuccess &&
        pinnedSessions.length === 0 &&
        unpinnedSessions.length === 0 && (
          <p className="px-3 py-4 text-center text-xs text-(--color-text-subtle)">
            No chats outside folders
          </p>
        )}
      {sessions.isSuccess && (normalSessions.length > 0 || hasNextPage) && (
        <div className="space-y-0.5">
          {pinnedSessions.length > 0 && (
            <div>
              <p
                className={
                  isMobile
                    ? "px-2 pb-0.5 pt-2 text-xs text-(--color-text-subtle) first:pt-1"
                    : "px-3 pb-0.5 pt-2 text-[10px] font-medium text-(--color-text-subtle) first:pt-1"
                }
              >
                Pinned
              </p>
              <div className={isDrawer ? undefined : 'pl-1.5'}>
                {pinnedSessions.map(renderSessionRow)}
              </div>
            </div>
          )}
          {groupByDate(unpinnedSessions).map(({ label, sessions: group }) => (
            <div key={label}>
              <p
                className={
                  isMobile
                    ? "px-2 pb-0.5 pt-2 text-xs text-(--color-text-subtle) first:pt-1"
                    : "px-3 pb-0.5 pt-2 text-[10px] font-medium text-(--color-text-subtle) first:pt-1"
                }
              >
                {label}
              </p>
              <div className={isDrawer ? undefined : 'pl-1.5'}>
                {group.map(renderSessionRow)}
              </div>
            </div>
          ))}
          <div ref={loadMoreRef} className="h-1" aria-hidden />
          {isFetchingNextPage && <SessionListSkeleton count={3} />}
        </div>
      )}
    </>
  );

  const sessionSections = (
      <div
        ref={sessionListRef}
        className="relative min-h-0 flex-1 overflow-y-auto pb-1.5"
        onTouchStart={handleSessionListTouchStart}
        onTouchMove={handleSessionListTouchMove}
        onTouchEnd={handleSessionListTouchEnd}
        onTouchCancel={handleSessionListTouchEnd}
      >
        {canPullRefresh && (
          <div
            className="pointer-events-none sticky top-0 z-(--z-panel) flex justify-center overflow-hidden transition-[height] duration-(--motion-fast)"
            style={{ height: pullDistance }}
            aria-hidden
          >
            <div className="mt-2 inline-flex h-8 items-center gap-2 rounded-full border border-(--color-border) bg-(--bg-card) px-3 text-xs text-(--color-text-muted) shadow-sm">
              <RefreshCw size={12} className={pullDistance >= 54 || sessions.isFetching ? 'animate-spin' : ''} />
              {pullDistance >= 54 ? 'Release to refresh' : 'Pull to refresh'}
            </div>
          </div>
        )}

        {/* Folders and Recent share one scroll track and one horizontal grid. */}
        <div className={isDrawer ? 'px-1.5 pt-1' : 'px-1 pt-1'}>
          <SessionFolders
            folders={folderList}
            isLoading={folders.isLoading}
            isError={folders.isError}
            isMobile={isMobile}
            renderSession={renderSessionRow}
            onNewChatInFolder={(folder) => void handleNewChatInFolder(folder)}
            onDropSession={moveSessionToFolder}
            onLoadMore={(folder) => {
              if (!folder.next_cursor) return;
              loadMoreFolderSessions.mutate(
                { folderId: folder.id, before: folder.next_cursor },
                {
                  onError: (err) =>
                    pushToast({
                      tone: "error",
                      title: "Could not load older chats",
                      description:
                        err instanceof Error ? err.message : "Please try again.",
                    }),
                },
              );
            }}
            loadingFolderId={
              loadMoreFolderSessions.isPending
                ? loadMoreFolderSessions.variables?.folderId
                : null
            }
            onRetry={() => void folders.refetch()}
          />
        </div>

        {/* Dropping a row here takes it out of its folder — the mirror of
            dropping it on a folder header. */}
        <div
          data-session-unfile-drop-zone
          className={cn(
            'rounded-md transition-colors',
            isDrawer && 'px-1.5',
            unfileDropActive && 'bg-(--bg-key)/40 ring-1 ring-(--color-accent)',
          )}
          onDragEnter={(event) => {
            if (!isSessionDrag(event)) return;
            event.preventDefault();
            setSessionDropTarget(null);
            setUnfileDropActive(true);
          }}
          onDragOver={(event) => {
            if (!isSessionDrag(event)) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            setSessionDropTarget(null);
          }}
          onDragLeave={(event) => {
            if (event.currentTarget.contains(event.relatedTarget as Node)) return;
            clearSessionDropTarget(null);
            setUnfileDropActive(false);
          }}
          onDrop={(event) => {
            if (!isSessionDrag(event)) return;
            event.preventDefault();
            markSessionDropHandled();
            setUnfileDropActive(false);
            const sessionId = readSessionDragPayload(event);
            if (sessionId) moveSessionToFolder(sessionId, null);
          }}
        >
          <CollapsibleSection
            label="Recent"
            collapsed={recentCollapsed}
            onToggle={() => setRecentCollapsed((value) => !value)}
            size={isDrawer ? 'large' : 'default'}
            className={cn(
              'px-2',
              isDrawer ? 'pb-1 pt-2' : 'pb-0.5 pt-1.5',
            )}
            rightSlot={(
              <button
                type="button"
                onClick={() => void refreshSidebar()}
                className={cn(
                  'flex shrink-0 items-center justify-center rounded text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)',
                  isDrawer ? 'h-7 w-7' : 'h-5 w-5',
                )}
                aria-label="Refresh folders and recent chats"
                title={`Refresh sidebar (${formatShortcutLabel("Ctrl+R")})`}
              >
                <RefreshCw
                  size={isDrawer ? 15 : 12}
                  className={sessions.isFetching || folders.isFetching ? "animate-spin" : ""}
                  aria-hidden="true"
                />
              </button>
            )}
          />
          {!recentCollapsed && (
            <>
              {unfileDropActive && (
                <p className="px-3 py-2 text-center text-xs text-(--color-text-muted)">
                  Drop to remove from folder
                </p>
              )}
              {ungroupedList}
            </>
          )}
        </div>
      </div>
  );

  // Desktop: one floating card with internal dividers (work style).
  const desktopShell = (
    <SidebarShell
      collapsed={collapsed}
    >
      <SidebarCard className="h-full">
        {/* ─── Top section: search + nav ─── */}
        <div className="shrink-0">
          <div className={`px-1.5 ${isMacOverlay ? 'pt-10' : 'pt-1.5'}`}>
            <SidebarModeSlot />
          </div>
          {onCommandPalette && (
            <div className="px-1.5 pt-2">
              <SidebarSearchTrigger onClick={onCommandPalette} compact />
            </div>
          )}
          <SidebarNavGroup ariaLabel="Primary" compact className="px-1.5 pb-1 pt-1">
            <SidebarItem
              Icon={Plus}
              label="New Chat"
              kbd="^N"
              compact
              onClick={handleNewChat}
            />
            <SidebarItem
              Icon={CalendarClock}
              label="Scheduler"
              kbd="^S"
              compact
              onClick={toggleScheduler}
            />
            <SidebarItem
              Icon={Blocks}
              label="Plugins"
              kbd="^K"
              compact
              onClick={() => togglePlugins("plugins")}
            />
          </SidebarNavGroup>
        </div>

        {/* ─── Sessions section ─── */}
        <AnimatePresence>
          <motion.div
            key="sessions-panel"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex min-h-0 flex-1 flex-col overflow-hidden"
          >
            {sessionSections}
          </motion.div>
        </AnimatePresence>

        <SidebarShellDivider />

        {/* ─── Footer section ─── */}
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
      aria-label="Session navigation"
      aria-modal={mobileOpen ? true : undefined}
      data-modal-focus={mobileOpen ? 'true' : undefined}
      {...(!mobileOpen ? { inert: true } : {})}
      className={cn(
        "mobile-safe-top fixed bottom-0 left-0 z-(--z-overlay) flex w-[min(272px,calc(100vw-2rem))] shrink-0 flex-col overflow-hidden bg-(--bg-sidebar) shadow-xl",
        !mobileOpen && "pointer-events-none",
      )}
    >
      {/* Search trigger */}
      {onCommandPalette && (
        <div className="px-2.5 pt-2">
          <SidebarSearchTrigger
            onClick={() => {
              onCommandPalette();
              onMobileClose?.();
            }}
          />
        </div>
      )}

      {/* Mode switch */}
      <div className="px-2.5 pt-1.5">
        <ModeSwitchTabs active={mode} onNavigate={onMobileClose} />
      </div>

      {/* Nav */}
      <SidebarNavGroup ariaLabel="Primary" className="px-1.5 pb-1.5 pt-1.5">
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
        <SidebarItem
          Icon={Blocks}
          label="Plugins"
          kbd="^K"
          onClick={() => { togglePlugins("plugins"); onMobileClose?.(); }}
        />
      </SidebarNavGroup>

      {/* Sessions */}
      <AnimatePresence>
        <motion.div
          key="mobile-sessions"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          {sessionSections}
        </motion.div>
      </AnimatePresence>

      {/* Footer */}
      <SidebarFooter
        onCommandPalette={onCommandPalette}
        onAction={onMobileClose}
      />
    </motion.aside>
  );

  return (
    <>
      <AnimatePresence>
        {isDrawer && mobileOpen && (
          <MobileDrawerBackdrop
            onClose={() => onMobileClose?.()}
            closeLabel="Close session navigation"
            desktopVisible={drawerMode}
          />
        )}
      </AnimatePresence>

      {isDrawer ? mobileDrawer : desktopShell}

      <SessionContextMenu
        anchor={desktopSessionActions}
        onClose={() => setDesktopSessionActions(null)}
        onEdit={handleEdit}
        onDuplicate={handleDuplicate}
        onDelete={handleDelete}
        pinned={
          desktopSessionActions
            ? pinnedIdSet.has(desktopSessionActions.session.id)
            : false
        }
        onTogglePin={() => {
          if (desktopSessionActions) togglePin(desktopSessionActions.session.id);
        }}
        onMoveToFolder={setMoveTarget}
      />

      <SessionActionsDialog
        session={mobileSessionActions}
        onClose={() => setMobileSessionActions(null)}
        onEdit={handleEdit}
        onDuplicate={handleDuplicate}
        onDelete={(session) => setPendingDeleteId(session.id)}
        pinned={
          mobileSessionActions ? pinnedIdSet.has(mobileSessionActions.id) : false
        }
        onTogglePin={() => {
          if (mobileSessionActions) togglePin(mobileSessionActions.id);
        }}
        onMoveToFolder={setMoveTarget}
      />

      <MoveToFolderDialog
        key={moveTarget?.id ?? "closed"}
        session={moveTarget}
        folders={folderList}
        onClose={() => setMoveTarget(null)}
        onSelect={(folderId) => {
          if (!moveTarget) return;
          moveSessionToFolder(moveTarget.id, folderId, () => setMoveTarget(null));
        }}
        onCreateAndSelect={(name) => {
          const target = moveTarget;
          if (!target) return;
          createFolder.mutate(name, {
            onSuccess: (folder) => {
              moveSessionToFolder(target.id, folder.id, () => setMoveTarget(null));
            },
            onError: (err) =>
              pushToast({
                tone: "error",
                title: "Could not create the folder",
                description:
                  err instanceof Error ? err.message : "Please try again.",
              }),
          });
        }}
        isPending={setSessionFolder.isPending || createFolder.isPending}
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
    </>
  );
}
