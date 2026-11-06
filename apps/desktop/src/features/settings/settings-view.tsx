import * as React from "react";
import { ArrowLeftIcon, SearchIcon, XIcon } from "lucide-react";
import { Kbd } from "@/components/ui/kbd";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { SidebarResizer } from "@/features/shell/sidebar-resizer";
import { TitleBarActions } from "@/features/shell/title-bar";
import { WindowControls } from "@/features/shell/window-controls";
import { inTauri, isMac } from "@/lib/platform";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import { matchesQuery, settingsGroups, settingsPages } from "./settings-registry";

/** Settings navigation, in place of the chat sidebar while settings are open. */
export function SettingsSidebar() {
  const section = useUiStore((s) => s.settingsSection);
  const openSettings = useUiStore((s) => s.openSettings);
  const closeSettings = useUiStore((s) => s.closeSettings);
  const [query, setQuery] = React.useState("");
  const visible = settingsPages.filter((page) => matchesQuery(page, query));

  return (
    <Sidebar className="border-r-0 group-data-[side=left]:border-r-0">
      <div
        data-tauri-drag-region
        className={cn("drag-region flex h-12 shrink-0 items-center px-2", isMac && inTauri && "pl-[76px]")}
      >
        <TitleBarActions />
      </div>
      <SidebarHeader className="gap-2 pt-0">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton onClick={closeSettings} className="h-8 text-[13px] font-medium">
              <ArrowLeftIcon />
              <span>Back to app</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <label className="flex h-8 items-center gap-2 rounded-lg bg-sidebar-accent/60 px-2.5 text-sm text-sidebar-foreground transition-colors focus-within:bg-sidebar-accent focus-within:shadow-[0_0_0_1px_var(--ring)]">
          <SearchIcon className="size-4 shrink-0" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && visible[0]) openSettings(visible[0].id);
              if (event.key === "Escape") setQuery("");
            }}
            placeholder="Search settings…"
            className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-sidebar-foreground/70 focus-visible:shadow-none"
          />
          {query && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => setQuery("")}
              className="text-muted-foreground hover:text-foreground"
            >
              <XIcon className="size-3.5" />
            </button>
          )}
        </label>
      </SidebarHeader>

      <SidebarContent className="gap-0 pt-2">
        {settingsGroups.map((group) => {
          const pages = visible.filter((page) => page.group === group);
          if (pages.length === 0) return null;
          return (
            <SidebarGroup key={group} className="py-1">
              <SidebarGroupLabel className="h-7 text-[11px] font-semibold tracking-wider uppercase">
                {group}
              </SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {pages.map((page) => (
                    <SidebarMenuItem key={page.id}>
                      <SidebarMenuButton
                        isActive={page.id === section}
                        onClick={() => openSettings(page.id)}
                        className="h-8 text-[13px] data-active:font-medium data-active:[&>svg]:text-brand"
                      >
                        <page.icon />
                        <span>{page.title}</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          );
        })}
        {visible.length === 0 && (
          <p className="px-4 py-2 text-xs text-muted-foreground">No settings match “{query}”.</p>
        )}
      </SidebarContent>

      <SidebarResizer />
    </Sidebar>
  );
}

/** The settings page: a header bar over a scrolling card with the open section. */
export function SettingsPage() {
  const section = useUiStore((s) => s.settingsSection);
  const closeSettings = useUiStore((s) => s.closeSettings);
  const { state, isMobile } = useSidebar();
  const page = settingsPages.find((p) => p.id === section) ?? settingsPages[0];
  const Section = page.component;
  const clearTrafficLights = isMac && inTauri && (state === "collapsed" || isMobile);
  const scroller = React.useRef<HTMLDivElement>(null);

  // Each section opens at its top.
  React.useEffect(() => {
    // Braces matter: newer engines return a promise from scrollTo.
    void scroller.current?.scrollTo({ top: 0 });
  }, [section]);

  // Escape leaves settings unless something on the page (a menu, a field) handled it.
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, [role=dialog], [role=menu], [role=listbox]")) return;
      closeSettings();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeSettings]);

  return (
    <div className="flex h-full min-w-0 flex-col">
      <header
        data-tauri-drag-region
        className={cn(
          "drag-region flex h-12 shrink-0 items-center gap-2 pl-4",
          clearTrafficLights && "pl-20",
          (isMac || !inTauri) && "pr-3",
        )}
      >
        {(state === "collapsed" || isMobile) && <TitleBarActions className="mr-1" />}
        <span className="text-sm font-medium">Settings</span>
        <span className="text-sm text-muted-foreground">/</span>
        <span className="truncate text-sm text-muted-foreground">{page.title}</span>
        <div data-tauri-drag-region className="h-full flex-1" />
        <span className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex">
          <Kbd>Esc</Kbd> to close
        </span>
        <WindowControls />
      </header>
      <div
        ref={scroller}
        className="min-h-0 flex-1 overflow-y-auto bg-background min-[900px]:rounded-t-xl"
      >
        <div className="mx-auto w-full max-w-3xl px-6 pt-10 pb-16 sm:px-10">
          <Section />
        </div>
      </div>
    </div>
  );
}
