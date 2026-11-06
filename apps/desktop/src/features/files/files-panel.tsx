import * as React from "react";
import {
  ChevronsDownUpIcon,
  EllipsisIcon,
  EllipsisVerticalIcon,
  EyeIcon,
  FileCodeIcon,
  FileCogIcon,
  FileIcon,
  FileJsonIcon,
  FileSpreadsheetIcon,
  FileTerminalIcon,
  FileTextIcon,
  FolderIcon,
  ImageIcon,
  ListTreeIcon,
  PencilIcon,
  SearchIcon,
  XIcon,
} from "lucide-react";
import { homeDir } from "@tauri-apps/api/path";
import { openPath } from "@tauri-apps/plugin-opener";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from "@/components/ui/context-menu";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatBytes } from "@/lib/format";
import { git } from "@/lib/git";
import { modKey } from "@/lib/platform";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { useFilesStore, type OpenFile } from "@/stores/files-store";
import { CodeEditor, dropEditorState } from "./code-editor";
import {
  fileName,
  grepFiles,
  listDir,
  relativePath,
  samePath,
  searchFiles,
  type DirEntry,
  type GrepHit,
  type SearchHit,
} from "./fs";
import { fileGit, inRepo, rowGit, type RowGit } from "./git-state";
import { PathMenuItems } from "./path-menu";

/** How often the open file is checked for changes on disk. */
const DISK_POLL_MS = 1500;
const AUTOSAVE_MS = 600;
/** How often git status is read while Files is open (and visible). */
const GIT_POLL_MS = 2000;
/** Content search results asked for at most. */
const GREP_LIMIT = 300;
/** Narrower than this, the tree and the editor take turns instead of sitting side by side. */
const SPLIT_MIN = 560;
const TREE_MIN = 180;
const EDITOR_MIN = 240;
const TREE_DEFAULT = 280;

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
            className={cn("shrink-0 text-muted-foreground", pressed && "bg-brand/12 text-brand hover:bg-brand/16 hover:text-brand")}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

const IMAGE = /\.(png|jpe?g|gif|webp|bmp|ico|avif|svg)$/i;
const MARKDOWN = /\.(md|mdx|markdown)$/i;
const TEXT = /\.(txt|rst|log)$|^(license|notice|readme|changelog|authors)(\.|$)/i;
const CODE =
  /\.(rs|ts|tsx|js|jsx|mjs|cjs|py|go|java|kt|swift|c|h|cc|cpp|hpp|cs|rb|php|lua|vue|svelte|html?|css|scss|less|sql|zig|dart|ex|exs|hs|ml|scala|r|toml)$/i;
const JSON_FILE = /\.(json|jsonc|json5|jsonl)$/i;
const SHELL = /\.(sh|bash|zsh|fish|ps1|psm1|bat|cmd)$/i;
const CONFIG = /\.(ya?ml|ini|cfg|conf|env|lock|properties|editorconfig)$|^\.(gitignore|gitattributes|npmrc|env.*)$/i;
const SHEET = /\.(csv|tsv|xlsx?|ods)$/i;

/** One icon per kind of file, picked by name. */
function FileKindIcon({ name, className }: { name: string; className?: string }) {
  const Icon = IMAGE.test(name)
    ? ImageIcon
    : MARKDOWN.test(name) || TEXT.test(name)
      ? FileTextIcon
      : JSON_FILE.test(name)
        ? FileJsonIcon
        : SHELL.test(name)
          ? FileTerminalIcon
          : SHEET.test(name)
            ? FileSpreadsheetIcon
            : CONFIG.test(name)
              ? FileCogIcon
              : CODE.test(name)
                ? FileCodeIcon
                : FileIcon;
  return <Icon className={className} />;
}

/** Letter, colour and label of a changed file in the tree. */
const FILE_MARK: Partial<Record<RowGit, { letter: string; className: string; label: string }>> = {
  modified: { letter: "M", className: "text-status-warn", label: "Modified" },
  added: { letter: "A", className: "text-status-ok", label: "Added or untracked" },
  deleted: { letter: "D", className: "text-status-error", label: "Deleted" },
};

/** The git mark at the end of a tree row: a letter for files, a dot for folders holding changes. */
function GitMark({ mark }: { mark: RowGit }) {
  if (mark === "folder-modified" || mark === "folder-added") {
    return (
      <span
        aria-label="Contains changes"
        className={cn("mr-0.5 ml-auto size-1.5 shrink-0 rounded-full", mark === "folder-added" ? "bg-status-ok" : "bg-status-warn")}
      />
    );
  }
  const file = FILE_MARK[mark];
  if (!file) return null;
  return (
    <span aria-label={file.label} className={cn("ml-auto w-3 shrink-0 text-center font-mono text-[10.5px] font-medium", file.className)}>
      {file.letter}
    </span>
  );
}

/** The folder caret: a small solid triangle, turned down when open. */
function Caret({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      className={cn("size-4 shrink-0 text-muted-foreground transition-transform duration-150", open && "rotate-90")}
    >
      <path d="M6 4.5v7l5.5-3.5z" fill="currentColor" />
    </svg>
  );
}

// ── Tree ────────────────────────────────────────────────────────────────────

/** Children of open folders, refreshed when a folder opens or on Refresh. */
const listings = new Map<string, DirEntry[]>();
/** Roots whose top folder was unfolded once already this session. */
const seenRoots = new Set<string>();

const ROW_PAD = 6;
const INDENT = 12;
const rowPadding = (depth: number) => ROW_PAD + depth * INDENT;

const rowClass =
  "flex h-7 w-full min-w-0 items-center gap-1 rounded-md pr-2 text-left text-[13px] outline-none hover:bg-accent/60 focus-visible:bg-accent/60 focus-visible:ring-1 focus-visible:ring-brand/40";

interface TreeContext {
  root: string;
  generation: number;
  selected: string | null;
  select(path: string): void;
}

const TreeCtx = React.createContext<TreeContext | null>(null);

function TreeNode({ entry, depth }: { entry: DirEntry; depth: number }) {
  const ctx = React.useContext(TreeCtx)!;
  const expanded = useFilesStore((s) => entry.dir && s.expanded.includes(entry.path));
  const mark = useFilesStore((s) => rowGit(s.git, entry.path, entry.dir));
  const markLabel = FILE_MARK[mark]?.label;
  const { toggleFolder, open } = useFilesStore.getState();
  const [children, setChildren] = React.useState<DirEntry[] | null>(() => listings.get(entry.path) ?? null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!entry.dir || !expanded) return;
    let live = true;
    listDir(entry.path)
      .then((list) => {
        listings.set(entry.path, list);
        if (live) {
          setChildren(list);
          setError(null);
        }
      })
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [entry.path, entry.dir, expanded, ctx.generation]);

  const selected = ctx.selected !== null && samePath(ctx.selected, entry.path);
  const activate = () => {
    ctx.select(entry.path);
    if (entry.dir) toggleFolder(entry.path);
    else void open(entry.path);
  };

  return (
    <div role="none">
      <ContextMenu>
        <ContextMenuTrigger
          render={
            <button
              type="button"
              role="treeitem"
              aria-expanded={entry.dir ? expanded : undefined}
              aria-selected={selected}
              data-tree-path={entry.path}
              onClick={activate}
              title={`${relativePath(ctx.root, entry.path) || entry.path}${markLabel ? ` — ${markLabel}` : ""}`}
              style={{ paddingLeft: rowPadding(depth) }}
              className={cn(
                rowClass,
                selected && "bg-brand/12 hover:bg-brand/14",
                (entry.dimmed || mark === "ignored") && !selected && "text-muted-foreground",
              )}
            />
          }
        >
          {entry.dir ? (
            <Caret open={expanded} />
          ) : (
            <span className={cn("flex size-4 shrink-0 items-center justify-center", selected ? "text-brand" : "text-muted-foreground")}>
              <FileKindIcon name={entry.name} className="size-3.5" />
            </span>
          )}
          <span className="truncate">{entry.name}</span>
          <GitMark mark={mark} />
        </ContextMenuTrigger>
        <ContextMenuContent className="w-56">
          <PathMenuItems path={entry.path} root={ctx.root} dir={entry.dir} onOpen={() => void open(entry.path)} />
        </ContextMenuContent>
      </ContextMenu>
      {entry.dir && expanded && (
        <div role="group" className="relative">
          {/* Indent guide under the open folder's caret. */}
          <span
            aria-hidden
            className="pointer-events-none absolute top-0 bottom-0 w-px bg-border"
            style={{ left: rowPadding(depth) + 7.5 }}
          />
          {error && (
            <p className="truncate py-1 text-xs text-destructive" style={{ paddingLeft: rowPadding(depth + 1) + 4 }}>
              {error}
            </p>
          )}
          {children?.map((child) => (
            <TreeNode key={child.path} entry={child} depth={depth + 1} />
          ))}
          {children?.length === 0 && (
            <p className="py-1 text-xs text-muted-foreground" style={{ paddingLeft: rowPadding(depth + 1) + 4 }}>
              Empty
            </p>
          )}
          {!children && !error && (
            <div className="flex h-7 items-center" style={{ paddingLeft: rowPadding(depth + 1) + 2 }}>
              <Spinner className="size-3 text-muted-foreground" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Wrap the part of `text` matching `query` (case-insensitive) in a mark. */
function Highlight({ text, query }: { text: string; query: string }) {
  const at = query ? text.toLowerCase().indexOf(query.toLowerCase()) : -1;
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark className="rounded-[3px] bg-brand/20 text-foreground">{text.slice(at, at + query.length)}</mark>
      {text.slice(at + query.length)}
    </>
  );
}

const dirOf = (relative: string) => (relative.includes("/") ? relative.slice(0, relative.lastIndexOf("/")) : "");

/** Search results: files by name, or lines inside files (`?query`). */
function Results({ root, query, inputRef }: { root: string; query: string; inputRef: React.RefObject<HTMLInputElement | null> }) {
  const open = useFilesStore((s) => s.open);
  const content = query.startsWith("?");
  const text = (content ? query.slice(1) : query).trim();
  const [files, setFiles] = React.useState<SearchHit[] | null>(null);
  const [lines, setLines] = React.useState<GrepHit[] | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [cursor, setCursor] = React.useState(0);
  const listRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    setCursor(0);
    if (!text) {
      setFiles(null);
      setLines(null);
      setBusy(false);
      return;
    }
    let live = true;
    setBusy(true);
    const timer = setTimeout(
      () => {
        const done = () => live && setBusy(false);
        if (content) {
          grepFiles(root, text, GREP_LIMIT)
            .then((list) => live && setLines(list))
            .catch(() => live && setLines([]))
            .finally(done);
        } else {
          searchFiles(root, text)
            .then((list) => live && setFiles(list))
            .catch(() => live && setFiles([]))
            .finally(done);
        }
      },
      content ? 220 : 100,
    );
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [root, text, content]);

  // Results the arrow keys move through, in display order.
  const targets = React.useMemo(
    () =>
      content
        ? (lines ?? []).map((hit) => ({ path: hit.path, line: hit.line }))
        : (files ?? []).map((hit) => ({ path: hit.path, line: undefined as number | undefined })),
    [content, lines, files],
  );

  // Keys typed in the filter box drive the list.
  React.useEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    const onKey = (event: KeyboardEvent) => {
      if (!targets.length) return;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        setCursor((i) => {
          const next = event.key === "ArrowDown" ? Math.min(targets.length - 1, i + 1) : Math.max(0, i - 1);
          requestAnimationFrame(() =>
            listRef.current?.querySelector(`[data-result="${next}"]`)?.scrollIntoView({ block: "nearest" }),
          );
          return next;
        });
      } else if (event.key === "Enter") {
        event.preventDefault();
        const target = targets[cursor];
        if (target) void open(target.path, target.line);
      }
    };
    input.addEventListener("keydown", onKey);
    return () => input.removeEventListener("keydown", onKey);
  }, [inputRef, targets, cursor, open]);

  if (!text) {
    return (
      <p className="px-3 py-3 text-xs text-muted-foreground">
        {content ? "Type to search inside the files." : null}
      </p>
    );
  }
  const list = content ? lines : files;
  if (!list) {
    return (
      <div className="flex justify-center py-6">
        <Spinner className="size-4 text-muted-foreground" />
      </div>
    );
  }
  if (list.length === 0) {
    return (
      <p className="px-3 py-3 text-xs text-muted-foreground">
        {busy ? "Searching…" : content ? "No matches in the files." : "No matching files. Start with ? to search inside files."}
      </p>
    );
  }

  if (!content) {
    return (
      <div ref={listRef} role="listbox" aria-label="Matching files">
        {(files ?? []).map((hit, index) => (
          <ContextMenu key={hit.path}>
            <ContextMenuTrigger
              render={
                <button
                  type="button"
                  role="option"
                  aria-selected={index === cursor}
                  data-result={index}
                  onClick={() => void open(hit.path)}
                  onMouseMove={() => setCursor(index)}
                  className={cn(rowClass, "gap-2 pl-2", index === cursor && "bg-brand/12 hover:bg-brand/14")}
                />
              }
            >
              <FileKindIcon name={fileName(hit.relative)} className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="shrink-0">{fileName(hit.relative)}</span>
              <span className="min-w-0 truncate text-xs text-muted-foreground">{dirOf(hit.relative)}</span>
            </ContextMenuTrigger>
            <ContextMenuContent className="w-56">
              <PathMenuItems path={hit.path} root={root} onOpen={() => void open(hit.path)} />
            </ContextMenuContent>
          </ContextMenu>
        ))}
      </div>
    );
  }

  // Lines grouped under their file, in the order the files were found.
  const groups: { relative: string; path: string; hits: { hit: GrepHit; index: number }[] }[] = [];
  (lines ?? []).forEach((hit, index) => {
    const last = groups[groups.length - 1];
    if (last && last.path === hit.path) last.hits.push({ hit, index });
    else groups.push({ relative: hit.relative, path: hit.path, hits: [{ hit, index }] });
  });
  const total = lines?.length ?? 0;

  return (
    <div ref={listRef} role="listbox" aria-label="Matching lines">
      <p className="px-2 pt-1 pb-1.5 text-[11px] text-muted-foreground">
        {total >= GREP_LIMIT ? `First ${GREP_LIMIT} matches` : `${total} ${total === 1 ? "match" : "matches"}`} in{" "}
        {groups.length} {groups.length === 1 ? "file" : "files"}
        {busy ? " · searching…" : ""}
      </p>
      {groups.map((group) => (
        <div key={group.path} role="group" aria-label={group.relative} className="mb-1">
          <ContextMenu>
            <ContextMenuTrigger
              render={
                <button
                  type="button"
                  onClick={() => void open(group.path)}
                  title={group.relative}
                  className={cn(rowClass, "gap-2 pl-2")}
                />
              }
            >
              <FileKindIcon name={fileName(group.relative)} className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="shrink-0 font-medium">{fileName(group.relative)}</span>
              <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{dirOf(group.relative)}</span>
              <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums">{group.hits.length}</span>
            </ContextMenuTrigger>
            <ContextMenuContent className="w-56">
              <PathMenuItems path={group.path} root={root} onOpen={() => void open(group.path)} />
            </ContextMenuContent>
          </ContextMenu>
          {group.hits.map(({ hit, index }) => (
            <button
              key={`${hit.line}:${hit.column}`}
              type="button"
              role="option"
              aria-selected={index === cursor}
              data-result={index}
              onClick={() => void open(hit.path, hit.line)}
              onMouseMove={() => setCursor(index)}
              className={cn(
                "flex min-h-6 w-full min-w-0 items-baseline gap-2 rounded-md py-0.5 pr-2 pl-7 text-left outline-none hover:bg-accent/60",
                index === cursor && "bg-brand/12 hover:bg-brand/14",
              )}
            >
              <span className="w-7 shrink-0 text-right font-mono text-[10.5px] text-muted-foreground tabular-nums">
                {hit.line}
              </span>
              <span className="min-w-0 truncate font-mono text-[11.5px] text-foreground/85">
                <Highlight text={hit.preview} query={text} />
              </span>
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * The folder tree with its filter box. Typing filters by file name; starting
 * with `?` searches inside the files.
 */
function Tree({
  root,
  generation,
  query,
  setQuery,
  inputRef,
}: {
  root: string;
  generation: number;
  query: string;
  setQuery(query: string): void;
  inputRef: React.RefObject<HTMLInputElement | null>;
}) {
  const active = useFilesStore((s) => s.active);
  const [selected, setSelected] = React.useState<string | null>(active);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  // The open file is the selected row; reveal it when it changes.
  React.useEffect(() => {
    if (!active) return;
    setSelected(active);
    revealInTree(root, active, scrollRef.current);
  }, [active, root]);

  // The top folder starts unfolded.
  React.useEffect(() => {
    if (seenRoots.has(root)) return;
    seenRoots.add(root);
    useFilesStore.getState().expand([root]);
  }, [root]);

  const rootEntry = React.useMemo<DirEntry>(
    () => ({ name: fileName(root), path: root, dir: true, size: 0, dimmed: false }),
    [root],
  );
  const ctx = React.useMemo<TreeContext>(() => ({ root, generation, selected, select: setSelected }), [root, generation, selected]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 px-2 pt-2 pb-1.5">
        <div className="flex h-8 items-center gap-1.5 rounded-lg border border-border/70 bg-background px-2 transition-[border-color,box-shadow] focus-within:border-brand/60 focus-within:ring-3 focus-within:ring-brand/15">
          <SearchIcon className="size-3.5 shrink-0 text-muted-foreground" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape" && query) {
                event.stopPropagation();
                setQuery("");
              }
            }}
            placeholder="Filter, or ? to search in files"
            aria-label="Filter files, or start with ? to search in files"
            spellCheck={false}
            className="h-full min-w-0 flex-1 bg-transparent text-[13px] shadow-none outline-none placeholder:text-muted-foreground focus-visible:shadow-none"
          />
          {query && (
            <button
              type="button"
              aria-label="Clear"
              onClick={() => {
                setQuery("");
                inputRef.current?.focus();
              }}
              className="text-muted-foreground hover:text-foreground"
            >
              <XIcon className="size-3.5" />
            </button>
          )}
        </div>
      </div>
      <div ref={scrollRef} className="scrollbar-slim min-h-0 flex-1 overflow-y-auto px-1.5 pb-3">
        {query.trim() ? (
          <Results root={root} query={query} inputRef={inputRef} />
        ) : (
          <TreeCtx.Provider value={ctx}>
            <div role="tree" aria-label="Files">
              <TreeNode key={`${root}:${generation}`} entry={rootEntry} depth={0} />
            </div>
          </TreeCtx.Provider>
        )}
      </div>
    </div>
  );
}

/** Unfold the folders down to `path` and scroll its row into view once it shows. */
function revealInTree(root: string, path: string, scroller: HTMLElement | null) {
  const relative = relativePath(root, path);
  if (relative === path.replace(/\\/g, "/")) return; // outside the folder
  const sep = root.includes("\\") ? "\\" : "/";
  const base = root.replace(/[\\/]+$/, "");
  const parts = relative.split("/").slice(0, -1);
  const folders = [root, ...parts.map((_, i) => `${base}${sep}${parts.slice(0, i + 1).join(sep)}`)];
  useFilesStore.getState().expand(folders);
  // Folders list asynchronously: look for the row for a moment.
  let tries = 0;
  const look = () => {
    const rows = scroller?.querySelectorAll<HTMLElement>("[data-tree-path]") ?? [];
    const row = [...rows].find((el) => samePath(el.dataset.treePath ?? "", path));
    if (row) row.scrollIntoView({ block: "nearest" });
    else if (++tries < 20) setTimeout(look, 60);
  };
  requestAnimationFrame(look);
}

// ── Open file ───────────────────────────────────────────────────────────────

function FileView({ file, root }: { file: OpenFile; root: string }) {
  const autoSave = useFilesStore((s) => s.autoSave);
  const reveal = useFilesStore((s) => (s.reveal?.path === file.path ? s.reveal : null));
  const { save, load, markDirty, setAutoSave, consumeReveal, checkDisk } = useFilesStore.getState();
  const [preview, setPreview] = React.useState(MARKDOWN.test(file.path));
  const [cursor, setCursor] = React.useState<{ line: number; column: number } | null>(null);
  const text = React.useRef<string | null>(null);
  const timer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const content = file.content;
  const isText = content?.kind === "text";
  const markdown = isText && MARKDOWN.test(file.path);
  const gitBase = useGitBase(root, file.path, isText);

  // Edits made on disk (the agent, git, another editor) show up here.
  React.useEffect(() => {
    const interval = setInterval(() => void checkDisk(file.path), DISK_POLL_MS);
    const onFocus = () => void checkDisk(file.path);
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", onFocus);
    };
  }, [file.path, checkDisk]);

  // Opening at a line shows the source.
  React.useEffect(() => {
    if (reveal) setPreview(false);
  }, [reveal]);

  const flush = React.useCallback(
    (force = false) => {
      clearTimeout(timer.current);
      const saving = text.current;
      if (saving === null) return;
      void save(file.path, saving, force).then((ok) => {
        // Typing during the save keeps it dirty for the next one.
        if (ok && text.current === saving) markDirty(file.path, false);
      });
    },
    [file.path, save, markDirty],
  );

  // Save what is pending when the file is switched away from.
  React.useEffect(
    () => () => {
      clearTimeout(timer.current);
      const state = useFilesStore.getState();
      const current = state.files[file.path];
      if (state.autoSave && current?.dirty && !current.conflict && text.current !== null) {
        void state.save(file.path, text.current);
      }
    },
    [file.path],
  );

  const status = file.saving
    ? "Saving…"
    : file.conflict
      ? "Changed on disk"
      : file.dirty
        ? autoSave
          ? "Editing"
          : "Unsaved"
        : "Saved";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-8 shrink-0 items-center gap-1 border-b border-border/60 pr-1 pl-3">
        <ContextMenu>
          <ContextMenuTrigger
            render={
              // Ellipsis at the start: the file name end of the path is what matters.
              <span
                dir="rtl"
                className="min-w-0 flex-1 truncate text-left font-mono text-[11.5px] text-muted-foreground"
                title={file.path}
              />
            }
          >
            <bdi>{relativePath(root, file.path)}</bdi>
          </ContextMenuTrigger>
          <ContextMenuContent className="w-56">
            <PathMenuItems path={file.path} root={root} />
          </ContextMenuContent>
        </ContextMenu>
        {markdown && (
          <IconButton label={preview ? "Edit source" : "Preview"} onClick={() => setPreview((v) => !v)}>
            {preview ? <PencilIcon /> : <EyeIcon />}
          </IconButton>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger
            render={<Button variant="ghost" size="icon-xs" aria-label="File actions" className="shrink-0 text-muted-foreground" />}
          >
            <EllipsisVerticalIcon />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuGroup>
              <DropdownMenuCheckboxItem checked={autoSave} onCheckedChange={(on) => setAutoSave(on)}>
                Auto save
              </DropdownMenuCheckboxItem>
              <DropdownMenuItem disabled={!file.dirty || autoSave} onClick={() => flush()}>
                Save
                <span className="ml-auto text-xs text-muted-foreground">{modKey}+S</span>
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => void load(file.path)}>Reload from disk</DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <PathMenuItems path={file.path} root={root} />
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {file.conflict && (
        <div className="flex shrink-0 items-center gap-2 border-b border-border/60 bg-amber-500/10 px-3 py-1.5 text-xs">
          <span className="min-w-0 flex-1">This file changed on disk while you were editing it.</span>
          <Button size="xs" variant="outline" onClick={() => flush(true)}>
            Override
          </Button>
          <Button size="xs" variant="ghost" onClick={() => void load(file.path)}>
            Discard mine
          </Button>
        </div>
      )}

      <div className="relative min-h-0 flex-1">
        {file.loading && !content ? (
          <div className="flex h-full items-center justify-center">
            <Spinner className="size-4 text-muted-foreground" />
          </div>
        ) : file.error && !content ? (
          <Empty className="h-full">
            <EmptyHeader>
              <EmptyTitle>Could not open this file</EmptyTitle>
              <EmptyDescription>{file.error}</EmptyDescription>
            </EmptyHeader>
            <Button size="sm" variant="outline" onClick={() => void load(file.path)}>
              Try again
            </Button>
          </Empty>
        ) : content?.kind === "image" ? (
          <div className="flex h-full items-center justify-center overflow-auto bg-[repeating-conic-gradient(var(--muted)_0_25%,transparent_0_50%)] bg-size-[16px_16px] p-4">
            <img src={content.dataUrl} alt={fileName(file.path)} className="max-h-full max-w-full object-contain" />
          </div>
        ) : content?.kind === "binary" || content?.kind === "tooLarge" ? (
          <Empty className="h-full">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <FileIcon />
              </EmptyMedia>
              <EmptyTitle>{content.kind === "binary" ? "Binary file" : "Too large to show"}</EmptyTitle>
              <EmptyDescription>{formatBytes(content.size)}</EmptyDescription>
            </EmptyHeader>
            <Button size="sm" variant="outline" onClick={() => void openPath(file.path).catch(() => undefined)}>
              Open with default app
            </Button>
          </Empty>
        ) : content?.kind === "text" ? (
          markdown && preview ? (
            <div className="h-full overflow-y-auto px-5 py-4">
              <Markdown>{content.text}</Markdown>
            </div>
          ) : (
            <CodeEditor
              path={file.path}
              text={content.text}
              revision={file.revision}
              readOnly={content.lossy}
              revealLine={reveal?.line}
              revealNonce={reveal?.nonce}
              gitBase={gitBase}
              onCursor={(line, column) => {
                setCursor({ line, column });
                if (reveal) consumeReveal();
              }}
              onChange={(next, dirty) => {
                text.current = next;
                markDirty(file.path, dirty);
                clearTimeout(timer.current);
                if (dirty && useFilesStore.getState().autoSave && !useFilesStore.getState().files[file.path]?.conflict) {
                  timer.current = setTimeout(() => flush(), AUTOSAVE_MS);
                }
              }}
              onSave={(next) => {
                text.current = next;
                flush();
              }}
            />
          )
        ) : null}
      </div>

      {isText && (
        <div className="flex h-6 shrink-0 items-center gap-3 border-t border-border/60 px-3 text-[11px] text-muted-foreground">
          <span className={cn(file.conflict && "text-amber-600 dark:text-amber-400")}>{status}</span>
          {content.lossy && <span>Read only: not valid UTF-8</span>}
          {file.error && content && <span className="text-destructive">{file.error}</span>}
          <span className="ml-auto tabular-nums">{cursor ? `Ln ${cursor.line}, Col ${cursor.column}` : ""}</span>
          <span>{formatBytes(content.size)}</span>
        </div>
      )}
    </div>
  );
}

/**
 * The open file's text at HEAD for the editor's change markers: read again
 * when HEAD moves or the file starts or stops being new. A new (untracked or
 * staged) file compares with nothing, so every line is added; a file git does
 * not track, or one over 1 MB, gets no markers.
 */
function useGitBase(root: string, path: string, isText: boolean): string | null {
  const head = useFilesStore((s) => s.git?.head ?? null);
  const tracked = useFilesStore((s) => inRepo(s.git, path));
  const added = useFilesStore((s) => fileGit(s.git, path) === "added");
  const [base, setBase] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!isText || !tracked) {
      setBase(null);
      return;
    }
    let live = true;
    git
      .fileBase(root, path)
      .then((text) => live && setBase(text ?? (added ? "" : null)))
      .catch(() => live && setBase(null));
    return () => {
      live = false;
    };
  }, [root, path, isText, tracked, added, head]);
  return base;
}

// ── Panel ───────────────────────────────────────────────────────────────────

function FileTab({ path, active, dirty }: { path: string; active: boolean; dirty: boolean }) {
  const { select } = useFilesStore.getState();
  const name = fileName(path);
  return (
    <div
      role="tab"
      aria-selected={active}
      tabIndex={active ? 0 : -1}
      title={path}
      onClick={() => select(path)}
      onAuxClick={(event) => {
        if (event.button === 1) closeFile(path);
      }}
      className={cn(
        "group/file relative flex h-7 max-w-44 shrink-0 cursor-default items-center gap-1.5 rounded-md pr-6 pl-2 text-xs transition-colors",
        active ? "bg-brand/12 text-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
      )}
    >
      <FileKindIcon name={name} className={cn("size-3.5 shrink-0", active ? "text-brand" : "text-muted-foreground")} />
      <span className="truncate">{name}</span>
      {dirty && (
        <span
          aria-label="Unsaved"
          className="absolute top-1/2 right-2 size-1.5 -translate-y-1/2 rounded-full bg-brand group-hover/file:hidden"
        />
      )}
      <button
        type="button"
        aria-label={`Close ${name}`}
        tabIndex={-1}
        onClick={(event) => {
          event.stopPropagation();
          closeFile(path);
        }}
        className={cn(
          "absolute top-1/2 right-0.5 size-5 -translate-y-1/2 items-center justify-center rounded-sm text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
          active && !dirty ? "flex" : "hidden group-hover/file:flex",
        )}
      >
        <XIcon className="size-3" />
      </button>
    </div>
  );
}

/** Close a tab (the editor saves pending edits as it unmounts when auto save is on). */
function closeFile(path: string) {
  dropEditorState(path);
  useFilesStore.getState().close(path);
}

function NoFileOpen() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-1.5 px-6 text-center">
      <FolderIcon className="mb-2 size-5 text-muted-foreground" strokeWidth={1.5} />
      <p className="text-[13px] font-medium">Open files appear here</p>
      <p className="max-w-60 text-xs text-balance text-muted-foreground">
        Pick a file in the tree, or click a file path in the conversation.
      </p>
    </div>
  );
}

/** Drag the tree's left edge to resize it; double-click puts it back. */
function TreeResizer({ container }: { container: React.RefObject<HTMLDivElement | null> }) {
  const setTreeWidth = useFilesStore((s) => s.setTreeWidth);
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the file tree"
      onDoubleClick={() => setTreeWidth(TREE_DEFAULT)}
      onPointerDown={(event) => {
        const box = container.current?.getBoundingClientRect();
        if (!box) return;
        event.preventDefault();
        const handle = event.currentTarget;
        handle.setPointerCapture(event.pointerId);
        const move = (e: PointerEvent) => {
          const width = Math.min(Math.max(box.right - e.clientX, TREE_MIN), box.width - EDITOR_MIN);
          setTreeWidth(width);
        };
        const up = () => {
          handle.removeEventListener("pointermove", move);
          handle.removeEventListener("pointerup", up);
          handle.removeEventListener("pointercancel", up);
          document.body.style.cursor = "";
        };
        document.body.style.cursor = "col-resize";
        handle.addEventListener("pointermove", move);
        handle.addEventListener("pointerup", up);
        handle.addEventListener("pointercancel", up);
      }}
      className="absolute inset-y-0 -left-1 z-10 w-2 cursor-col-resize after:absolute after:inset-y-0 after:left-1 after:w-px after:bg-transparent after:transition-colors hover:after:bg-brand/60"
    />
  );
}

/**
 * The Files tool, laid out like an editor: the open files on the left (tabs
 * on top, viewed and edited in place — auto save, images, markdown preview),
 * the folder tree on the right with one box to filter it or, starting with
 * `?`, search inside the files. Files changed on disk reload by themselves;
 * unsaved edits are never overwritten without asking. In a narrow panel the
 * tree and the editor take turns.
 */
export function FilesPanel() {
  const cwd = useEngineStore((s) => s.cwd);
  const tabs = useFilesStore((s) => s.tabs);
  const active = useFilesStore((s) => s.active);
  const files = useFilesStore((s) => s.files);
  const autoSave = useFilesStore((s) => s.autoSave);
  const treeVisible = useFilesStore((s) => s.treeVisible);
  const treeWidth = useFilesStore((s) => s.treeWidth);
  const { setTreeVisible, setAutoSave, collapseAll, closeAll, refreshGit } = useFilesStore.getState();
  const [home, setHome] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [generation, setGeneration] = React.useState(0);
  const [width, setWidth] = React.useState(0);
  // Narrow panels: whether the tree is shown over the open file.
  const [treeOver, setTreeOver] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (cwd) return;
    void homeDir().then(setHome).catch(() => undefined);
  }, [cwd]);
  const root = cwd || home;
  const file = active ? files[active] : undefined;

  // Git marks: read now, then while the window is visible and on focus.
  React.useEffect(() => {
    if (!root) return;
    void refreshGit(root, true);
    const tick = () => {
      if (document.visibilityState === "visible") void refreshGit(root);
    };
    const interval = setInterval(tick, GIT_POLL_MS);
    window.addEventListener("focus", tick);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", tick);
    };
  }, [root, refreshGit]);

  React.useLayoutEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const split = width === 0 || width >= SPLIT_MIN;
  // Narrow: the tree fills the panel until a file is open, then shows on demand.
  const showTree = split ? treeVisible : !file || treeOver;
  const treeAside = split ? Math.min(Math.max(treeWidth, TREE_MIN), Math.max(TREE_MIN, width - EDITOR_MIN)) : undefined;

  // Opening a file in a narrow panel puts the tree away.
  React.useEffect(() => {
    if (active) setTreeOver(false);
  }, [active]);

  // Focus the filter when nothing is open yet.
  React.useEffect(() => {
    if (!useFilesStore.getState().active) inputRef.current?.focus();
  }, []);

  const toggleTree = () => (split ? setTreeVisible(!treeVisible) : setTreeOver((v) => !v));
  const showTreeNow = () => (split ? setTreeVisible(true) : setTreeOver(true));

  function searchInFiles() {
    showTreeNow();
    if (!query.startsWith("?")) setQuery(`?${query}`);
    requestAnimationFrame(() => {
      const input = inputRef.current;
      input?.focus();
      input?.setSelectionRange(input.value.length, input.value.length);
    });
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-9 shrink-0 items-center gap-1 border-b border-border/60 px-1.5">
        <div
          role="tablist"
          aria-label="Open files"
          onWheel={(event) => {
            if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) event.currentTarget.scrollLeft += event.deltaY;
          }}
          className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none]"
        >
          {tabs.map((path) => (
            <FileTab key={path} path={path} active={path === active} dirty={!!files[path]?.dirty} />
          ))}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <IconButton label="Search in files" onClick={searchInFiles}>
            <SearchIcon />
          </IconButton>
          <IconButton label="Collapse folders" disabled={!showTree} onClick={() => collapseAll(root)}>
            <ChevronsDownUpIcon />
          </IconButton>
          <IconButton label={showTree ? "Hide file tree" : "Show file tree"} pressed={showTree} onClick={toggleTree}>
            <ListTreeIcon />
          </IconButton>
          <DropdownMenu>
            <DropdownMenuTrigger
              render={<Button variant="ghost" size="icon-xs" aria-label="More" className="shrink-0 text-muted-foreground" />}
            >
              <EllipsisIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuGroup>
                <DropdownMenuItem
                  onClick={() => {
                    listings.clear();
                    setGeneration((g) => g + 1);
                    if (root) void refreshGit(root, true);
                  }}
                >
                  Refresh
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={!active}
                  onClick={() => {
                    if (!active) return;
                    setQuery("");
                    showTreeNow();
                    requestAnimationFrame(() =>
                      revealInTree(root, active, containerRef.current?.querySelector("[role=tree]")?.parentElement ?? null),
                    );
                  }}
                >
                  Reveal open file
                </DropdownMenuItem>
                <DropdownMenuCheckboxItem checked={autoSave} onCheckedChange={(on) => setAutoSave(on)}>
                  Auto save
                </DropdownMenuCheckboxItem>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                disabled={tabs.length === 0}
                onClick={() => {
                  tabs.forEach(dropEditorState);
                  closeAll();
                }}
              >
                Close all files
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      <div ref={containerRef} className="relative flex min-h-0 flex-1">
        {(split || !showTree || treeOver) && (
          <section aria-label="Open file" className="min-w-0 flex-1">
            {file ? <FileView key={file.path} file={file} root={root} /> : <NoFileOpen />}
          </section>
        )}
        {showTree && (
          <aside
            aria-label="File tree"
            style={treeAside ? { width: treeAside } : undefined}
            className={cn(
              "flex min-h-0 flex-col bg-background",
              split
                ? "relative shrink-0 border-l border-border/60"
                : treeOver
                  ? "absolute inset-y-0 right-0 z-20 w-[min(20rem,88%)] border-l border-border/60 shadow-lg"
                  : "flex-1",
            )}
          >
            {split && <TreeResizer container={containerRef} />}
            {root ? (
              <Tree key={root} root={root} generation={generation} query={query} setQuery={setQuery} inputRef={inputRef} />
            ) : (
              <div className="flex h-full items-center justify-center">
                <Spinner className="size-4 text-muted-foreground" />
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}
