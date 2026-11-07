import * as React from "react";
import { open } from "@tauri-apps/plugin-dialog";
import {
  ChevronDownIcon,
  CornerLeftUpIcon,
  FolderOpenIcon,
  FolderIcon,
  GitBranchIcon,
  LaptopIcon,
} from "lucide-react";
import { WorktreeReview } from "@/components/ai-elements/worktree-review";
import { SidePanelIcon, SummaryIcon } from "@/components/icons/tool-icons";
import { ContextPanel } from "@/features/chat/context-panel";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSidebar } from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { inTauri, isMac, modKey } from "@/lib/platform";
import { cn } from "@/lib/utils";
import { chatWindowId } from "@/lib/windows";
import { useEngineStore } from "@/stores/engine-store";
import { useSessionStore } from "@/stores/session-store";
import { useUiStore } from "@/stores/ui-store";
import { TitleBarActions } from "./title-bar";
import { NotificationCenter } from "@/features/notifications/notification-center";
import { OpenInMenu } from "./open-in-menu";
import { WindowControls } from "./window-controls";

/** A chat working in a worktree: review its changes, apply or discard them. */
function WorktreeChip() {
  const chat = useSessionStore((s) => s.sessions.find((x) => x.id === s.currentId));
  const workspace = useSessionStore((s) => s.workspaces.find((w) => w.id === chat?.workspaceId));
  const leaveWorktree = useEngineStore((s) => s.leaveWorktree);
  const [open, setOpen] = React.useState(false);
  if (!chat?.worktreePath || !workspace) return null;
  const name = chat.worktreePath.replace(/\\/g, "/").split("/").filter(Boolean).at(-1);
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="no-drag min-w-0 gap-1.5 text-muted-foreground"
        title={`Works in the worktree ${chat.worktreePath}`}
        onClick={() => setOpen(true)}
      >
        <GitBranchIcon />
        <span className="max-w-40 truncate">Worktree {name}</span>
      </Button>
      <WorktreeReview
        open={open}
        onOpenChange={setOpen}
        repo={workspace.path}
        path={chat.worktreePath}
        onSettled={() => void leaveWorktree(chat.id)}
      />
    </>
  );
}

/** In a nested session: the chat that started it, one click away. */
function ParentLink() {
  const parent = useSessionStore((s) => {
    const current = s.sessions.find((x) => x.id === s.currentId);
    return current?.parentChatId ? s.sessions.find((x) => x.id === current.parentChatId) : undefined;
  });
  const selectSession = useEngineStore((s) => s.selectSession);
  if (!parent) return null;
  return (
    <Button
      variant="ghost"
      size="sm"
      className="no-drag min-w-0 gap-1.5 text-muted-foreground"
      title={`Started from ${parent.title}`}
      onClick={() => void selectSession(parent.id)}
    >
      <CornerLeftUpIcon />
      <span className="max-w-48 truncate">{parent.title}</span>
    </Button>
  );
}

/** The workspace of the current chat, and a way to switch or open another folder. */
function WorkspaceSwitcher() {
  const cwd = useEngineStore((s) => s.cwd);
  const openWorkspace = useEngineStore((s) => s.openWorkspace);
  const newChat = useEngineStore((s) => s.newChat);
  const workspace = useSessionStore((s) => s.workspaceOf(s.currentId));
  const workspaces = useSessionStore((s) => s.workspaces);
  const Icon = workspace ? FolderIcon : LaptopIcon;
  const others = workspaces.filter((w) => w.id !== workspace?.id);

  async function chooseFolder() {
    const folder = await open({ directory: true, multiple: false, title: "Open a workspace folder" });
    if (typeof folder === "string") await openWorkspace(folder);
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" size="sm" className="no-drag min-w-0 gap-2 font-medium" title={cwd} />}
      >
        <Icon className="text-muted-foreground" />
        <span className="truncate">{workspace?.name ?? "This computer"}</span>
        <ChevronDownIcon className="text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="truncate">{cwd ?? "Home folder"}</DropdownMenuLabel>
        </DropdownMenuGroup>
        {(others.length > 0 || workspace) && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuLabel>Switch to</DropdownMenuLabel>
              {others.map((w) => (
                <DropdownMenuItem key={w.id} onClick={() => void newChat(w.id)}>
                  <FolderIcon />
                  <span className="truncate">{w.name}</span>
                </DropdownMenuItem>
              ))}
              {workspace && (
                <DropdownMenuItem onClick={() => void newChat(null)}>
                  <LaptopIcon />
                  This computer
                </DropdownMenuItem>
              )}
            </DropdownMenuGroup>
          </>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => void chooseFolder()}>
          <FolderOpenIcon />
          Open folder…
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function HeaderIcon({
  label,
  pressed,
  onClick,
  children,
}: {
  label: string;
  pressed?: boolean;
  onClick(): void;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            aria-pressed={pressed}
            onClick={onClick}
            // Pressed in the accent colour (Settings → Appearance), like the side panel's tool rail.
            className={cn(
              "no-drag size-8 text-muted-foreground",
              pressed && "bg-brand/15 text-brand hover:bg-brand/20 hover:text-brand",
            )}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

const GroupDivider = () => <span aria-hidden className="mx-0.5 h-4 w-px shrink-0 bg-border" />;

/**
 * The window's title bar, right of the sidebar: the title bar buttons while
 * the sidebar is hidden, then — at the right — the notification bell and the
 * window controls. Everything else is empty space that drags the window.
 */
export function WindowTitleBar() {
  const { state, isMobile } = useSidebar();
  const sidebarHidden = state === "collapsed" || isMobile;
  // macOS traffic lights sit over the title bar once the sidebar is out of the way.
  const clearTrafficLights = isMac && inTauri && sidebarHidden;

  return (
    <header
      data-tauri-drag-region
      className={cn(
        "drag-region flex h-10 shrink-0 items-center gap-1 pl-2",
        clearTrafficLights && "pl-20",
        // No custom window controls at the edge (macOS, browser preview).
        (isMac || !inTauri) && "pr-2",
      )}
    >
      {/* While the sidebar is out of view its title bar buttons (menu, sidebar, back/forward) live here. */}
      {sidebarHidden && !chatWindowId && <TitleBarActions />}
      <div data-tauri-drag-region className="h-full min-w-4 flex-1" />
      <NotificationCenter />
      <WindowControls />
    </header>
  );
}

/**
 * The top row of the chat card: the workspace on the left; on the right one
 * group with Open in, context used, the summary and side panel toggles. Labels drop to
 * icons as the card narrows.
 */
export function WorkspaceToolbar() {
  const cwd = useEngineStore((s) => s.cwd);
  const context = useEngineStore((s) => s.state.context);
  const rightPanelOpen = useUiStore((s) => s.rightPanelOpen);
  const toggleRightPanel = useUiStore((s) => s.toggleRightPanel);
  const summaryShown = useUiStore((s) => (s.summaryFits ? s.summaryOpen : s.summaryPeek));
  const toggleSummary = useUiStore((s) => s.toggleSummary);
  const hasContext = (context?.window ?? 0) > 0;

  return (
    <div className="@container/header flex h-12 shrink-0 items-center gap-1 px-2">
      <WorkspaceSwitcher />
      <ParentLink />
      <WorktreeChip />
      <div className="min-w-4 flex-1" />

      {/* Workspace tools in one group: Open in, context used, summary, side panel. */}
      <div className="no-drag flex h-9 shrink-0 items-center gap-0.5 rounded-lg p-0.5 shadow-border-small">
        {cwd && (
          <>
            <OpenInMenu cwd={cwd} />
            <GroupDivider />
          </>
        )}
        {hasContext && (
          <>
            <ContextPanel />
            <GroupDivider />
          </>
        )}
        {/* The overlay summary ignores presses here, so this button can close it. */}
        <span data-summary-toggle className="contents">
          <HeaderIcon label={summaryShown ? "Hide summary" : "Show summary"} pressed={summaryShown} onClick={() => toggleSummary()}>
            <SummaryIcon open={summaryShown} className="size-[18px]" />
          </HeaderIcon>
        </span>
        <HeaderIcon label={`Side panel (${modKey} J)`} pressed={rightPanelOpen} onClick={() => toggleRightPanel()}>
          <SidePanelIcon open={rightPanelOpen} className="size-[18px]" />
        </HeaderIcon>
      </div>

    </div>
  );
}
