import * as React from "react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CaseSensitiveIcon,
  ChevronDownIcon,
  EraserIcon,
  PlusIcon,
  RotateCwIcon,
  SearchIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { TerminalIcon } from "@/components/icons/tool-icons";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from "@/components/ui/context-menu";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { isMac } from "@/lib/platform";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { tabLabel, terminalInstance, useTerminalStore, type TerminalTab } from "@/stores/terminal-store";

const COPY_KEYS = isMac ? "⌘C" : "Ctrl+Shift+C";
const PASTE_KEYS = isMac ? "⌘V" : "Ctrl+V";
const FIND_KEYS = isMac ? "⌘F" : "Ctrl+Shift+F";
/** Ctrl on every platform (⌘` switches windows on macOS). */
const NEW_KEYS = isMac ? "⌃⇧`" : "Ctrl+Shift+`";

function IconButton({
  label,
  onClick,
  disabled,
  pressed,
  children,
}: {
  label: string;
  onClick(): void;
  disabled?: boolean;
  pressed?: boolean;
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
            aria-pressed={pressed}
            disabled={disabled}
            onClick={onClick}
            className={cn("shrink-0 text-muted-foreground", pressed && "bg-accent text-foreground")}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

/** The last segment of a folder path. */
const folderName = (cwd: string) => cwd.split(/[\\/]/).filter(Boolean).pop() ?? cwd;

function TerminalTabButton({ tab, active }: { tab: TerminalTab; active: boolean }) {
  const { select, close } = useTerminalStore.getState();
  const label = tabLabel(tab);
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <div
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => select(tab.key)}
            onAuxClick={(event) => {
              if (event.button === 1) close(tab.key);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                select(tab.key);
              } else if (event.key === "Delete") {
                event.preventDefault();
                close(tab.key);
              }
            }}
            className={cn(
              "group/term relative flex h-6 max-w-40 shrink-0 cursor-default items-center gap-1.5 rounded-md pr-6 pl-2 text-xs transition-colors outline-none",
              active
                ? "bg-accent text-foreground"
                : "text-muted-foreground hover:bg-accent/60 hover:text-foreground focus-visible:bg-accent/60",
            )}
          />
        }
      >
        {tab.status === "starting" ? (
          <Spinner className="size-3 shrink-0" />
        ) : (
          <TerminalIcon className={cn("size-3 shrink-0", tab.status === "exited" && "text-destructive")} />
        )}
        <span className="truncate">{label}</span>
        <button
          type="button"
          aria-label={`Kill ${label}`}
          tabIndex={-1}
          onClick={(event) => {
            event.stopPropagation();
            close(tab.key);
          }}
          className={cn(
            "absolute top-1/2 right-0.5 size-5 -translate-y-1/2 items-center justify-center rounded-sm text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
            active ? "flex" : "hidden group-hover/term:flex",
          )}
        >
          <XIcon className="size-3" />
        </button>
      </TooltipTrigger>
      <TooltipContent className="flex flex-col items-start gap-0.5">
        <span>{tab.shell}</span>
        {tab.cwd && <span className="text-muted-foreground">{tab.cwd}</span>}
      </TooltipContent>
    </Tooltip>
  );
}

/** New terminal: one click for the default shell, the menu for another one. */
function NewTerminalButton({ onCreate }: { onCreate(shell?: string): void }) {
  const shells = useTerminalStore((s) => s.shells);
  const defaultShell = useTerminalStore((s) => s.defaultShell);
  const setDefaultShell = useTerminalStore((s) => s.setDefaultShell);
  const current = defaultShell && shells.some((s) => s.id === defaultShell) ? defaultShell : shells[0]?.id;

  return (
    <div className="flex shrink-0 items-center">
      <IconButton label={`New terminal (${NEW_KEYS})`} onClick={() => onCreate()}>
        <PlusIcon />
      </IconButton>
      <DropdownMenu>
        <Tooltip>
          <TooltipTrigger
            render={
              <DropdownMenuTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Choose a shell"
                    className="w-4 shrink-0 text-muted-foreground"
                  />
                }
              />
            }
          >
            <ChevronDownIcon className="size-3" />
          </TooltipTrigger>
          <TooltipContent>Choose a shell</TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuGroup>
            <DropdownMenuLabel>New terminal</DropdownMenuLabel>
            {shells.map((shell) => (
              <DropdownMenuItem key={shell.id} onClick={() => onCreate(shell.id)}>
                <TerminalIcon className="size-3.5 text-muted-foreground" />
                <span className="truncate">{shell.name}</span>
                {shell.id === current && <DropdownMenuShortcut>Default</DropdownMenuShortcut>}
              </DropdownMenuItem>
            ))}
            {shells.length === 0 && <DropdownMenuItem disabled>No shells found</DropdownMenuItem>}
          </DropdownMenuGroup>
          {shells.length > 1 && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuSub>
                <DropdownMenuSubTrigger>Default shell</DropdownMenuSubTrigger>
                <DropdownMenuSubContent className="w-52">
                  <DropdownMenuRadioGroup value={current ?? ""} onValueChange={(id) => setDefaultShell(String(id))}>
                    {shells.map((shell) => (
                      <DropdownMenuRadioItem key={shell.id} value={shell.id}>
                        {shell.name}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuSubContent>
              </DropdownMenuSub>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

/** Find in the active terminal's scrollback: Enter / Shift+Enter step, Esc closes. */
function FindBar({ tabKey }: { tabKey: string }) {
  const setFindOpen = useTerminalStore((s) => s.setFindOpen);
  const [query, setQuery] = React.useState("");
  const [caseSensitive, setCaseSensitive] = React.useState(false);
  const [results, setResults] = React.useState<{ index: number; count: number } | null>(null);
  const input = React.useRef<HTMLInputElement>(null);
  const instance = terminalInstance(tabKey);

  React.useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);

  React.useEffect(() => {
    if (!instance) return;
    const sub = instance.search.onDidChangeResults(({ resultIndex, resultCount }) =>
      setResults({ index: resultIndex, count: resultCount }),
    );
    return () => {
      sub.dispose();
      instance.search.clearDecorations();
    };
  }, [instance]);

  const find = (backwards = false, incremental = false) => {
    if (!instance) return;
    if (!query) {
      instance.search.clearDecorations();
      setResults(null);
      return;
    }
    const options = { caseSensitive, incremental };
    if (backwards) instance.findPrevious(query, options);
    else instance.findNext(query, options);
  };

  // Search as you type.
  React.useEffect(() => find(false, true), [query, caseSensitive]);

  const close = () => {
    setFindOpen(false);
    instance?.focus();
  };

  return (
    <div className="absolute top-2 right-3 z-10 flex items-center gap-0.5 rounded-lg bg-popover p-1 shadow-lg ring-1 ring-foreground/10">
      <input
        ref={input}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            find(event.shiftKey);
          } else if (event.key === "Escape") {
            event.preventDefault();
            close();
          }
        }}
        placeholder="Find"
        aria-label="Find in terminal"
        className="h-6 w-36 bg-transparent px-1.5 text-xs outline-none placeholder:text-muted-foreground"
      />
      <span className="min-w-12 px-1 text-right text-[11px] text-muted-foreground tabular-nums">
        {query && results ? (results.count === 0 ? "No results" : `${results.index + 1} of ${results.count}`) : ""}
      </span>
      <IconButton label="Match case" pressed={caseSensitive} onClick={() => setCaseSensitive((v) => !v)}>
        <CaseSensitiveIcon />
      </IconButton>
      <IconButton label="Previous match (Shift+Enter)" onClick={() => find(true)} disabled={!query}>
        <ArrowUpIcon />
      </IconButton>
      <IconButton label="Next match (Enter)" onClick={() => find(false)} disabled={!query}>
        <ArrowDownIcon />
      </IconButton>
      <IconButton label="Close (Esc)" onClick={close}>
        <XIcon />
      </IconButton>
    </div>
  );
}

/** Where the active terminal's xterm element is shown. */
function TerminalView({ tab }: { tab: TerminalTab }) {
  const container = React.useRef<HTMLDivElement>(null);
  const consumeFocus = useTerminalStore((s) => s.consumeFocus);
  const focusPending = useTerminalStore((s) => s.focusPending);
  const instance = terminalInstance(tab.key);

  React.useLayoutEffect(() => {
    const element = container.current;
    if (!element || !instance) return;
    let alive = true;
    void instance.attach(element).then(() => {
      if (alive && useTerminalStore.getState().consumeFocus()) instance.focus();
    });
    const observer = new ResizeObserver(() => instance.scheduleFit());
    observer.observe(element);
    return () => {
      alive = false;
      observer.disconnect();
      instance.detach();
    };
  }, [instance]);

  // A focus request while already shown (Ctrl+`, a tab switch, a restart).
  React.useEffect(() => {
    if (focusPending && instance && consumeFocus()) instance.focus();
  }, [focusPending, instance, consumeFocus]);

  const [hasSelection, setHasSelection] = React.useState(false);
  const { restart, close, setFindOpen } = useTerminalStore.getState();

  return (
    <ContextMenu
      onOpenChange={(open) => {
        if (open) setHasSelection(!!instance?.term.hasSelection());
      }}
    >
      <ContextMenuTrigger
        render={<div ref={container} className="h-full w-full overflow-hidden" />}
      />
      <ContextMenuContent className="w-52">
        <DropdownMenuGroup>
          <DropdownMenuItem disabled={!hasSelection} onClick={() => void instance?.copySelection()}>
            Copy
            <DropdownMenuShortcut>{COPY_KEYS}</DropdownMenuShortcut>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => void instance?.paste()} disabled={tab.status !== "running"}>
            Paste
            <DropdownMenuShortcut>{PASTE_KEYS}</DropdownMenuShortcut>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => instance?.term.selectAll()}>Select all</DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem onClick={() => setFindOpen(true)}>
            Find
            <DropdownMenuShortcut>{FIND_KEYS}</DropdownMenuShortcut>
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => instance?.term.clear()}>Clear</DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem onClick={() => void restart(tab.key)}>Restart</DropdownMenuItem>
          <DropdownMenuItem variant="destructive" onClick={() => close(tab.key)}>
            Kill terminal
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </ContextMenuContent>
    </ContextMenu>
  );
}

/**
 * The Terminal tool: the user's shells in the chat's workspace, one tab each.
 * Shells keep running while another tool or no side panel shows; closing the
 * Terminal tool tab ends them.
 */
export function TerminalPanel() {
  const tabs = useTerminalStore((s) => s.tabs);
  const activeKey = useTerminalStore((s) => s.activeKey);
  const findOpen = useTerminalStore((s) => s.findOpen);
  const error = useTerminalStore((s) => s.error);
  const cwd = useEngineStore((s) => s.cwd);
  const [ready, setReady] = React.useState(false);
  const active = tabs.find((t) => t.key === activeKey) ?? null;

  const create = React.useCallback(
    (shell?: string) => void useTerminalStore.getState().create({ shell, cwd: useEngineStore.getState().cwd }),
    [],
  );

  // Shells, the terminals that outlived a reload, then a first terminal if none.
  React.useEffect(() => {
    let alive = true;
    void useTerminalStore
      .getState()
      .ensure(useEngineStore.getState().cwd)
      .then(() => alive && setReady(true));
    return () => {
      alive = false;
    };
  }, []);

  const { restart, close, setFindOpen } = useTerminalStore.getState();
  const instance = active ? terminalInstance(active.key) : undefined;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-9 shrink-0 items-center gap-1 border-b border-border/60 px-1.5">
        <div
          role="tablist"
          aria-label="Terminals"
          onWheel={(event) => {
            if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) event.currentTarget.scrollLeft += event.deltaY;
          }}
          className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none]"
        >
          {tabs.map((tab) => (
            <TerminalTabButton key={tab.key} tab={tab} active={tab.key === activeKey} />
          ))}
        </div>
        <NewTerminalButton onCreate={create} />
        <IconButton label={`Find (${FIND_KEYS})`} pressed={findOpen} onClick={() => setFindOpen(!findOpen)} disabled={!active}>
          <SearchIcon />
        </IconButton>
        <IconButton
          label="Clear"
          disabled={!active}
          onClick={() => {
            instance?.term.clear();
            instance?.focus();
          }}
        >
          <EraserIcon />
        </IconButton>
        <IconButton label="Kill terminal" disabled={!active} onClick={() => active && close(active.key)}>
          <Trash2Icon />
        </IconButton>
      </div>

      <div className="relative min-h-0 flex-1 py-1.5 pl-2.5 pr-1">
        {active ? (
          <>
            <TerminalView key={active.key} tab={active} />
            {findOpen && <FindBar key={active.key} tabKey={active.key} />}
            {active.status === "exited" && (
              <div className="absolute inset-x-3 bottom-3 z-10 flex items-center gap-2 rounded-lg bg-popover px-3 py-2 text-xs shadow-lg ring-1 ring-foreground/10">
                <span className="min-w-0 flex-1 truncate text-muted-foreground">
                  {error && active.exitCode === null
                    ? error
                    : `${active.shell} exited${active.exitCode != null ? ` with code ${active.exitCode}` : ""}.`}
                </span>
                <Button size="xs" variant="outline" onClick={() => void restart(active.key)}>
                  <RotateCwIcon />
                  Restart
                </Button>
                <Button size="xs" variant="ghost" onClick={() => close(active.key)}>
                  Close
                </Button>
              </div>
            )}
          </>
        ) : ready ? (
          <Empty className="h-full">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <TerminalIcon />
              </EmptyMedia>
              <EmptyTitle>No terminal open</EmptyTitle>
              <EmptyDescription>
                {cwd ? <>Start a shell in {folderName(cwd)}.</> : "Start a shell in your home folder."}
              </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button size="sm" variant="outline" onClick={() => create()}>
                <PlusIcon />
                New terminal
                <span className="text-muted-foreground">{NEW_KEYS}</span>
              </Button>
            </EmptyContent>
          </Empty>
        ) : (
          <div className="flex h-full items-center justify-center">
            <Spinner className="size-4 text-muted-foreground" />
          </div>
        )}
      </div>
    </div>
  );
}
