import * as React from "react";
import { useShallow } from "zustand/react/shallow";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import {
  ArchiveIcon,
  ChevronRightIcon,
  FolderOpenIcon,
  MoreHorizontalIcon,
  PinIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react";
import { StatusDot } from "@/components/status-dot";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
} from "@/components/ui/sidebar";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { LOCAL_GROUP, UNTITLED, useSessionStore, type SessionSummary } from "@/stores/session-store";
import { ChatMenuItems, useChatMenuKeys } from "./chat-menu";

// The sidebar's chat lists: a row per chat with what it is doing (running,
// waiting for approval, unread, how long ago), and its actions (see
// `chat-menu.tsx`) from a right-click or the "…" button.

/** "now", "5m", "3h", "2d", "4w", then the date. */
function age(at: number, now = Date.now()): string {
  const minutes = Math.floor((now - at) / 60_000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  if (days < 35) return `${Math.floor(days / 7)}w`;
  return new Date(at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Re-render once a minute so ages stay current. */
function useMinuteTick() {
  const [, setTick] = React.useState(0);
  React.useEffect(() => {
    const timer = window.setInterval(() => setTick((t) => t + 1), 60_000);
    return () => window.clearInterval(timer);
  }, []);
}

function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  action,
  onConfirm,
}: {
  open: boolean;
  onOpenChange(open: boolean): void;
  title: string;
  description: string;
  action: string;
  onConfirm(): void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            autoFocus
            onClick={() => {
              onOpenChange(false);
              onConfirm();
            }}
          >
            {action}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RenameInput({ chat, onDone }: { chat: SessionSummary; onDone(): void }) {
  const rename = useSessionStore((s) => s.rename);
  const [value, setValue] = React.useState(chat.title);
  const done = React.useRef(false);
  const commit = (save: boolean) => {
    if (done.current) return;
    done.current = true;
    if (save && value.trim() && value.trim() !== chat.title) void rename(chat.id, value);
    onDone();
  };
  return (
    <input
      autoFocus
      value={value}
      aria-label="Chat title"
      onChange={(event) => setValue(event.target.value)}
      onFocus={(event) => event.target.select()}
      onBlur={() => commit(true)}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit(true);
        else if (event.key === "Escape") commit(false);
      }}
      className="h-7 w-full rounded-lg border border-sidebar-ring bg-sidebar px-2 text-[13px] text-sidebar-accent-foreground outline-none"
    />
  );
}

/** One chat row: right-click (or "…") for its actions; the title shimmers while it runs. */
export function ChatItem({ chat, active }: { chat: SessionSummary; active: boolean }) {
  const busy = useEngineStore((s) => Boolean(s.runtimes[chat.id]?.transcript.busy || s.busyElsewhere[chat.id]));
  const waiting = useEngineStore((s) => Boolean(s.runtimes[chat.id]?.transcript.turns.at(-1)?.permission));
  const failed = useEngineStore((s) => s.runtimes[chat.id]?.status === "exited");
  const { selectSession, closeChat } = useEngineStore.getState();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [contextOpen, setContextOpen] = React.useState(false);
  const [renaming, setRenaming] = React.useState(false);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const archived = chat.archivedAt != null;
  const menu = {
    chat,
    active,
    onRename: () => setRenaming(true),
    onDelete: () => setConfirmDelete(true),
    onClose: () => {
      setMenuOpen(false);
      setContextOpen(false);
    },
  };
  const onMenuKey = useChatMenuKeys(menu);

  if (renaming) {
    return (
      <SidebarMenuItem>
        <RenameInput chat={chat} onDone={() => setRenaming(false)} />
      </SidebarMenuItem>
    );
  }

  const status = busy ? (
    <Spinner className="size-3.5 text-muted-foreground" aria-label="Running" />
  ) : waiting ? (
    <StatusDot tone="warn" pulse label="Waiting for approval" />
  ) : failed ? (
    <StatusDot tone="error" label="Engine stopped" />
  ) : chat.unread ? (
    <StatusDot tone="info" label="Unread reply" />
  ) : chat.draft ? null : (
    <span className="text-[11px] text-muted-foreground tabular-nums">{age(chat.updatedAt)}</span>
  );

  const row = (
    <>
      <SidebarMenuButton
        isActive={active || contextOpen}
        onClick={() => void selectSession(chat.id)}
        title={chat.preview ? `${chat.title}

${chat.preview}` : chat.title}
        className="h-7 pr-8 text-[13px]"
      >
        {chat.pinned && !archived && <PinIcon className="size-3! text-muted-foreground" />}
        <span
          className={cn(
            "truncate",
            chat.draft && "text-muted-foreground italic",
            chat.unread && "font-medium",
            busy && "shimmer motion-reduce:shimmer-none",
          )}
        >
          {chat.title || UNTITLED}
        </span>
      </SidebarMenuButton>
      {status && (
        <span
          className={cn(
            "pointer-events-none absolute top-1/2 right-2 flex -translate-y-1/2 items-center",
            !chat.draft && "group-hover/menu-item:opacity-0 group-focus-within/menu-item:opacity-0",
            menuOpen && "opacity-0",
          )}
        >
          {status}
        </span>
      )}
      {!chat.draft && (
        <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
          <DropdownMenuTrigger
            render={<SidebarMenuAction showOnHover className="top-1 size-5" aria-label={`Actions for ${chat.title}`} />}
          >
            <MoreHorizontalIcon />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" side="right" className="w-52" onKeyDown={onMenuKey}>
            <ChatMenuItems {...menu} />
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Delete this chat?"
        description={`"${chat.title}" and its whole conversation are removed from this computer. This cannot be undone.`}
        action="Delete chat"
        onConfirm={() => void closeChat(chat.id, "delete")}
      />
    </>
  );

  // A draft has no saved chat to act on yet.
  if (chat.draft) return <SidebarMenuItem>{row}</SidebarMenuItem>;
  return (
    <ContextMenu open={contextOpen} onOpenChange={setContextOpen}>
      <ContextMenuTrigger render={<SidebarMenuItem />}>{row}</ContextMenuTrigger>
      <ContextMenuContent className="w-52" onKeyDown={onMenuKey}>
        <ChatMenuItems {...menu} />
      </ContextMenuContent>
    </ContextMenu>
  );
}

/** Nested sessions shown before the rest fold into the footer. */
const NESTED_SHOWN = 3;

/**
 * The sessions a chat started, under its row with a guide line: running,
 * waiting and unread ones first, then the most recent; the rest fold into
 * "N more nested sessions · M unread".
 */
function NestedChats({ parentId, currentId }: { parentId: string; currentId: string | null }) {
  const children = useSessionStore(useShallow((s) => s.sessions.filter((x) => x.parentChatId === parentId)));
  const attention = useEngineStore((s) => {
    const marks: Record<string, number> = {};
    for (const child of children) {
      const rt = s.runtimes[child.id];
      marks[child.id] = rt?.transcript.turns.at(-1)?.permission ? 3 : rt?.transcript.busy || s.busyElsewhere[child.id] ? 2 : 0;
    }
    return JSON.stringify(marks);
  });
  const [expanded, setExpanded] = React.useState(false);
  if (children.length === 0) return null;
  const marks = JSON.parse(attention) as Record<string, number>;
  const rank = (chat: SessionSummary) => (marks[chat.id] ?? 0) + (chat.unread ? 1 : 0);
  const sorted = [...children].sort((a, b) => rank(b) - rank(a) || b.updatedAt - a.updatedAt);
  // The open chat stays visible even when it would fold away.
  const shown = expanded
    ? sorted
    : sorted.filter((chat, index) => index < NESTED_SHOWN || chat.id === currentId);
  const hidden = sorted.filter((chat) => !shown.includes(chat));
  const unread = hidden.filter((chat) => chat.unread).length;
  return (
    <SidebarMenuSub className="mr-0 ml-3.5 gap-0 pr-0 pl-1.5">
      {shown.map((chat) => (
        <ChatItem key={chat.id} chat={chat} active={chat.id === currentId} />
      ))}
      {(hidden.length > 0 || expanded) && sorted.length > NESTED_SHOWN && (
        <li>
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="flex h-6 w-full items-center gap-1 rounded-md px-2 text-left text-xs text-muted-foreground hover:text-sidebar-accent-foreground"
          >
            {expanded ? (
              "Show fewer"
            ) : (
              <>
                {hidden.length} more nested {hidden.length === 1 ? "session" : "sessions"}
                {unread > 0 && <span className="text-link"> · {unread} unread</span>}
              </>
            )}
          </button>
        </li>
      )}
    </SidebarMenuSub>
  );
}

export function ChatList({ chats, empty }: { chats: SessionSummary[]; empty?: string }) {
  const currentId = useEngineStore((s) => s.activeId);
  useMinuteTick();
  return (
    <SidebarMenu>
      {chats.length === 0 && empty && <p className="px-2 py-1 text-xs text-muted-foreground">{empty}</p>}
      {chats.map((chat) => (
        <React.Fragment key={chat.id}>
          <ChatItem chat={chat} active={chat.id === currentId} />
          <NestedChats parentId={chat.id} currentId={currentId} />
        </React.Fragment>
      ))}
    </SidebarMenu>
  );
}

/** One collapsible workspace: name, activity dot, "+" for a new chat and a menu, then its chats. */
export function WorkspaceGroup({
  id,
  name,
  path,
  chats,
}: {
  id: string;
  name: string;
  path?: string;
  chats: SessionSummary[];
}) {
  const collapsed = useSessionStore((s) => s.collapsed.includes(id));
  const toggleCollapsed = useSessionStore((s) => s.toggleCollapsed);
  const removeWorkspace = useSessionStore((s) => s.removeWorkspace);
  const { newChat, forgetChats } = useEngineStore.getState();
  const running = useEngineStore((s) => chats.some((chat) => s.runtimes[chat.id]?.transcript.busy));
  const unread = chats.some((s) => s.unread);
  const [confirmRemove, setConfirmRemove] = React.useState(false);

  return (
    <Collapsible open={!collapsed} onOpenChange={() => toggleCollapsed(id)}>
      <SidebarGroup className="group/workspace py-0.5">
        <SidebarGroupLabel
          title={path}
          render={<CollapsibleTrigger />}
          className="h-7 w-full gap-1 pr-14 text-[13px] font-semibold text-sidebar-accent-foreground hover:bg-sidebar-accent"
        >
          <span className="truncate">{name}</span>
          <ChevronRightIcon
            className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", !collapsed && "rotate-90")}
          />
        </SidebarGroupLabel>
        {collapsed && (running || unread) && (
          <span className="pointer-events-none absolute top-2.5 right-16 flex items-center">
            {running ? <Spinner className="size-3.5 text-muted-foreground" /> : <StatusDot tone="info" label="Unread replies" />}
          </span>
        )}
        {path && (
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <SidebarGroupAction
                  className="top-1.5 right-8 opacity-0 group-hover/workspace:opacity-100 aria-expanded:opacity-100"
                  title={`${name} actions`}
                />
              }
            >
              <MoreHorizontalIcon />
              <span className="sr-only">{name} actions</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-52">
              <DropdownMenuItem onClick={() => void revealItemInDir(path).catch(() => undefined)}>
                <FolderOpenIcon />
                Show in folder
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onClick={() => setConfirmRemove(true)}>
                <Trash2Icon />
                Remove workspace…
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
        <SidebarGroupAction title={`New chat in ${name}`} onClick={() => void newChat(id === LOCAL_GROUP ? null : id)} className="top-1.5">
          <PlusIcon />
          <span className="sr-only">New chat in {name}</span>
        </SidebarGroupAction>
        <CollapsibleContent>
          <SidebarGroupContent>
            <ChatList chats={chats} empty="No chats yet" />
          </SidebarGroupContent>
        </CollapsibleContent>
      </SidebarGroup>
      {path && (
        <ConfirmDialog
          open={confirmRemove}
          onOpenChange={setConfirmRemove}
          title={`Remove ${name}?`}
          description="The workspace and its chats are removed from evo. The folder and its files stay on disk."
          action="Remove"
          onConfirm={() => void removeWorkspace(id).then((ids) => forgetChats(ids))}
        />
      )}
    </Collapsible>
  );
}

/** Archived chats, loaded when opened. */
export function ArchivedGroup() {
  const archived = useSessionStore((s) => s.archived);
  const loadArchived = useSessionStore((s) => s.loadArchived);
  const [open, setOpen] = React.useState(false);
  return (
    <Collapsible
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) void loadArchived();
      }}
    >
      <SidebarGroup className="py-0.5">
        <SidebarGroupLabel
          render={<CollapsibleTrigger />}
          className="h-7 w-full gap-1 text-[13px] text-muted-foreground hover:bg-sidebar-accent"
        >
          <ArchiveIcon className="size-3.5!" />
          <span className="truncate">Archived</span>
          <ChevronRightIcon className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")} />
        </SidebarGroupLabel>
        <CollapsibleContent>
          <SidebarGroupContent>
            <ChatList chats={archived} empty="Nothing archived" />
          </SidebarGroupContent>
        </CollapsibleContent>
      </SidebarGroup>
    </Collapsible>
  );
}
