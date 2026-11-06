import * as React from "react";
import { createPortal } from "react-dom";

const DELAY = 400;

/**
 * Shows the design-system tooltip for every element with a `title` attribute,
 * instead of the webview's native one. The first time the pointer reaches an
 * element its `title` moves to `data-tip` (which silences the native tooltip).
 */
export function TitleTooltips() {
  const [tip, setTip] = React.useState<{ text: string; x: number; y: number; below: boolean } | null>(null);

  React.useEffect(() => {
    let timer = 0;
    let current: Element | null = null;
    const hide = () => {
      window.clearTimeout(timer);
      current = null;
      setTip(null);
    };
    const tipOf = (el: Element) => {
      const title = el.getAttribute("title");
      if (title !== null) {
        if (title.trim()) el.setAttribute("data-tip", title);
        else el.removeAttribute("data-tip");
        el.removeAttribute("title");
      }
      return el.getAttribute("data-tip");
    };
    const over = (event: PointerEvent) => {
      if (!(event.target instanceof Element)) return;
      let el: Element | null = event.target.closest("[title], [data-tip]");
      // Walk up past elements whose title is empty.
      while (el && !tipOf(el)) el = el.parentElement?.closest("[title], [data-tip]") ?? null;
      if (el === current) return;
      hide();
      if (!el) return;
      const target = el;
      current = target;
      timer = window.setTimeout(() => {
        const text = target.getAttribute("data-tip");
        if (!text || !target.isConnected) return;
        const r = target.getBoundingClientRect();
        const below = r.top < 48;
        setTip({ text, x: r.left + r.width / 2, y: below ? r.bottom + 6 : r.top - 6, below });
      }, DELAY);
    };
    document.addEventListener("pointerover", over, true);
    document.addEventListener("pointerdown", hide, true);
    document.addEventListener("scroll", hide, true);
    document.addEventListener("keydown", hide, true);
    window.addEventListener("blur", hide);
    return () => {
      hide();
      document.removeEventListener("pointerover", over, true);
      document.removeEventListener("pointerdown", hide, true);
      document.removeEventListener("scroll", hide, true);
      document.removeEventListener("keydown", hide, true);
      window.removeEventListener("blur", hide);
    };
  }, []);

  if (!tip) return null;
  return createPortal(
    <div
      role="tooltip"
      className="pointer-events-none fixed z-[100] w-max max-w-xs whitespace-pre-line break-words rounded-xl bg-foreground px-3 py-1.5 text-xs text-background animate-in fade-in-0 zoom-in-95"
      style={{
        left: Math.min(Math.max(tip.x, 160), window.innerWidth - 160),
        top: tip.y,
        transform: `translate(-50%, ${tip.below ? "0" : "-100%"})`,
      }}
    >
      {tip.text}
    </div>,
    document.body,
  );
}
