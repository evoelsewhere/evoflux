import * as React from "react";
import { useSidebar } from "@/components/ui/sidebar";
import { SIDEBAR_WIDTH, useUiStore } from "@/stores/ui-store";

/** Dragging the edge further left than this collapses the sidebar. */
const COLLAPSE_AT = 150;
const STEP = 16;

/**
 * Drag handle on the sidebar's right edge. Drag to resize, drag past the
 * minimum to collapse, double-click to reset, or focus it and use the arrow
 * keys. Width is stored, so it survives restarts.
 */
export function SidebarResizer() {
  const { setOpen, isMobile } = useSidebar();
  const width = useUiStore((s) => s.sidebarWidth);
  const setWidth = useUiStore((s) => s.setSidebarWidth);
  const [dragging, setDragging] = React.useState(false);

  React.useEffect(() => {
    const root = document.documentElement;
    if (dragging) root.setAttribute("data-resizing", "x");
    else root.removeAttribute("data-resizing");
    return () => root.removeAttribute("data-resizing");
  }, [dragging]);

  if (isMobile) return null;

  function onPointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    const handle = event.currentTarget;
    const left = handle.parentElement?.getBoundingClientRect().left ?? 0;
    handle.setPointerCapture(event.pointerId);
    setDragging(true);

    const onMove = (move: PointerEvent) => {
      const next = move.clientX - left;
      if (next < COLLAPSE_AT) {
        setOpen(false);
        stop();
        return;
      }
      setWidth(next);
    };
    const stop = () => {
      setDragging(false);
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowLeft") setWidth(width - STEP);
    else if (event.key === "ArrowRight") setWidth(width + STEP);
    else if (event.key === "Home") setWidth(SIDEBAR_WIDTH.min);
    else if (event.key === "End") setWidth(SIDEBAR_WIDTH.max);
    else return;
    event.preventDefault();
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize sidebar"
      aria-valuemin={SIDEBAR_WIDTH.min}
      aria-valuemax={SIDEBAR_WIDTH.max}
      aria-valuenow={width}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onDoubleClick={() => setWidth(SIDEBAR_WIDTH.default)}
      onKeyDown={onKeyDown}
      data-dragging={dragging || undefined}
      className="no-drag group/resizer absolute inset-y-0 -right-1.5 z-20 w-3 cursor-col-resize outline-none"
    >
      <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-transparent transition-colors group-hover/resizer:bg-ring/60 group-focus-visible/resizer:bg-ring group-data-dragging/resizer:bg-ring" />
    </div>
  );
}
