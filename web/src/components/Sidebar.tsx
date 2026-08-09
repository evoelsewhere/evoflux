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
  Search,
} from "lucide-react";
import { ModeSwitchTabs } from "@/components/ModeSwitchTabs";
import { isToday, isYesterday } from "date-fns";
import {
  useTeamSessionsQuery,
  useDeleteTeamSessionMutation,
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
  SidebarShellDivider,
  SidebarSearchTrigger,
  SidebarFooter,
  SidebarModeSlot,
  SidebarModeRailSlot,
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
import { MoveToFolderDialog } from "@/components/shell/MoveToFolderDialog";
import {
  isSessionDrag,
  readSessionDragPayload,
  setSessionDragPayload,
} from "@/components/shell/session-drag";
import { resolveTeamSession } from "@/api/client";
import { prependSession } from "@/stores/cache-invalidation-bridge";
import { useQueryClient } from "@tanstack/react-query";
import { useToastStore } from "@/stores/useToastStore";
import { useTeamStore } from "@/stores/useTeamStore";
import type { SessionFolder, SessionResponse } from "@/api/types";
import { cn } from "@/lib/utils";

interface DateGroup {
  label: string;
  sessions: SessionResponse[];
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

interface SidebarProps {
  currentSessionId?: string;
  onCommandPalette?: () => void;
  onNewChat?: () => void;
  /** Current mode — 'work' or 'coding' */
  mode?: 'work' | 'coding';
  /** Mobile only: whether the overlay drawer is open */
  mobileOpen?: boolean;
  /** Mobile only: called when the drawer should close (backdrop tap, session select) */
  onMobileClose?: () => void;
}

export function Sidebar({
  currentSessionId,
  onCommandPalette,
  onNewChat,
  mode = 'work',
  mobileOpen = false,
  onMobileClose,
}: SidebarProps) {
  const isMobile = useIsMobile();
  const { isTauri, os, isMacOverlay } = usePlatform();
  const isTauriMobile = isTauri && (os === "ios" || os === "android");
  const mobileLongPressActions = isMobile && isTauriMobile && mobileOpen;
  const preset = useMotionPreset();
  useModalFocus(isMobile && mobileOpen, onMobileClose);
  const navigate = useNavigate();
  const toggleScheduler = useUIStore((s) => s.toggleScheduler);
  const togglePlugins = useUIStore((s) => s.toggleWorkbenchTool);
  // Server-filtered to work — coding sessions live in their own sidebar.
  const sessions = useTeamSessionsQuery("work");
  const folders = useSessionFoldersQuery("work");
  const deleteSession = useDeleteTeamSessionMutation();
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

  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<SessionResponse | null>(null);
  const [mobileSessionActions, setMobileSessionActions] =
    useState<SessionResponse | null>(null);
  const [desktopSessionActions, setDesktopSessionActions] =
    useState<SessionMenuAnchor | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [moveTarget, setMoveTarget] = useState<SessionResponse | null>(null);
  const [unfileDropActive, setUnfileDropActive] = useState(false);
  const [pullDistance, setPullDistance] = useState(0);
  const pullStartYRef = useRef<number | null>(null);

  const refetchSessions = sessions.refetch;
  const refetchFolders = folders.refetch;
  const refreshSidebar = useCallback(
    () => Promise.all([refetchSessions(), refetchFolders()]),
    [refetchFolders, refetchSessions],
  );
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
      if (!e.ctrlKey || e.metaKey) return;
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
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const handleDelete = (session: SessionResponse) => {
    setPendingDeleteId(session.id);
  };

  const handleEdit = (session: SessionResponse) => {
    setEditTarget(session);
    setEditTitle(session.title || "");
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
      onDragEnd={() => setUnfileDropActive(false)}
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
                    : "px-3 pb-1 pt-3 text-xs font-medium text-(--color-text-subtle) first:pt-1.5"
                }
              >
                Pinned
              </p>
              {pinnedSessions.map(renderSessionRow)}
            </div>
          )}
          {groupByDate(unpinnedSessions).map(({ label, sessions: group }) => (
            <div key={label}>
              <p
                className={
                  isMobile
                    ? "px-2 pb-0.5 pt-2 text-xs text-(--color-text-subtle) first:pt-1"
                    : "px-3 pb-1 pt-3 text-xs font-medium text-(--color-text-subtle) first:pt-1.5"
                }
              >
                {label}
              </p>
              {group.map(renderSessionRow)}
            </div>
          ))}
          <div ref={loadMoreRef} className="h-1" aria-hidden />
          {isFetchingNextPage && <SessionListSkeleton count={3} />}
        </div>
      )}
    </>
  );

  const sessionList = (
    <>
      <div className="mx-1.5 h-px bg-(--color-border)" aria-hidden="true" />
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

      {/* Dropping a row here takes it out of its folder — the mirror of
          dropping it on a folder header. */}
      <div
        className={cn(
          "rounded-md transition-colors",
          unfileDropActive && "bg-(--bg-key)/40 ring-1 ring-(--color-accent)",
        )}
        onDragEnter={(event) => {
          if (!isSessionDrag(event)) return;
          event.preventDefault();
          setUnfileDropActive(true);
        }}
        onDragOver={(event) => {
          if (!isSessionDrag(event)) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
        }}
        onDragLeave={(event) => {
          if (event.currentTarget.contains(event.relatedTarget as Node)) return;
          setUnfileDropActive(false);
        }}
        onDrop={(event) => {
          if (!isSessionDrag(event)) return;
          event.preventDefault();
          setUnfileDropActive(false);
          const sessionId = readSessionDragPayload(event);
          if (sessionId) moveSessionToFolder(sessionId, null);
        }}
      >
        <div className="mx-1.5 mt-2 h-px bg-(--color-border)" aria-hidden="true" />
        <div className="flex items-center justify-between px-2.5 pb-2 pt-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
            Recent
          </span>
          <button
            type="button"
            onClick={() => void refreshSidebar()}
            className="rounded-md p-1.5 text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-muted)"
            aria-label="Refresh folders and recent chats"
            title="Refresh sidebar (Ctrl+R)"
          >
            <RefreshCw
              size={15}
              className={sessions.isFetching || folders.isFetching ? "animate-spin" : ""}
            />
          </button>
        </div>
        {unfileDropActive && (
          <p className="px-3 py-2 text-center text-xs text-(--color-text-muted)">
            Drop to remove from folder
          </p>
        )}
        {ungroupedList}
      </div>
    </>
  );

  // Collapsed desktop rail: mode switch + nav icons + first-8-sessions dots.
  const rail = (
    <SidebarCard className="h-full">
      <div className="shrink-0 flex flex-col items-center px-1 py-2">
        <SidebarModeRailSlot
          className={`pb-1 ${isMacOverlay ? 'pt-10' : ''}`}
        />
        <nav
          aria-label="Primary"
          className="space-y-0.5 flex flex-col items-center gap-0.5"
        >
          {onCommandPalette && (
            <SidebarItem
              Icon={Search}
              label="Commands"
              kbd="^P"
              collapsed
              onClick={onCommandPalette}
            />
          )}
          <SidebarItem
            Icon={Plus}
            label="New Chat"
            kbd="^N"
            collapsed
            onClick={handleNewChat}
          />
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
            collapsed
            onClick={() => togglePlugins("plugins")}
          />
        </nav>
      </div>

      <SidebarShellDivider className="mx-2" />

      <div className="flex flex-1 flex-col items-center gap-1 overflow-y-auto py-2">
        {sessions.isSuccess &&
          normalSessions.slice(0, 8).map((session) => {
            const isActive = session.id === currentSessionId;
            const title = session.title || "Untitled";
            return (
              <button
                key={session.id}
                type="button"
                onClick={() => handleSelect(session.id)}
                title={title}
                aria-label={title}
                aria-current={isActive ? "page" : undefined}
                className={`flex h-8 w-8 items-center justify-center rounded-md transition-colors ${
                  isActive
                    ? "bg-(--bg-key) text-(--color-accent)"
                    : "text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text-2)"
                }`}
              >
                <div className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
              </button>
            );
          })}
      </div>

      <SidebarShellDivider className="mx-2" />

      <SidebarFooter collapsed onCommandPalette={onCommandPalette} />
    </SidebarCard>
  );

  // Desktop: one floating card with internal dividers (work style).
  const desktopShell = (
    <SidebarShell
      collapsed={collapsed}
      rail={rail}
    >
      <SidebarCard className="h-full">
        {/* ─── Top section: search + nav ─── */}
        <div className="shrink-0">
          <div className={`px-1.5 ${isMacOverlay ? 'pt-10' : 'pt-1.5'}`}>
            <SidebarModeSlot />
          </div>
          {onCommandPalette && (
            <div className="px-2.5 pt-2.5">
              <SidebarSearchTrigger onClick={onCommandPalette} />
            </div>
          )}
          <nav aria-label="Primary" className="space-y-0.5 px-1.5 pb-1.5 pt-2">
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
              onClick={toggleScheduler}
            />
            <SidebarItem
              Icon={Blocks}
              label="Plugins"
              onClick={() => togglePlugins("plugins")}
            />
          </nav>
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
            <div
              ref={sessionListRef}
              className="relative flex-1 overflow-y-auto px-1.5 pb-1.5"
              onTouchStart={handleSessionListTouchStart}
              onTouchMove={handleSessionListTouchMove}
              onTouchEnd={handleSessionListTouchEnd}
              onTouchCancel={handleSessionListTouchEnd}
            >
              {sessionList}
            </div>
          </motion.div>
        </AnimatePresence>

        <SidebarShellDivider />

        {/* ─── Footer section ─── */}
        <SidebarFooter onCommandPalette={onCommandPalette} />
      </SidebarCard>
    </SidebarShell>
  );

  // Mobile: fixed overlay drawer — slides via x transform, always 272px.
  // When closed it stays mounted for the spring close animation but is
  // inert + hidden from AT so focus cannot land inside an off-screen drawer.
  const mobileDrawer = (
    <motion.aside
      initial={false}
      animate={{
        x: mobileOpen ? 0 : -280,
        width: "min(272px, calc(100vw - 2rem))",
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
      <nav aria-label="Primary" className="space-y-0.5 px-1.5 pb-1.5 pt-1.5">
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
          onClick={() => { togglePlugins("plugins"); onMobileClose?.(); }}
        />
      </nav>

      {/* Sessions */}
      <AnimatePresence>
        <motion.div
          key="mobile-sessions"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <div
            ref={sessionListRef}
            className="relative flex-1 overflow-y-auto px-1.5 pb-1.5"
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
            {sessionList}
          </div>
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
        {isMobile && mobileOpen && (
          <MobileDrawerBackdrop
            onClose={() => onMobileClose?.()}
            closeLabel="Close session navigation"
          />
        )}
      </AnimatePresence>

      {isMobile ? mobileDrawer : desktopShell}

      <SessionContextMenu
        anchor={desktopSessionActions}
        onClose={() => setDesktopSessionActions(null)}
        onEdit={handleEdit}
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
