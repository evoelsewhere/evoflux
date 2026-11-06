import * as React from "react";
import { invoke } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  EllipsisVerticalIcon,
  GlobeIcon,
  LockIcon,
  PlusIcon,
  RotateCwIcon,
  XIcon,
} from "lucide-react";
import { BrowserIcon } from "@/components/icons/tool-icons";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Spinner } from "@/components/ui/spinner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { inTauri } from "@/lib/platform";
import { cn } from "@/lib/utils";
import { useBrowserStore, type BrowserTab } from "@/stores/browser-store";
import { useUiStore } from "@/stores/ui-store";

const QUICK = ["localhost:3000", "localhost:5173", "localhost:8080"];

function IconButton({
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
            size="icon-xs"
            aria-label={label}
            disabled={disabled}
            onClick={onClick}
            className="shrink-0 text-muted-foreground"
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

const hostOf = (url: string) => {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "file:" ? decodeURIComponent(parsed.pathname.split("/").pop() || url) : parsed.host || url;
  } catch {
    return url;
  }
};

const tabLabel = (tab: BrowserTab) => tab.title || hostOf(tab.url) || "New tab";

function TabButton({ tab, active }: { tab: BrowserTab; active: boolean }) {
  const { select, closeTab } = useBrowserStore.getState();
  return (
    <div
      role="tab"
      aria-selected={active}
      tabIndex={active ? 0 : -1}
      title={tab.url}
      onClick={() => select(tab.id)}
      onAuxClick={(event) => {
        if (event.button === 1) closeTab(tab.id);
      }}
      className={cn(
        "group/btab relative flex h-6 max-w-44 min-w-16 shrink cursor-default items-center gap-1.5 rounded-md pr-6 pl-2 text-xs transition-colors",
        active ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
      )}
    >
      {tab.loading ? <Spinner className="size-3 shrink-0" /> : <GlobeIcon className="size-3 shrink-0" />}
      <span className="truncate">{tabLabel(tab)}</span>
      <button
        type="button"
        aria-label={`Close ${tabLabel(tab)}`}
        tabIndex={-1}
        onClick={(event) => {
          event.stopPropagation();
          closeTab(tab.id);
        }}
        className={cn(
          "absolute top-1/2 right-0.5 size-5 -translate-y-1/2 items-center justify-center rounded-sm text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
          active ? "flex" : "hidden group-hover/btab:flex",
        )}
      >
        <XIcon className="size-3" />
      </button>
    </div>
  );
}

function AddressBar({ tab }: { tab: BrowserTab | null }) {
  const [value, setValue] = React.useState(tab?.url ?? "");
  const [editing, setEditing] = React.useState(false);
  const { navigate, newTab } = useBrowserStore.getState();
  React.useEffect(() => {
    if (!editing) setValue(tab?.url && tab.url !== "about:blank" ? tab.url : "");
  }, [tab?.url, editing, tab]);
  const secure = tab?.url.startsWith("https://");

  return (
    <form
      className="flex h-7 min-w-0 flex-1 items-center gap-1.5 rounded-md bg-muted/70 px-2 dark:bg-accent/50"
      onSubmit={(event) => {
        event.preventDefault();
        const text = value.trim();
        if (!text) return;
        if (tab) void navigate(tab.id, text);
        else void newTab(text);
        setEditing(false);
        (document.activeElement as HTMLElement | null)?.blur();
      }}
    >
      {secure ? (
        <LockIcon className="size-3 shrink-0 text-muted-foreground" />
      ) : (
        <GlobeIcon className="size-3 shrink-0 text-muted-foreground" />
      )}
      <input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onFocus={(event) => {
          setEditing(true);
          event.target.select();
        }}
        onBlur={() => setEditing(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setValue(tab?.url ?? "");
            (event.target as HTMLInputElement).blur();
          }
        }}
        spellCheck={false}
        placeholder="Search or enter a URL"
        aria-label="Address"
        className="h-full min-w-0 flex-1 bg-transparent text-xs shadow-none outline-none placeholder:text-muted-foreground focus-visible:shadow-none"
      />
    </form>
  );
}

/** Popups (menus, dialogs, popovers) that would sit under the native page view. */
const OVERLAYS =
  '[data-slot="dropdown-menu-content"],[data-slot="context-menu-content"],[data-slot="popover-content"],[data-slot="select-content"],[data-slot="hover-card-content"],[role="dialog"],[role="alertdialog"]';

/**
 * Where the page shows: a placeholder whose box the native webview follows
 * (in window logical pixels: CSS pixels × the app zoom).
 */
function PageArea() {
  const area = React.useRef<HTMLDivElement>(null);
  const zoom = useUiStore((s) => s.zoom);

  React.useLayoutEffect(() => {
    const element = area.current;
    if (!element) return;
    const { setBounds, setCovered } = useBrowserStore.getState();
    let frame = 0;
    const measure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const rect = element.getBoundingClientRect();
        const scale = useUiStore.getState().zoom || 1;
        setBounds({ x: rect.left * scale, y: rect.top * scale, width: rect.width * scale, height: rect.height * scale });
        // Anything open over the page area hides the page meanwhile.
        const covered = [...document.querySelectorAll<HTMLElement>(OVERLAYS)].some((popup) => {
          // The narrow-window side panel is itself a sheet (a dialog) holding the page.
          if (popup.contains(element)) return false;
          const box = popup.getBoundingClientRect();
          return box.width > 0 && box.right > rect.left && box.left < rect.right && box.bottom > rect.top && box.top < rect.bottom;
        });
        setCovered(covered);
      });
    };
    measure();
    const resize = new ResizeObserver(measure);
    resize.observe(element);
    resize.observe(document.documentElement);
    const mutations = new MutationObserver(measure);
    mutations.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-open", "data-closed", "style"] });
    window.addEventListener("resize", measure);
    // The side panel slides open: follow it for a moment.
    const settle = setInterval(measure, 100);
    const stop = setTimeout(() => clearInterval(settle), 600);
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      mutations.disconnect();
      window.removeEventListener("resize", measure);
      clearInterval(settle);
      clearTimeout(stop);
      setBounds(null);
      setCovered(false);
    };
  }, [zoom]);

  return <div ref={area} className="h-full w-full" />;
}

function StartPage() {
  const history = useBrowserStore((s) => s.history);
  const newTab = useBrowserStore((s) => s.newTab);
  return (
    <div className="flex h-full flex-col items-center justify-center gap-5 px-6">
      <div className="flex flex-col items-center gap-2 text-center">
        <div className="flex size-9 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          <BrowserIcon className="size-4" />
        </div>
        <p className="text-sm font-medium">Browser</p>
        <p className="max-w-72 text-xs text-muted-foreground">
          Preview your app or open any site. The agent can see and use the page you have open here.
        </p>
      </div>
      <div className="flex w-full max-w-72 flex-col gap-1">
        {[...new Set([...history.slice(0, 6), ...QUICK])].slice(0, 8).map((url) => (
          <button
            key={url}
            type="button"
            onClick={() => void newTab(url)}
            className="flex h-7 items-center gap-2 rounded-md px-2 text-left text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <GlobeIcon className="size-3 shrink-0" />
            <span className="truncate">{url}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * The Browser tool: tabs of real pages (native webviews) laid over the panel,
 * an address bar that takes URLs, hosts, local files or a search, and the
 * page shared with the agent's browser tools.
 */
export function BrowserPanel() {
  const tabs = useBrowserStore((s) => s.tabs);
  const activeId = useBrowserStore((s) => s.activeId);
  const error = useBrowserStore((s) => s.error);
  const { newTab, go } = useBrowserStore.getState();
  const tab = tabs.find((t) => t.id === activeId) ?? null;

  if (!inTauri) {
    return <p className="p-4 text-xs text-muted-foreground">The browser runs in the desktop app.</p>;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-9 shrink-0 items-center gap-1 border-b border-border/60 px-1.5">
        <div
          role="tablist"
          aria-label="Browser tabs"
          className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none]"
        >
          {tabs.map((t) => (
            <TabButton key={t.id} tab={t} active={t.id === activeId} />
          ))}
        </div>
        <IconButton label="New tab" onClick={() => void newTab("about:blank")}>
          <PlusIcon />
        </IconButton>
      </div>
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-border/60 px-1.5">
        <IconButton label="Back" disabled={!tab} onClick={() => tab && go(tab.id, "back")}>
          <ArrowLeftIcon />
        </IconButton>
        <IconButton label="Forward" disabled={!tab} onClick={() => tab && go(tab.id, "forward")}>
          <ArrowRightIcon />
        </IconButton>
        <IconButton
          label={tab?.loading ? "Stop" : "Reload"}
          disabled={!tab}
          onClick={() => tab && go(tab.id, tab.loading ? "stop" : "reload")}
        >
          {tab?.loading ? <XIcon /> : <RotateCwIcon />}
        </IconButton>
        <AddressBar tab={tab} />
        <DropdownMenu>
          <DropdownMenuTrigger
            render={<Button variant="ghost" size="icon-xs" aria-label="Browser menu" disabled={!tab} className="shrink-0 text-muted-foreground" />}
          >
            <EllipsisVerticalIcon />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            {tab && (
              <>
                <DropdownMenuGroup>
                  <DropdownMenuItem onClick={() => void openUrl(tab.url).catch(() => undefined)}>Open in default browser</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => void navigator.clipboard.writeText(tab.url).catch(() => undefined)}>Copy URL</DropdownMenuItem>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                  <DropdownMenuItem onClick={() => void invoke("browser_zoom", { tab: tab.id, scale: 1.25 })}>Zoom 125%</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => void invoke("browser_zoom", { tab: tab.id, scale: 1 })}>Zoom 100%</DropdownMenuItem>
                  <DropdownMenuItem onClick={() => void invoke("browser_zoom", { tab: tab.id, scale: 0.8 })}>Zoom 80%</DropdownMenuItem>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => void invoke("browser_devtools", { tab: tab.id })}>Developer tools</DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {error && <p className="shrink-0 border-b border-border/60 px-3 py-1.5 text-xs text-destructive">{error}</p>}
      <div className="relative min-h-0 flex-1 bg-background">{tab ? <PageArea /> : <StartPage />}</div>
    </div>
  );
}
