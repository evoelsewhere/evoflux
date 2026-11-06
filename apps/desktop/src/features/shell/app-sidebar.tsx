import { open } from "@tauri-apps/plugin-dialog";
import { PluginsIcon, SchedulerIcon } from "@/components/icons/tool-icons";
import { FolderPlusIcon, MoonIcon, SearchIcon, SettingsIcon, SquarePenIcon, SunIcon } from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { inTauri, isMac, modKey } from "@/lib/platform";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { LOCAL_GROUP, useSessionStore, type SessionSummary } from "@/stores/session-store";
import { ArchivedGroup, ChatList, WorkspaceGroup } from "./sidebar-chats";
import { useUiStore } from "@/stores/ui-store";
import { SidebarResizer } from "./sidebar-resizer";
import { TitleBarActions } from "./title-bar";

function IconButton({
  label,
  onClick,
  children,
  className,
}: {
  label: string;
  onClick?(): void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            onClick={onClick}
            className={cn("no-drag text-sidebar-foreground", className)}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

/**
 * Navigation on the system material (Mica / vibrancy): brand and new chat,
 * search, tools, chats grouped by workspace, engine status and theme.
 * The right edge drags to resize.
 */
export function AppSidebar() {
  const workspaces = useSessionStore((s) => s.workspaces);
  const sessions = useSessionStore((s) => s.sessions);
  const newChat = useEngineStore((s) => s.newChat);
  const openWorkspace = useEngineStore((s) => s.openWorkspace);
  const setCommandOpen = useUiStore((s) => s.setCommandOpen);
  const openSettings = useUiStore((s) => s.openSettings);
  const customizeOpen = useUiStore((s) => s.customizeOpen);
  const schedulerOpen = useUiStore((s) => s.schedulerOpen);
  const { resolved, setTheme } = useTheme();

  const byUpdated = (a: SessionSummary, b: SessionSummary) => b.updatedAt - a.updatedAt;
  // Nested sessions show under their parent; at the top only if it is gone.
  const ids = new Set(sessions.map((s) => s.id));
  const topLevel = sessions.filter((s) => !s.parentChatId || !ids.has(s.parentChatId));
  const pinned = topLevel.filter((s) => s.pinned).sort(byUpdated);
  const unpinned = topLevel.filter((s) => !s.pinned);
  const local = unpinned.filter((s) => s.workspaceId === null).sort(byUpdated);

  async function addWorkspace() {
    const folder = await open({ directory: true, multiple: false, title: "Add a workspace folder" });
    if (typeof folder === "string") await openWorkspace(folder);
  }

  return (
    <Sidebar className="border-r-0 group-data-[side=left]:border-r-0">
      {/* Title bar: the window's own buttons, after the macOS traffic lights. Empty space drags the window. */}
      <div
        data-tauri-drag-region
        className={cn("drag-region flex h-10 shrink-0 items-center px-2", isMac && inTauri && "pl-[76px]")}
      >
        <TitleBarActions />
      </div>
      <SidebarHeader className="gap-2 pt-0">
        <button
          type="button"
          onClick={() => setCommandOpen(true)}
          className="flex h-8 items-center gap-2 rounded-lg bg-sidebar-accent/60 px-2.5 text-sm text-sidebar-foreground transition-colors hover:bg-sidebar-accent"
        >
          <SearchIcon className="size-4 shrink-0" />
          <span className="flex-1 truncate text-left">Search chats…</span>
          <Kbd>{modKey} P</Kbd>
        </button>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton onClick={() => void newChat()} className="h-7 text-[13px]">
              <SquarePenIcon />
              <span>New chat</span>
            </SidebarMenuButton>
            <SidebarMenuBadge className="font-normal text-muted-foreground">{modKey} N</SidebarMenuBadge>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={() => useUiStore.getState().openScheduler()}
              isActive={schedulerOpen}
              className="h-7 text-[13px]"
            >
              <SchedulerIcon />
              <span>Scheduler</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={() => useUiStore.getState().openCustomize()}
              isActive={customizeOpen}
              className="h-7 text-[13px]"
            >
              <PluginsIcon />
              <span>Customize</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent className="gap-0">
        {pinned.length > 0 && (
          <SidebarGroup className="py-0.5">
            <SidebarGroupLabel className="h-7 text-xs font-normal text-muted-foreground">Pinned</SidebarGroupLabel>
            <SidebarGroupContent>
              <ChatList chats={pinned} />
            </SidebarGroupContent>
          </SidebarGroup>
        )}
        <div className="flex items-center justify-between px-4 pt-2 pb-1">
          <span className="text-xs text-muted-foreground">Workspaces</span>
          <IconButton label="Add workspace" onClick={() => void addWorkspace()} className="size-6 text-muted-foreground">
            <FolderPlusIcon />
          </IconButton>
        </div>

        {workspaces.map((workspace) => (
          <WorkspaceGroup
            key={workspace.id}
            id={workspace.id}
            name={workspace.name}
            path={workspace.path}
            chats={unpinned.filter((s) => s.workspaceId === workspace.id).sort(byUpdated)}
          />
        ))}
        <WorkspaceGroup id={LOCAL_GROUP} name="This computer" chats={local} />
        <ArchivedGroup />
      </SidebarContent>

      <SidebarFooter className="flex-row items-center gap-1">
        <IconButton label={`Settings (${modKey} ,)`} onClick={() => openSettings()}>
          <SettingsIcon />
        </IconButton>
        <div className="flex-1" />
        <IconButton
          label={resolved === "dark" ? "Light theme" : "Dark theme"}
          onClick={() => setTheme(resolved === "dark" ? "light" : "dark")}
        >
          {resolved === "dark" ? <SunIcon /> : <MoonIcon />}
        </IconButton>
      </SidebarFooter>

      <SidebarResizer />
    </Sidebar>
  );
}
