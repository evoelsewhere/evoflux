// A `show_widget` widget in the chat (docs/features/office-v3-parity/sdd.md,
// FR-13; port of v3 web/src/components/WidgetRenderer.tsx).
//
// The model's HTML runs in an iframe with `sandbox="allow-scripts"` only: an
// opaque origin, so it cannot reach the app, its storage or the engine. (v3
// also granted `allow-same-origin`, which lets a frame's script reach its
// parent; evo leaves it out and talks to the frame by postMessage.) The
// document is loaded as a `data:` URL, which starts with a fresh
// Content-Security-Policy — the v3 widget policy injected by
// `wrapWidgetHtml` — instead of inheriting the app's. Messages are accepted
// only from this frame's own window: `sendPrompt(text)` sends `text` as a new
// message in the chat, and the height report sizes the frame (120–2400 px).
// The app's theme is seeded into the document and kept in sync.

import * as React from "react";
import { Spinner } from "@/components/ui/spinner";
import {
  WIDGET_RESIZE,
  WIDGET_SEND_PROMPT,
  WIDGET_THEME,
  clampWidgetHeight,
  readWidgetTheme,
  wrapWidgetHtml,
} from "@/lib/widget-document";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";

function appTheme() {
  const root = document.documentElement;
  return {
    theme: readWidgetTheme(window.getComputedStyle(root)),
    colorScheme: root.classList.contains("dark") ? ("dark" as const) : ("light" as const),
  };
}

/** A widget's message: a new user message, or the next step's input while the agent works. */
function sendToChat(text: string) {
  const engine = useEngineStore.getState();
  if (engine.transcript.busy) void engine.queueMessage(text, [], "steer");
  else void engine.sendPrompt(text);
}

export interface WidgetFrameProps {
  /** The widget's HTML (`widget_code`); empty while it is still being written. */
  html: string;
  title?: string;
  /** Height before the widget reports its own. */
  height?: number;
  /** Shown while `html` is empty. */
  loadingMessages?: string[];
  className?: string;
  /** Where `sendPrompt(text)` goes; the active chat by default. */
  onSendPrompt?(text: string): void;
}

export function WidgetFrame({
  html,
  title = "Widget",
  height = 600,
  loadingMessages,
  className,
  onSendPrompt,
}: WidgetFrameProps) {
  const frameRef = React.useRef<HTMLIFrameElement>(null);
  const [contentHeight, setContentHeight] = React.useState<number | null>(null);
  const sendRef = React.useRef(onSendPrompt);
  sendRef.current = onSendPrompt;

  // The theme at load time is baked into the document; later changes are posted.
  const src = React.useMemo(() => {
    if (!html) return "";
    const { theme, colorScheme } = appTheme();
    return `data:text/html;charset=utf-8,${encodeURIComponent(wrapWidgetHtml(html, theme, colorScheme))}`;
  }, [html]);

  React.useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      // Widgets speak only through their own frame: any other window could
      // otherwise send a prompt into the chat.
      const frame = frameRef.current?.contentWindow;
      if (!frame || event.source !== frame) return;
      const data = event.data as { type?: unknown; prompt?: unknown; height?: unknown } | null;
      if (data?.type === WIDGET_SEND_PROMPT && typeof data.prompt === "string" && data.prompt.trim()) {
        (sendRef.current ?? sendToChat)(data.prompt.trim());
      } else if (data?.type === WIDGET_RESIZE && typeof data.height === "number" && Number.isFinite(data.height)) {
        setContentHeight(clampWidgetHeight(data.height));
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  // The frame's document does not inherit the app's variables: post them
  // whenever the appearance changes (class or style on <html> or <body>).
  React.useEffect(() => {
    const sync = () => {
      const { theme, colorScheme } = appTheme();
      frameRef.current?.contentWindow?.postMessage({ type: WIDGET_THEME, theme, colorScheme }, "*");
    };
    const observer = new MutationObserver(sync);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "style"] });
    if (document.body) observer.observe(document.body, { attributes: true, attributeFilter: ["class", "style"] });
    return () => observer.disconnect();
  }, []);

  if (!html) {
    return (
      <div
        className={cn("flex w-full items-center justify-center rounded-lg bg-card shadow-border", className)}
        style={{ minHeight: Math.min(height, 240) }}
        role="status"
      >
        <div className="flex flex-col items-center gap-2 text-muted-foreground">
          <Spinner />
          <span className="shimmer text-sm">{loadingMessages?.[0] || "Loading visualization..."}</span>
        </div>
      </div>
    );
  }

  return (
    <div className={cn("relative overflow-hidden", className)}>
      <iframe
        ref={frameRef}
        title={title}
        src={src}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        scrolling="no"
        style={{ height: contentHeight ?? clampWidgetHeight(height) }}
        className="block w-full border-0 transition-[height] duration-150"
      />
    </div>
  );
}
