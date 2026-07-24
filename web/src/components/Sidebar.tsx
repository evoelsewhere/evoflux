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
import { useMotionPreset } from "@/lib/motion";

import {
  CalendarClock,
  Plus,
  RefreshCw,
  Search,
} from "lucide-react";
import { ModeSwitchTabs, ModeSwitchRail } from "@/components/ModeSwitchTabs";
import { isToday, isYesterday } from "date-fns";
import {
  useTeamSessionsQuery,
  useDeleteTeamSessionMutation,
  useUpdateTeamSessionTitleMutation,
} from "@/queries";
import { ThemeToggle } from "./ThemeToggle";
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
} from "@/components/shell/SidebarShell";
import { SessionRow } from "@/components/shell/SessionRow";
import {
  SessionContextMenu,
  SessionActionsDialog,
  type SessionMenuAnchor,
} from "@/components/shell/SessionContextMenu";
import { EditSessionTitleDialog } from "@/components/shell/EditSessionTitleDialog";
import type { SessionResponse } from "@/api/types";

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
  /** Current mode — 'forge', 'coding', or 'aim' */
  mode?: 'forge' | 'coding' | 'aim';
  /** Mobile only: whether the overlay drawer is open */
  mobileOpen?: boolean;
  /** Mobile only: called when the drawer should close (backdrop tap, session select) */
  onMobileClose?: () => void;
}

export function Sidebar({
  currentSessionId,
  onCommandPalette,
  onNewChat,
  mode = 'forge',
  mobileOpen = false,
  onMobileClose,
}: SidebarProps) {
  const isMobile = useIsMobile();
  const { isTauri, os, isMacOverlay } = usePlatform();
  const isTauriMobile = isTauri && (os === "ios" || os === "android");
  const mobileLongPressActions = isMobile && isTauriMobile && mobileOpen;
  const preset = useMotionPreset();
  const navigate = useNavigate();
  const toggleScheduler = useUIStore((s) => s.toggleScheduler);
  // Server-filtered to forge — coding/aim sessions live in their own
  // sidebars (per-run aim sessions would otherwise flood this list).
  const sessions = useTeamSessionsQuery("forge");
  const deleteSession = useDeleteTeamSessionMutation();
  const updateSessionTitle = useUpdateTeamSessionTitleMutation();
  const sessionListRef = useRef<HTMLDivElement>(null);
  const loadMoreRef = useRef<HTMLDivElement>(null);

  // Flatten pages into a single list of sessions
  const normalSessions = sessions.data?.pages.flatMap((p) => p.data) ?? [];

  // Pinned sessions (persisted in usePinnedSessions) surface in a "Pinned"
  // section above the date groups; only ids present in the already-loaded
  // pages can render — a pinned session older than the loaded pages simply
  // doesn't appear until it loads into view.
  const pinnedIds = usePinnedSessions((s) => s.pinnedIds);
  const togglePin = usePinnedSessions((s) => s.togglePin);
  const pinnedIdSet = new Set(pinnedIds);
  const pinnedSessions = pinnedIds
    .map((id) => normalSessions.find((s) => s.id === id))
    .filter((s): s is SessionResponse => s !== undefined);
  const unpinnedSessions = normalSessions.filter((s) => !pinnedIdSet.has(s.id));

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
  const [pullDistance, setPullDistance] = useState(0);
  const pullStartYRef = useRef<number | null>(null);

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
        setPullDistance(0);
        return;
      }
      setPullDistance(Math.min(72, delta * 0.5));
    },
    [canPullRefresh],
  );

  const handleSessionListTouchEnd = useCallback(() => {
    if (canPullRefresh && pullDistance >= 54) {
      void refetchSessions();
    }
    pullStartYRef.current = null;
    setPullDistance(0);
  }, [canPullRefresh, pullDistance, refetchSessions]);

  // Ctrl+R: refresh sessions (data refresh — a sidebar concern, not shell).
  // Ctrl+B (collapse) is owned once by AppShell; Ctrl+M (wiki) / Ctrl+S
  // (scheduler) live in TeamChatView — those panels moved out of the sidebar
  // per the topbar-redesign wireframe and their open-state is in useUIStore.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.metaKey) return;
      if (e.key === "r") {
        e.preventDefault();
        refetchSessions();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [refetchSessions]);

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

  const confirmDelete = () => {
    if (!pendingDeleteId) return;
    const target = normalSessions.find((s) => s.id === pendingDeleteId);
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

  const renderSessionRow = (session: SessionResponse) => (
    <SessionRow
      key={session.id}
      session={session}
      isActive={session.id === currentSessionId}
      onSelect={(s) => handleSelect(s.id)}
      onOpenSideChat={(s) => handleSideChat(s.id)}
      onDelete={handleDelete}
      pendingDelete={pendingDeleteId === session.id}
      onCancelDelete={() => setPendingDeleteId(null)}
      onConfirmDelete={confirmDelete}
      onEdit={handleEdit}
      mobileLongPressActions={mobileLongPressActions}
      onLongPress={setMobileSessionActions}
      onContextActions={(session, event) => {
        setDesktopSessionActions({
          session,
          x: event.clientX,
          y: event.clientY,
        });
      }}
    />
  );

  const sessionList = (
    <>
      {sessions.isLoading && <SessionListSkeleton />}
      {sessions.isError && (
        <p className="px-3 py-4 text-center text-xs text-(--color-error)">Failed to load sessions</p>
      )}
      {sessions.isSuccess && normalSessions.length === 0 && (
        <p className="px-3 py-4 text-center text-xs text-(--color-text-subtle)">No sessions yet</p>
      )}
      {sessions.isSuccess && normalSessions.length > 0 && (
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

  // Collapsed desktop rail: mode switch + nav icons + first-8-sessions dots.
  const rail = (
    <SidebarCard className="h-full">
      <div className="shrink-0 flex flex-col items-center px-1 py-2">
        <ModeSwitchRail
          active={mode}
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
        </nav>
      </div>

      <SidebarShellDivider className="mx-2" />

      <div className="flex flex-1 flex-col items-center gap-1 overflow-y-auto py-2">
        {sessions.isSuccess &&
          normalSessions.slice(0, 8).map((session) => {
            const isActive = session.id === currentSessionId;
            return (
              <button
                key={session.id}
                onClick={() => handleSelect(session.id)}
                title={session.title || 'Untitled'}
                className={`flex h-8 w-8 items-center justify-center rounded-md transition-colors ${
                  isActive
                    ? 'bg-(--bg-key) text-(--color-accent)'
                    : 'text-(--color-text-subtle) hover:bg-(--bg-key) hover:text-(--color-text-2)'
                }`}
              >
                <div className="h-1.5 w-1.5 rounded-full bg-current" />
              </button>
            );
          })}
      </div>

      <SidebarShellDivider className="mx-2" />

      <div className="shrink-0 flex justify-center py-2 pb-safe px-1">
        <ThemeToggle collapsed />
      </div>
    </SidebarCard>
  );

  // Desktop: one floating card with internal dividers (forge style).
  const desktopShell = (
    <SidebarShell
      collapsed={collapsed}
      rail={rail}
    >
      <SidebarCard className="h-full">
        {/* ─── Top section: search + nav ─── */}
        <div className="shrink-0">
          <div className={`px-2 ${isMacOverlay ? 'pt-10' : 'pt-2'}`}>
            <ModeSwitchTabs active={mode} />
          </div>
          {onCommandPalette && (
            <div className="px-2 pt-2">
              <SidebarSearchTrigger onClick={onCommandPalette} />
            </div>
          )}
          <nav aria-label="Primary" className="space-y-0.5 px-2 py-2">
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
          </nav>
        </div>

        <SidebarShellDivider />

        {/* ─── Sessions section ─── */}
        <AnimatePresence>
          <motion.div
            key="sessions-panel"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex min-h-0 flex-1 flex-col overflow-hidden"
          >
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
                <RefreshCw size={11} className={sessions.isFetching ? 'animate-spin' : ''} />
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
  const mobileDrawer = (
    <motion.aside
      initial={false}
      animate={{
        x: mobileOpen ? 0 : -280,
        width: "min(272px, calc(100vw - 2rem))",
      }}
      transition={preset.spring}
      className="mobile-safe-top fixed bottom-0 left-0 z-(--z-overlay) flex w-[min(272px,calc(100vw-2rem))] shrink-0 flex-col overflow-hidden bg-(--bg-sidebar) shadow-xl"
    >
      {/* Search trigger */}
      {onCommandPalette && (
        <div className="px-3 pt-3">
          <SidebarSearchTrigger onClick={onCommandPalette} />
        </div>
      )}

      {/* Mode switch */}
      <div className="px-3 pt-2">
        <ModeSwitchTabs active={mode} onNavigate={onMobileClose} />
      </div>

      {/* Nav */}
      <nav aria-label="Primary" className="space-y-0.5 px-2 pb-2 pt-2">
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

      {/* Sessions */}
      <AnimatePresence>
        <motion.div
          key="mobile-sessions"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <div className="flex items-center justify-between px-3 pb-1 pt-2">
            <span className="font-mono text-xs font-semibold uppercase tracking-[0.14em] text-(--color-text-muted)">
              Recent
            </span>
            <button
              onClick={() => refetchSessions()}
              className="rounded-xs p-1 text-(--color-text-subtle) transition-colors hover:bg-(--bg-key) hover:text-(--color-text-muted)"
              aria-label="Refresh sessions"
              title="Refresh sessions (Ctrl+R)"
            >
              <RefreshCw size={12} className={sessions.isFetching ? 'animate-spin' : ''} />
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
            {canPullRefresh && (
              <div
                className="pointer-events-none sticky top-0 z-(--z-panel) flex justify-center overflow-hidden transition-[height] duration-150"
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
      {/* Mobile backdrop — closes the drawer on tap */}
      <AnimatePresence>
        {isMobile && mobileOpen && (
          <motion.div
            key="sidebar-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="mobile-safe-top fixed inset-x-0 bottom-0 z-(--z-drawer) bg-(--color-overlay) md:hidden"
            aria-hidden="true"
            onClick={onMobileClose}
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
