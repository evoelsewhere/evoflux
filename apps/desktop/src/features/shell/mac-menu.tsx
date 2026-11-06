import * as React from "react";
import {
  CheckMenuItem,
  Menu,
  MenuItem,
  PredefinedMenuItem,
  Submenu,
  type MenuItemOptions,
} from "@tauri-apps/api/menu";
import { open } from "@tauri-apps/plugin-dialog";
import { useSidebar } from "@/components/ui/sidebar";
import { useTheme, type Theme } from "@/components/theme-provider";
import { panels } from "@/features/panels/panel-registry";
import { inTauri, isMac } from "@/lib/platform";
import { useEngineStore } from "@/stores/engine-store";
import { canGoBack, canGoForward, useHistoryStore } from "@/stores/history-store";
import { useSessionStore } from "@/stores/session-store";
import { useUiStore } from "@/stores/ui-store";
import { REPOSITORY_URL, openLink, reloadWindow, resetZoom, toggleDevtools, zoomBy } from "./app-commands";

const separator = () => PredefinedMenuItem.new({ item: "Separator" });

/** A menu item that runs `action`; the accelerator is in Tauri's syntax ("CmdOrCtrl+N"). */
const item = (text: string, action: () => void, accelerator?: string, extra?: Partial<MenuItemOptions>) =>
  MenuItem.new({ text, accelerator, action: () => action(), ...extra });

/** Tauri accelerator for a panel's shortcut key (see the panel registry). */
const panelAccelerator = (key: string) => `CmdOrCtrl+${key === "`" ? "Backquote" : key === ";" ? "Semicolon" : key}`;

/**
 * The macOS menu bar, holding what the ☰ menu holds on Windows and Linux.
 * It replaces Tauri's default menu, so it also carries the standard App, Edit
 * and Window items — without an Edit menu, ⌘C / ⌘V do nothing in the webview.
 * Menu accelerators take the keys before the page sees them, so the page's
 * own hotkeys never fire twice. Renders nothing; mount once inside the
 * sidebar and theme providers.
 */
export function MacMenu() {
  const sidebar = useSidebar();
  const { theme, setTheme } = useTheme();
  // Handlers read the latest context through refs; the menu is built once.
  const live = React.useRef({ sidebar, setTheme, theme });
  live.current = { sidebar, setTheme, theme };

  const themeItems = React.useRef<Partial<Record<Theme, CheckMenuItem>>>({});
  const navItems = React.useRef<{ back?: MenuItem; forward?: MenuItem }>({});

  React.useEffect(() => {
    if (!isMac || !inTauri) return;
    let cancelled = false;

    // Back / Forward follow the history; chats that are gone do not count.
    const syncNav = () => {
      const state = useHistoryStore.getState();
      void navItems.current.back?.setEnabled(canGoBack(state));
      void navItems.current.forward?.setEnabled(canGoForward(state));
    };

    (async () => {
      const ui = () => useUiStore.getState();
      const engine = () => useEngineStore.getState();
      const history = () => useHistoryStore.getState();

      const themes = await Promise.all(
        (["system", "light", "dark"] as const).map(async (value) => {
          const check = await CheckMenuItem.new({
            text: value === "system" ? "System" : value === "light" ? "Light" : "Dark",
            checked: false,
            action: () => live.current.setTheme(value),
          });
          return [value, check] as const;
        }),
      );
      const back = await item("Back", () => history().back(), "CmdOrCtrl+[", { enabled: false });
      const forward = await item("Forward", () => history().forward(), "CmdOrCtrl+]", { enabled: false });

      const menu = await Menu.new({
        items: [
          await Submenu.new({
            text: "Evo Harness",
            items: [
              await PredefinedMenuItem.new({ item: { About: null } }),
              await separator(),
              await PredefinedMenuItem.new({ item: "Services" }),
              await separator(),
              await PredefinedMenuItem.new({ item: "Hide" }),
              await PredefinedMenuItem.new({ item: "HideOthers" }),
              await PredefinedMenuItem.new({ item: "ShowAll" }),
              await separator(),
              await PredefinedMenuItem.new({ item: "Quit" }),
            ],
          }),
          await Submenu.new({
            text: "File",
            items: [
              await item("New Chat", () => void engine().newChat(), "CmdOrCtrl+N"),
              await item(
                "Open Folder…",
                () =>
                  void open({ directory: true, multiple: false, title: "Open a workspace folder" }).then((folder) => {
                    if (typeof folder === "string") void engine().openWorkspace(folder);
                  }),
                "CmdOrCtrl+O",
              ),
              await separator(),
              await PredefinedMenuItem.new({ item: "CloseWindow" }),
            ],
          }),
          await Submenu.new({
            text: "Edit",
            items: [
              await PredefinedMenuItem.new({ item: "Undo" }),
              await PredefinedMenuItem.new({ item: "Redo" }),
              await separator(),
              await PredefinedMenuItem.new({ item: "Cut" }),
              await PredefinedMenuItem.new({ item: "Copy" }),
              await PredefinedMenuItem.new({ item: "Paste" }),
              await PredefinedMenuItem.new({ item: "SelectAll" }),
            ],
          }),
          await Submenu.new({
            text: "View",
            items: [
              await item("Toggle Sidebar", () => live.current.sidebar.toggleSidebar(), "CmdOrCtrl+B"),
              await item("Toggle Side Panel", () => ui().toggleRightPanel(), "CmdOrCtrl+J"),
              await separator(),
              await Submenu.new({ text: "Theme", items: themes.map(([, check]) => check) }),
              await separator(),
              await item("Zoom In", () => zoomBy(1), "CmdOrCtrl+="),
              await item("Zoom Out", () => zoomBy(-1), "CmdOrCtrl+-"),
              await item("Actual Size", resetZoom, "CmdOrCtrl+0"),
              await separator(),
              await PredefinedMenuItem.new({ item: "Fullscreen" }),
            ],
          }),
          await Submenu.new({
            text: "Go",
            items: [
              back,
              forward,
              await separator(),
              await item("Search Chats…", () => ui().setCommandOpen(true), "CmdOrCtrl+P"),
              await separator(),
              await Submenu.new({
                text: "Tools",
                items: await Promise.all(
                  panels.map((panel) => item(panel.title, () => ui().openPanel(panel.id), panelAccelerator(panel.shortcut))),
                ),
              }),
              await item("Next Tab", () => ui().cycleTab(1), "Ctrl+Tab"),
              await item("Previous Tab", () => ui().cycleTab(-1), "Ctrl+Shift+Tab"),
            ],
          }),
          await Submenu.new({
            text: "Developer",
            items: [
              await item("Reload", reloadWindow, "CmdOrCtrl+R"),
              await item("Toggle Developer Tools", () => toggleDevtools(), "Alt+CmdOrCtrl+I"),
              await separator(),
              await item("Restart Engine", () => void engine().start()),
              await item(
                "Copy Engine Log",
                () => void navigator.clipboard.writeText(engine().logs.map((l) => l.line).join("\n")),
              ),
            ],
          }),
          await Submenu.new({
            text: "Window",
            items: [
              await PredefinedMenuItem.new({ item: "Minimize" }),
              await PredefinedMenuItem.new({ item: "Maximize" }),
              await separator(),
              await PredefinedMenuItem.new({ item: "BringAllToFront" }),
            ],
          }),
          await Submenu.new({
            text: "Help",
            items: [
              await item("Documentation", () => openLink(`${REPOSITORY_URL}#readme`)),
              await item("Report an Issue", () => openLink(`${REPOSITORY_URL}/issues/new`)),
            ],
          }),
        ],
      });
      if (cancelled) return;
      await menu.setAsAppMenu();
      themeItems.current = Object.fromEntries(themes);
      navItems.current = { back, forward };
      syncNav();
      void themeItems.current[live.current.theme]?.setChecked(true);
    })().catch((error) => console.error("could not build the macOS menu", error));

    const unsubscribeHistory = useHistoryStore.subscribe(syncNav);
    const unsubscribeSessions = useSessionStore.subscribe(syncNav);
    return () => {
      cancelled = true;
      unsubscribeHistory();
      unsubscribeSessions();
    };
    // Built once; the theme checkmarks are synced by the effect below.
  }, []);

  React.useEffect(() => {
    for (const [value, check] of Object.entries(themeItems.current)) void check?.setChecked(value === theme);
  }, [theme]);

  return null;
}
