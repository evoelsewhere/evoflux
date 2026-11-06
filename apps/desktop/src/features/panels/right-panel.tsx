import { PanelRightCloseIcon, PanelRightOpenIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from "@/components/ui/context-menu";
import { DropdownMenuGroup, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Kbd } from "@/components/ui/kbd";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { modKey } from "@/lib/platform";
import { cn } from "@/lib/utils";
import { BrowserPanel } from "@/features/browser";
import { FilesPanel } from "@/features/files";
import { MemoryPanel } from "@/features/memory";
import { SideChatPanel } from "@/features/side-chat";
import { TerminalPanel } from "@/features/terminal";
import { useUiStore, type PanelId } from "@/stores/ui-store";
import { panelById, panels, type PanelDefinition } from "./panel-registry";

/** Tools that lay out and scroll their own content. */
const FULL_BLEED = new Set<PanelId>(["terminal", "side-chat", "files", "browser", "memory"]);

/** "Ctrl+T" — one chip, like the menu shortcuts. */
export const shortcutLabel = (panel: PanelDefinition) => `${modKey}+${panel.shortcut}`;

/** One tool card: icon, title and a one-line description, shortcut on the right. */
function ToolCard({ panel, onOpen }: { panel: PanelDefinition; onOpen(): void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-center gap-3 rounded-lg bg-muted/70 px-3 py-2 text-left transition-colors hover:bg-accent focus-visible:bg-accent dark:bg-accent/50 dark:hover:bg-accent"
    >
      <panel.icon className="size-4 shrink-0 text-muted-foreground" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-[13px] font-medium leading-5">{panel.title}</span>
        <span className="truncate text-xs leading-4 text-muted-foreground">{panel.description}</span>
      </span>
      <Kbd className="hidden shrink-0 @[18rem]/tools:inline-flex">{shortcutLabel(panel)}</Kbd>
    </button>
  );
}

function PanelLauncher() {
  const openPanel = useUiStore((s) => s.openPanel);
  return (
    <div className="@container/tools flex h-full items-center justify-center px-4 py-6">
      <div className="flex w-full max-w-sm flex-col gap-1.5">
        {panels.map((panel) => (
          <ToolCard key={panel.id} panel={panel} onOpen={() => openPanel(panel.id)} />
        ))}
      </div>
    </div>
  );
}

/**
 * One tool in the rail: its icon, the accent behind it while it shows (the
 * accent icon alone while the panel is collapsed), an accent dot while it is
 * open but hidden (a terminal still running, browser tabs kept).
 * Clicking the visible tool collapses the side panel to the rail, like VS
 * Code's activity bar.
 * Right-click or middle-click closes an open tool.
 */
function RailButton({
  panel,
  active,
  chosen,
  open,
}: {
  panel: PanelDefinition;
  /** It shows in the expanded panel. */
  active: boolean;
  /** The panel's tool, shown or collapsed. */
  chosen: boolean;
  open: boolean;
}) {
  const { openPanel, closeTab, toggleRightPanel } = useUiStore.getState();
  const button = (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            role="tab"
            aria-selected={active}
            aria-label={panel.title}
            data-panel-tab={panel.id}
            onClick={() => (active ? toggleRightPanel(false) : openPanel(panel.id))}
            onAuxClick={(event) => {
              if (event.button === 1 && open) closeTab(panel.id);
            }}
            className={cn(
              "no-drag relative flex size-8 shrink-0 items-center justify-center rounded-lg outline-none transition-colors focus-visible:ring-2 focus-visible:ring-brand/40",
              active
                ? "bg-brand/15 text-brand hover:bg-brand/20"
                : chosen
                  ? "text-brand hover:bg-accent"
                  : "text-foreground/75 hover:bg-accent hover:text-foreground",
            )}
          />
        }
      >
        <panel.icon className="size-4" />
        {open && !active && !chosen && (
          <span
            aria-label="Open"
            className="absolute right-0.5 bottom-0.5 size-2 rounded-full bg-brand ring-2 ring-background"
          />
        )}
      </TooltipTrigger>
      <TooltipContent side="left" className="flex items-center gap-2">
        {panel.title}
        <Kbd>{shortcutLabel(panel)}</Kbd>
      </TooltipContent>
    </Tooltip>
  );
  if (!open) return button;
  return (
    <ContextMenu>
      <ContextMenuTrigger render={<div className="flex" />}>{button}</ContextMenuTrigger>
      <ContextMenuContent className="w-48">
        <DropdownMenuGroup>
          <DropdownMenuItem onClick={() => openPanel(panel.id)}>
            Show {panel.title}
            <span className="ml-auto text-xs text-muted-foreground">{shortcutLabel(panel)}</span>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => closeTab(panel.id)}>Close {panel.title}</DropdownMenuItem>
        </DropdownMenuGroup>
      </ContextMenuContent>
    </ContextMenu>
  );
}

/** The ready tools first, the ones still to come after a divider. */
const READY = new Set<PanelId>(["terminal", "browser", "files", "side-chat", "memory"]);

/**
 * The tool rail on the window's right edge, always shown: every tool as an
 * icon, the visible one in the accent colour; at the bottom, collapse the side
 * panel to the rail (or expand it again). Each tool's own tabs (shells, pages,
 * files) stay in the tool's top row, so there is one row of tabs, not two.
 */
export function ToolRail({ className }: { className?: string }) {
  const activePanel = useUiStore((s) => s.activePanel);
  const openTabs = useUiStore((s) => s.openTabs);
  const expanded = useUiStore((s) => s.rightPanelOpen);
  const toggleRightPanel = useUiStore((s) => s.toggleRightPanel);
  const openPanel = useUiStore((s) => s.openPanel);
  const ready = panels.filter((panel) => READY.has(panel.id));
  const later = panels.filter((panel) => !READY.has(panel.id));
  const button = (panel: PanelDefinition) => (
    <RailButton
      key={panel.id}
      panel={panel}
      active={expanded && panel.id === activePanel}
      chosen={panel.id === activePanel}
      open={openTabs.includes(panel.id)}
    />
  );
  const label = expanded ? "Collapse side panel" : "Expand side panel";
  return (
    <nav
      role="tablist"
      aria-label="Tools"
      aria-orientation="vertical"
      className={cn("flex w-11 shrink-0 flex-col items-center gap-1 bg-background py-2", className)}
    >
      {ready.map(button)}
      {later.length > 0 && <span aria-hidden className="my-1 h-px w-5 bg-border" />}
      {later.map(button)}
      <span className="flex-1" />
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={label}
              aria-expanded={expanded}
              // Expanding with nothing chosen yet shows the tool list.
              onClick={() => (expanded ? toggleRightPanel(false) : activePanel ? toggleRightPanel(true) : openPanel(null))}
              className="no-drag text-foreground/75 hover:text-foreground"
            />
          }
        >
          {expanded ? <PanelRightCloseIcon /> : <PanelRightOpenIcon />}
        </TooltipTrigger>
        <TooltipContent side="left" className="flex items-center gap-2">
          {label} <Kbd>{modKey}+J</Kbd>
        </TooltipContent>
      </Tooltip>
    </nav>
  );
}

/**
 * Side panel: the chosen tool, in a card beside the chat, below the title bar.
 *
 * `docked`: between the chat card and the tool rail, which the layout shows
 * on its own so it stays when the panel collapses.
 * `overlay`: a sheet over the chat on narrow windows, with its own rail.
 */
export function RightPanel({ variant = "docked" }: { variant?: "docked" | "overlay" }) {
  const activePanel = useUiStore((s) => s.activePanel);
  const panel = panelById(activePanel);
  const docked = variant === "docked";

  return (
    <div
      className={cn(
        "flex h-full min-w-0 bg-background duration-200 animate-in fade-in slide-in-from-right-3",
        docked && "min-[900px]:rounded-tl-xl",
      )}
    >
      <div
        className={cn(
          "min-h-0 min-w-0 flex-1",
          panel && FULL_BLEED.has(panel.id) ? "overflow-hidden" : "overflow-auto",
        )}
      >
        {panel?.id === "terminal" ? (
          <TerminalPanel />
        ) : panel?.id === "side-chat" ? (
          <SideChatPanel />
        ) : panel?.id === "files" ? (
          <FilesPanel />
        ) : panel?.id === "memory" ? (
          <MemoryPanel />
        ) : panel?.id === "browser" ? (
          <BrowserPanel />
        ) : panel ? (
          <Empty className="h-full">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <panel.icon />
              </EmptyMedia>
              <EmptyTitle>{panel.title}</EmptyTitle>
              <EmptyDescription>{panel.description}. Coming soon.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <PanelLauncher />
        )}
      </div>
      {!docked && <ToolRail className="border-l border-border/60" />}
    </div>
  );
}
