import * as React from "react";
import type { PanelImperativeHandle } from "react-resizable-panels";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { ChatView } from "@/features/chat/chat-view";
import { SummaryCard } from "@/features/chat/summary-card";
import { RightPanel, ToolRail } from "@/features/panels/right-panel";
import { CommandPalette } from "@/features/sessions/command-palette";
import { SettingsPage, SettingsSidebar } from "@/features/settings/settings-view";
import { AppSidebar } from "@/features/shell/app-sidebar";
import { Toaster } from "@/features/notifications/toaster";
import { WindowTitleBar, WorkspaceToolbar } from "@/features/shell/workspace-header";
import { useElementWidth } from "@/hooks/use-element-width";
import { cn } from "@/lib/utils";
import { chatWindowId } from "@/lib/windows";
import { SIDE_PANEL_WIDTH, useUiStore } from "@/stores/ui-store";
import { MacMenu } from "@/features/shell/mac-menu";
import { useAppBootstrap, useAppHotkeys } from "./use-app-bootstrap";
import { CustomizePage } from "@/features/customize/customize-page";
import { SchedulerPage } from "@/features/scheduler/scheduler-page";
import { UsagePage } from "@/features/usage/usage-page";

/** Below this width (right of the sidebar) the side panel overlays instead of splitting. */
const SPLIT_MIN_WIDTH = 900;
const MAIN_MIN = 440;

/**
 * The chat card: the workspace toolbar over the thread. Beside the docked side
 * panel it is rounded on both top corners.
 */
function ChatCard({ besidePanel }: { besidePanel: boolean }) {
  return (
    <div
      className={cn(
        "flex h-full min-w-0 flex-col overflow-hidden bg-background min-[900px]:rounded-tl-xl",
        besidePanel && "rounded-tr-xl",
      )}
    >
      <WorkspaceToolbar />
      <div className="relative min-h-0 flex-1">
        <ChatView />
        <SummaryCard />
      </div>
    </div>
  );
}

/**
 * Chat card and side panel card side by side, below the title bar. The side
 * panel slides open and closed; its width is dragged on the gap between them.
 */
function SplitLayout() {
  const rightPanelOpen = useUiStore((s) => s.rightPanelOpen);
  const toggleRightPanel = useUiStore((s) => s.toggleRightPanel);
  const setSidePanelWidth = useUiStore((s) => s.setSidePanelWidth);
  // Read once: later widths come from dragging, not from the store.
  const [initialWidth] = React.useState(() => useUiStore.getState().sidePanelWidth);
  const sidePanel = React.useRef<PanelImperativeHandle | null>(null);
  const group = React.useRef<HTMLDivElement | null>(null);
  // True while the side panel has any width — including its closing animation.
  const [sideVisible, setSideVisible] = React.useState(rightPanelOpen);
  // Resize events also fire for programmatic layout changes; only a drag on
  // the handle may open, close or re-size the panel in the store.
  const dragging = React.useRef(false);
  const startDrag = React.useCallback(() => {
    dragging.current = true;
    const stop = () => {
      dragging.current = false;
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  }, []);

  // The side panel stays mounted and collapses to zero, so reopening it
  // restores the width it was dragged to. Width changes animate only around
  // this open/close — never while dragging a handle or resizing the window —
  // so the flag goes on the DOM right before the resize and comes off after.
  React.useEffect(() => {
    const panel = sidePanel.current;
    const element = group.current;
    if (!panel) return;
    const opening = rightPanelOpen && panel.isCollapsed();
    const closing = !rightPanelOpen && !panel.isCollapsed();
    if (!opening && !closing) return;
    element?.setAttribute("data-animating", "");
    if (opening) {
      setSideVisible(true);
      panel.resize(`${useUiStore.getState().sidePanelWidth}px`);
    } else panel.collapse();
    const done = setTimeout(() => {
      element?.removeAttribute("data-animating");
      if (closing) setSideVisible(false);
    }, 260);
    return () => {
      clearTimeout(done);
      element?.removeAttribute("data-animating");
    };
  }, [rightPanelOpen]);

  return (
    <div className="flex h-full min-w-0">
      <ResizablePanelGroup orientation="horizontal" elementRef={group} className="min-w-0 flex-1">
        <ResizablePanel id="main" minSize={`${MAIN_MIN}px`}>
          {/* The tool rail is always beside it. */}
          <ChatCard besidePanel />
        </ResizablePanel>
        <ResizableHandle
          onPointerDown={startDrag}
          className={cn(
            // A narrow gap of window material between the two cards; the line shows on hover.
            "w-1.5 bg-transparent after:w-px after:bg-transparent hover:after:bg-ring/60 focus-visible:after:bg-ring",
            !rightPanelOpen && "pointer-events-none opacity-0",
          )}
        />
        <ResizablePanel
          id="side"
          panelRef={sidePanel}
          defaultSize={rightPanelOpen ? `${initialWidth}px` : 0}
          minSize={`${SIDE_PANEL_WIDTH.min}px`}
          maxSize="60"
          collapsible
          collapsedSize={0}
          // The side panel keeps its width when the window resizes; the chat flexes.
          groupResizeBehavior="preserve-pixel-size"
          onResize={(size) => {
            if (!dragging.current) return;
            const open = size.inPixels > 0;
            setSideVisible(open);
            if (open) setSidePanelWidth(size.inPixels);
            // Dragging the panel shut closes it; dragging it open opens it.
            if (open !== useUiStore.getState().rightPanelOpen) toggleRightPanel(open);
          }}
        >
          <div className="h-full w-full overflow-hidden">
            {(rightPanelOpen || sideVisible) && <RightPanel variant="docked" />}
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>
      {/* The rail joins the panel's card when it is open, else it is a card of its own. */}
      <ToolRail
        className={cn(
          "border-l transition-[border-radius,border-color] duration-200",
          sideVisible ? "border-border/60" : "border-transparent min-[900px]:rounded-tl-xl",
        )}
      />
    </div>
  );
}

/** Narrow windows: the side panel slides over the main column. */
function OverlayLayout() {
  const rightPanelOpen = useUiStore((s) => s.rightPanelOpen);
  const toggleRightPanel = useUiStore((s) => s.toggleRightPanel);
  return (
    <div className="flex h-full min-w-0">
      <div className="min-w-0 flex-1">
        <ChatCard besidePanel />
      </div>
      <ToolRail className="ml-1.5 rounded-tl-xl" />
      <Sheet open={rightPanelOpen} onOpenChange={(open) => toggleRightPanel(open)}>
        <SheetContent side="right" showCloseButton={false} className="w-[min(440px,92vw)] p-0 sm:max-w-none">
          <SheetTitle className="sr-only">Tools</SheetTitle>
          <SheetDescription className="sr-only">Side panel tools</SheetDescription>
          <RightPanel variant="overlay" />
        </SheetContent>
      </Sheet>
    </div>
  );
}

/**
 * Layout: a resizable sidebar on the system material; to its right the title
 * bar (notifications, window controls), and below it the chat card (workspace
 * toolbar over the thread) and, when open, the side panel card. Narrow windows overlay the side panel instead.
 */
export function App() {
  useAppBootstrap();
  useAppHotkeys();
  const sidebarOpen = useUiStore((s) => s.sidebarOpen);
  const sidebarWidth = useUiStore((s) => s.sidebarWidth);
  const setSidebarOpen = useUiStore((s) => s.setSidebarOpen);
  const settingsOpen = useUiStore((s) => s.settingsOpen);
  const customizeOpen = useUiStore((s) => s.customizeOpen);
  const schedulerOpen = useUiStore((s) => s.schedulerOpen);
  const usageOpen = useUiStore((s) => s.usageOpen);
  const [insetRef, insetWidth] = useElementWidth<HTMLElement>();
  const split = insetWidth === 0 || insetWidth >= SPLIT_MIN_WIDTH;
  // A chat window shows its one chat: no sidebar.
  const solo = chatWindowId !== null;

  return (
    <SidebarProvider
      open={solo ? false : sidebarOpen}
      onOpenChange={solo ? () => undefined : setSidebarOpen}
      className="h-full min-h-0"
      style={{ "--sidebar-width": `${sidebarWidth}px` } as React.CSSProperties}
    >
      {!solo && (settingsOpen ? <SettingsSidebar /> : <AppSidebar />)}
      <SidebarInset ref={insetRef} className="min-h-0 min-w-0 bg-transparent">
        {settingsOpen ? (
          <SettingsPage />
        ) : schedulerOpen && !solo ? (
          <div className="flex h-full min-w-0 flex-col">
            <WindowTitleBar />
            <div className="min-h-0 flex-1">
              <SchedulerPage />
            </div>
          </div>
        ) : usageOpen && !solo ? (
          <div className="flex h-full min-w-0 flex-col">
            <WindowTitleBar />
            <div className="min-h-0 flex-1">
              <UsagePage />
            </div>
          </div>
        ) : customizeOpen && !solo ? (
          <div className="flex h-full min-w-0 flex-col">
            <WindowTitleBar />
            <div className="min-h-0 flex-1">
              <CustomizePage />
            </div>
          </div>
        ) : (
          <div className="flex h-full min-w-0 flex-col">
            <WindowTitleBar />
            <div className="min-h-0 flex-1">{split ? <SplitLayout /> : <OverlayLayout />}</div>
          </div>
        )}
      </SidebarInset>
      <CommandPalette />
      <MacMenu />
      <Toaster />
    </SidebarProvider>
  );
}
