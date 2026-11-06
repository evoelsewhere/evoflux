import * as React from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { CopyIcon, MinusIcon, SquareIcon, XIcon } from "lucide-react";
import { inTauri, isMac } from "@/lib/platform";
import { cn } from "@/lib/utils";

/**
 * Minimise / maximise / close for frameless windows on Windows and Linux.
 * macOS keeps its native traffic lights, so this renders nothing there.
 */
export function WindowControls() {
  const [maximized, setMaximized] = React.useState(false);

  React.useEffect(() => {
    if (isMac || !inTauri) return;
    const window = getCurrentWindow();
    let stop: (() => void) | undefined;
    void window.isMaximized().then(setMaximized);
    void window
      .onResized(async () => setMaximized(await window.isMaximized()))
      .then((unlisten) => (stop = unlisten));
    return () => stop?.();
  }, []);

  if (isMac || !inTauri) return null;
  const window = getCurrentWindow();
  const button =
    "no-drag inline-flex h-full w-11 items-center justify-center text-muted-foreground transition-colors hover:bg-accent hover:text-foreground [&_svg]:size-3.5";

  return (
    <div className="flex h-full items-stretch">
      <button type="button" aria-label="Minimize" className={button} onClick={() => void window.minimize()}>
        <MinusIcon />
      </button>
      <button
        type="button"
        aria-label={maximized ? "Restore" : "Maximize"}
        className={button}
        onClick={() => void window.toggleMaximize()}
      >
        {maximized ? <CopyIcon className="-scale-x-100" /> : <SquareIcon />}
      </button>
      <button
        type="button"
        aria-label="Close"
        className={cn(button, "hover:bg-status-error hover:text-white")}
        onClick={() => void window.close()}
      >
        <XIcon />
      </button>
    </div>
  );
}
