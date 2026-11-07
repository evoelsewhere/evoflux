import * as React from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { ChevronLeftIcon, ChevronRightIcon, MenuIcon, PanelLeftIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSidebar } from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useTheme, type Theme } from "@/components/theme-provider";
import { panels } from "@/features/panels/panel-registry";
import { inTauri, isMac } from "@/lib/platform";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { canGoBack, canGoForward, useHistoryStore } from "@/stores/history-store";
import { useSessionStore } from "@/stores/session-store";
import { useUiStore } from "@/stores/ui-store";
import {
  REPOSITORY_URL,
  closeWindow,
  openLink,
  reloadWindow,
  resetZoom,
  runEditCommand,
  toggleDevtools,
  toggleFullscreen,
  zoomBy,
} from "./app-commands";

/** A shortcut as the platform writes it: "Ctrl+Shift+I" or "⇧⌘I". */
export function keys(...parts: string[]): string {
  if (!isMac) return parts.map((p) => (p === "Mod" ? "Ctrl" : p)).join("+");
  const symbol: Record<string, string> = { Mod: "⌘", Shift: "⇧", Alt: "⌥", Ctrl: "⌃" };
  const order = ["Ctrl", "Alt", "Shift", "Mod"];
  const mods = parts.filter((p) => p in symbol).sort((a, b) => order.indexOf(a) - order.indexOf(b));
  return [...mods.map((m) => symbol[m]), ...parts.filter((p) => !(p in symbol))].join("");
}

export const BACK_KEYS = isMac ? keys("Mod", "[") : keys("Alt", "←");
export const FORWARD_KEYS = isMac ? keys("Mod", "]") : keys("Alt", "→");

function Item({
  children,
  shortcut,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  shortcut?: string;
  onClick(): void;
  disabled?: boolean;
}) {
  return (
    <DropdownMenuItem onClick={onClick} disabled={disabled}>
      {children}
      {shortcut && <DropdownMenuShortcut className="tracking-normal">{shortcut}</DropdownMenuShortcut>}
    </DropdownMenuItem>
  );
}

function Submenu({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>{label}</DropdownMenuSubTrigger>
      <DropdownMenuSubContent className={cn("w-60", className)}>{children}</DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

/** The app menu (☰): File, Edit, View, Go, Developer, Help. Windows and Linux only — macOS has its menu bar. */
export function AppMenu() {
  const { toggleSidebar } = useSidebar();
  const { theme, setTheme } = useTheme();
  const engine = useEngineStore.getState();
  const ui = useUiStore.getState();
  const history = useHistoryStore();
  useSessionStore((s) => s.sessions); // back/forward skip chats that are gone
  const zoom = useUiStore((s) => s.zoom);

  async function openFolder() {
    const folder = await open({ directory: true, multiple: false, title: "Open a workspace folder" });
    if (typeof folder === "string") await engine.openWorkspace(folder);
  }

  return (
    <>
      <DropdownMenu>
        <Tooltip>
          <TooltipTrigger
            render={
              <DropdownMenuTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Menu"
                    className="no-drag text-sidebar-foreground data-popup-open:bg-sidebar-accent"
                  />
                }
              />
            }
          >
            <MenuIcon />
          </TooltipTrigger>
          <TooltipContent>Menu</TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="start" className="w-44">
          <Submenu label="File">
            <Item shortcut={keys("Mod", "N")} onClick={() => void engine.newChat()}>
              New chat
            </Item>
            <Item shortcut={keys("Mod", "O")} onClick={() => void openFolder()}>
              Open folder…
            </Item>
            <DropdownMenuSeparator />
            <Item shortcut={keys("Mod", ",")} onClick={() => ui.openSettings()}>
              Settings…
            </Item>
            <DropdownMenuSeparator />
            <Item shortcut={isMac ? keys("Mod", "Q") : keys("Alt", "F4")} onClick={closeWindow}>
              Exit
            </Item>
          </Submenu>

          <Submenu label="Edit" className="w-52">
            <Item shortcut={keys("Mod", "Z")} onClick={() => runEditCommand("undo")}>
              Undo
            </Item>
            <Item shortcut={isMac ? keys("Shift", "Mod", "Z") : keys("Mod", "Y")} onClick={() => runEditCommand("redo")}>
              Redo
            </Item>
            <DropdownMenuSeparator />
            <Item shortcut={keys("Mod", "X")} onClick={() => runEditCommand("cut")}>
              Cut
            </Item>
            <Item shortcut={keys("Mod", "C")} onClick={() => runEditCommand("copy")}>
              Copy
            </Item>
            <Item shortcut={keys("Mod", "V")} onClick={() => runEditCommand("paste")}>
              Paste
            </Item>
            <DropdownMenuSeparator />
            <Item shortcut={keys("Mod", "A")} onClick={() => runEditCommand("selectAll")}>
              Select all
            </Item>
          </Submenu>

          <Submenu label="View">
            <Item shortcut={keys("Mod", "B")} onClick={toggleSidebar}>
              Toggle sidebar
            </Item>
            <Item shortcut={keys("Mod", "J")} onClick={() => ui.toggleRightPanel()}>
              Toggle side panel
            </Item>
            <DropdownMenuSeparator />
            <Submenu label="Theme" className="w-36">
              <DropdownMenuRadioGroup value={theme} onValueChange={(value) => setTheme(value as Theme)}>
                <DropdownMenuRadioItem value="system">System</DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="light">Light</DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="dark">Dark</DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </Submenu>
            <DropdownMenuSeparator />
            <Item shortcut={keys("Mod", "=")} onClick={() => zoomBy(1)}>
              Zoom in
            </Item>
            <Item shortcut={keys("Mod", "-")} onClick={() => zoomBy(-1)}>
              Zoom out
            </Item>
            <Item shortcut={keys("Mod", "0")} onClick={resetZoom} disabled={zoom === 1}>
              Actual size{zoom !== 1 && <span className="text-muted-foreground">({Math.round(zoom * 100)}%)</span>}
            </Item>
            <DropdownMenuSeparator />
            <Item shortcut={isMac ? keys("Ctrl", "Mod", "F") : "F11"} onClick={() => void toggleFullscreen()}>
              Toggle full screen
            </Item>
          </Submenu>

          <Submenu label="Go">
            <Item shortcut={BACK_KEYS} onClick={history.back} disabled={!canGoBack(history)}>
              Back
            </Item>
            <Item shortcut={FORWARD_KEYS} onClick={history.forward} disabled={!canGoForward(history)}>
              Forward
            </Item>
            <DropdownMenuSeparator />
            <Item shortcut={keys("Mod", "P")} onClick={() => ui.setCommandOpen(true)}>
              Search chats…
            </Item>
            <DropdownMenuSeparator />
            <Submenu label="Tools" className="w-52">
              {panels.map((panel) => (
                <Item key={panel.id} shortcut={keys("Mod", panel.shortcut)} onClick={() => ui.openPanel(panel.id)}>
                  <panel.icon className="text-muted-foreground" />
                  {panel.title}
                </Item>
              ))}
            </Submenu>
            <Item shortcut={keys("Ctrl", "Tab")} onClick={() => ui.cycleTab(1)}>
              Next tab
            </Item>
            <Item shortcut={keys("Ctrl", "Shift", "Tab")} onClick={() => ui.cycleTab(-1)}>
              Previous tab
            </Item>
          </Submenu>

          <Submenu label="Developer">
            <Item shortcut={keys("Mod", "R")} onClick={reloadWindow}>
              Reload
            </Item>
            <Item
              shortcut={isMac ? keys("Alt", "Mod", "I") : keys("Mod", "Shift", "I")}
              onClick={() => toggleDevtools()}
              disabled={!inTauri}
            >
              Toggle developer tools
            </Item>
            <DropdownMenuSeparator />
            <Item onClick={() => void engine.start()}>Restart engine</Item>
            <Item
              onClick={() =>
                void navigator.clipboard.writeText(
                  useEngineStore
                    .getState()
                    .logs.map((l) => l.line)
                    .join("\n"),
                )
              }
            >
              Copy engine log
            </Item>
          </Submenu>

          <Submenu label="Help">
            <Item onClick={() => openLink(`${REPOSITORY_URL}#readme`)}>Documentation</Item>
            <Item onClick={() => openLink(`${REPOSITORY_URL}/issues/new`)}>Report an issue</Item>
            <DropdownMenuSeparator />
            <Item onClick={() => ui.openSettings("about")}>About Evo Harness</Item>
          </Submenu>
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );
}

function BarButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick(): void;
  disabled?: boolean;
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
            disabled={disabled}
            onClick={onClick}
            className="no-drag text-sidebar-foreground disabled:opacity-35"
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
 * The title bar's own buttons: app menu (not on macOS, which has a menu bar),
 * sidebar toggle, back and forward. They sit at the top of the sidebar, and
 * move into the header bar while the sidebar is collapsed.
 */
export function TitleBarActions({ className }: { className?: string }) {
  const { open, isMobile, openMobile, toggleSidebar } = useSidebar();
  const history = useHistoryStore();
  useSessionStore((s) => s.sessions);
  const expanded = isMobile ? openMobile : open;

  return (
    <div className={cn("flex items-center gap-0.5", className)}>
      {!(isMac && inTauri) && <AppMenu />}
      <BarButton label={`${expanded ? "Hide" : "Show"} sidebar (${keys("Mod", "B")})`} onClick={toggleSidebar}>
        <PanelLeftIcon />
      </BarButton>
      <BarButton label={`Back (${BACK_KEYS})`} onClick={history.back} disabled={!canGoBack(history)}>
        <ChevronLeftIcon />
      </BarButton>
      <BarButton label={`Forward (${FORWARD_KEYS})`} onClick={history.forward} disabled={!canGoForward(history)}>
        <ChevronRightIcon />
      </BarButton>
    </div>
  );
}
