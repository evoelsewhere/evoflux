import * as React from "react";
import { BrainIcon, FolderOpenIcon, PencilIcon, PlusIcon, SearchIcon, Trash2Icon, XIcon } from "lucide-react";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { baseName, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";

// The Memory tool: what the agent keeps across chats (RPC `list_memories`,
// `save_memory`, `delete_memory`, `set_memory_enabled`;
// crates/evo-engine/src/memory.rs). Personal memories hold in every project,
// project ones in this chat's folder. The agent saves them with its `memory`
// tool; here you read, correct, add and remove them.

type Scope = "personal" | "project";
type MemoryType = "user" | "feedback" | "project" | "reference";

interface MemoryItem {
  name: string;
  description: string;
  type: MemoryType;
  content: string;
  updated: number;
  path: string;
  scope: Scope;
}

interface MemoryState {
  enabled: boolean;
  personal: { dir: string; items: MemoryItem[] };
  project: { dir: string; folder: string; items: MemoryItem[] };
}

const TYPES: { id: MemoryType; label: string; hint: string }[] = [
  { id: "user", label: "About you", hint: "Your role, expertise and preferences" },
  { id: "feedback", label: "How to work", hint: "Corrections and approaches you confirmed" },
  { id: "project", label: "Project", hint: "Goals, decisions and constraints of ongoing work" },
  { id: "reference", label: "Reference", hint: "Where things live outside the code" },
];
const typeLabel = (type: string) => TYPES.find((t) => t.id === type)?.label ?? type;

interface Draft {
  scope: Scope;
  name: string;
  description: string;
  type: MemoryType;
  content: string;
  /** The name being edited, when editing. */
  previous?: string;
}

function useMemories() {
  const chat = useEngineStore((s) => s.activeId);
  const ready = useEngineStore((s) => (s.activeId ? s.runtimes[s.activeId]?.status === "ready" : false));
  // A finished turn may have saved memories.
  const busy = useEngineStore((s) => (s.activeId ? Boolean(s.runtimes[s.activeId]?.transcript.busy) : false));
  const [state, setState] = React.useState<MemoryState | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const request = React.useCallback(async (command: string, args?: Record<string, unknown>) => {
    const engine = useEngineStore.getState();
    try {
      const next = await engine.request<MemoryState>(command, args);
      // An engine that does not know memory answers with something else.
      if (!next?.personal?.items || !next?.project?.items) throw new Error("this engine has no memory support; restart the app");
      setState(next);
      setError(null);
      if (command !== "list_memories") await engine.reloadIdleResources().catch(() => undefined);
      return true;
    } catch (e) {
      setError(String(e).replace(/^Error:\s*/, ""));
      return false;
    }
  }, []);

  React.useEffect(() => {
    if (ready && !busy) void request("list_memories");
  }, [ready, busy, chat, request]);

  return { state, error, ready, request };
}

function Editor({
  draft,
  onChange,
  onCancel,
  onSave,
  saving,
  canPickScope,
}: {
  draft: Draft;
  onChange(next: Draft): void;
  onCancel(): void;
  onSave(): void;
  saving: boolean;
  canPickScope: boolean;
}) {
  const field = "w-full rounded-md border border-border bg-background px-2 text-[13px] outline-none focus-visible:border-brand";
  return (
    <div
      className="flex flex-col gap-2 rounded-xl bg-muted/50 p-3 ring-1 ring-brand/30 dark:bg-accent/40"
      onKeyDown={(e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") onSave();
        if (e.key === "Escape") onCancel();
      }}
    >
      {canPickScope && (
        <div className="flex gap-1">
          {(["project", "personal"] as const).map((scope) => (
            <button
              key={scope}
              type="button"
              onClick={() => onChange({ ...draft, scope })}
              className={cn(
                "h-6 rounded-md px-2 text-xs transition-colors",
                draft.scope === scope ? "bg-brand/15 text-brand" : "text-muted-foreground hover:bg-accent",
              )}
            >
              {scope === "project" ? "This project" : "Every project"}
            </button>
          ))}
        </div>
      )}
      <input
        autoFocus
        value={draft.name}
        onChange={(e) => onChange({ ...draft, name: e.target.value })}
        placeholder="Name, e.g. prefers-small-commits"
        aria-label="Name"
        className={cn(field, "h-7 font-mono")}
      />
      <input
        value={draft.description}
        onChange={(e) => onChange({ ...draft, description: e.target.value })}
        placeholder="One line: what it is about"
        aria-label="Description"
        className={cn(field, "h-7")}
      />
      <div className="flex flex-wrap gap-1">
        {TYPES.map((type) => (
          <Tooltip key={type.id}>
            <TooltipTrigger
              render={
                <button
                  type="button"
                  onClick={() => onChange({ ...draft, type: type.id })}
                  className={cn(
                    "h-6 rounded-md px-2 text-xs transition-colors",
                    draft.type === type.id ? "bg-brand/15 text-brand" : "text-muted-foreground hover:bg-accent",
                  )}
                />
              }
            >
              {type.label}
            </TooltipTrigger>
            <TooltipContent>{type.hint}</TooltipContent>
          </Tooltip>
        ))}
      </div>
      <textarea
        value={draft.content}
        onChange={(e) => onChange({ ...draft, content: e.target.value })}
        placeholder={"What to remember.\nFor how-to-work and project memories, add why and how to apply it."}
        aria-label="Memory"
        className={cn(field, "field-sizing-content min-h-24 max-h-80 resize-none py-1.5 leading-5")}
      />
      <div className="flex items-center justify-end gap-1.5">
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button size="sm" onClick={onSave} disabled={saving || !draft.name.trim() || !draft.content.trim()} className="gap-1.5">
          {saving && <Spinner className="size-3.5" />}
          Save
        </Button>
      </div>
    </div>
  );
}

function MemoryCard({
  item,
  open,
  onToggle,
  onEdit,
  onDelete,
}: {
  item: MemoryItem;
  open: boolean;
  onToggle(): void;
  onEdit(): void;
  onDelete(): void;
}) {
  const [confirming, setConfirming] = React.useState(false);
  return (
    <div className={cn("group/memory rounded-lg transition-colors", open ? "bg-muted/60 dark:bg-accent/40" : "hover:bg-accent/50")}>
      <button type="button" onClick={onToggle} className="flex w-full flex-col gap-0.5 px-2.5 py-2 text-left">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate font-mono text-[12.5px] font-medium">{item.name}</span>
          <span className="shrink-0 rounded bg-brand/10 px-1.5 text-[10.5px] leading-4 text-brand">{typeLabel(item.type)}</span>
          <span className="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">{formatRelative(item.updated)}</span>
        </span>
        <span className={cn("text-xs leading-4 text-muted-foreground", !open && "line-clamp-2")}>{item.description}</span>
      </button>
      {open && (
        <div className="flex flex-col gap-2 px-2.5 pb-2.5">
          <div className="rounded-md bg-background px-3 py-2 text-[13px] ring-1 ring-border/70">
            <Markdown>{item.content}</Markdown>
          </div>
          <div className="flex items-center gap-1">
            {confirming ? (
              <>
                <span className="text-xs text-muted-foreground">Forget this memory?</span>
                <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" onClick={() => setConfirming(false)}>
                  Keep
                </Button>
                <Button size="sm" variant="destructive" className="h-6 px-2 text-xs" onClick={onDelete}>
                  Forget
                </Button>
              </>
            ) : (
              <>
                <Button size="sm" variant="ghost" className="h-6 gap-1 px-2 text-xs" onClick={onEdit}>
                  <PencilIcon className="size-3" /> Edit
                </Button>
                <Button size="sm" variant="ghost" className="h-6 gap-1 px-2 text-xs" onClick={() => setConfirming(true)}>
                  <Trash2Icon className="size-3" /> Forget
                </Button>
                <span className="flex-1" />
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="Show in folder"
                  className="size-6 text-muted-foreground"
                  onClick={() => void revealItemInDir(item.path).catch(() => undefined)}
                >
                  <FolderOpenIcon className="size-3.5" />
                </Button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function MemoryPanel() {
  const { state, error, ready, request } = useMemories();
  const [query, setQuery] = React.useState("");
  const [filter, setFilter] = React.useState<"all" | MemoryType>("all");
  const [open, setOpen] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState<Draft | null>(null);
  const [saving, setSaving] = React.useState(false);

  if (!state) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-[13px] text-muted-foreground">
        {error ? `Could not read memory: ${error}` : ready ? <Spinner className="size-4" /> : "Open a chat to see its memory."}
      </div>
    );
  }

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    const { scope, name, description, type, content, previous } = draft;
    const ok = await request("save_memory", { scope, name, description, kind: type, content, previous });
    setSaving(false);
    if (ok) {
      setDraft(null);
      setOpen(`${scope}:${name}`);
    }
  };

  const q = query.trim().toLowerCase();
  const matches = (m: MemoryItem) =>
    (filter === "all" || m.type === filter) &&
    (!q || `${m.name} ${m.description} ${m.content}`.toLowerCase().includes(q));
  const groups: { scope: Scope; title: string; hint: string; items: MemoryItem[] }[] = [
    {
      scope: "project",
      title: `This project · ${baseName(state.project.folder)}`,
      hint: "Kept outside the repository",
      items: state.project.items.filter(matches),
    },
    { scope: "personal", title: "Every project", hint: "About you and how you work", items: state.personal.items.filter(matches) },
  ];
  const total = state.personal.items.length + state.project.items.length;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 flex-col gap-2 border-b border-border/60 px-3 py-2.5">
        <div className="flex items-center gap-2">
          <BrainIcon className="size-4 text-brand" />
          <h2 className="text-[13px] font-semibold">Memory</h2>
          <span className="text-xs text-muted-foreground tabular-nums">{total}</span>
          <span className="flex-1" />
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="Add a memory"
                  disabled={!state.enabled}
                  onClick={() => setDraft({ scope: "project", name: "", description: "", type: "user", content: "" })}
                />
              }
            >
              <PlusIcon />
            </TooltipTrigger>
            <TooltipContent>Add a memory</TooltipContent>
          </Tooltip>
          <Switch
            aria-label="Memory on"
            checked={state.enabled}
            onCheckedChange={(on) => void request("set_memory_enabled", { enabled: on })}
          />
        </div>
        {state.enabled && total > 0 && (
          <>
            <label className="flex h-7 items-center gap-1.5 rounded-md bg-muted/70 px-2 text-xs dark:bg-accent/50">
              <SearchIcon className="size-3.5 text-muted-foreground" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search memories"
                className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
              />
              {query && (
                <button type="button" aria-label="Clear" onClick={() => setQuery("")} className="text-muted-foreground">
                  <XIcon className="size-3.5" />
                </button>
              )}
            </label>
            <div className="flex flex-wrap gap-1">
              {(["all", ...TYPES.map((t) => t.id)] as const).map((id) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setFilter(id)}
                  className={cn(
                    "h-6 rounded-md px-2 text-xs transition-colors",
                    filter === id ? "bg-brand/15 text-brand" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )}
                >
                  {id === "all" ? "All" : typeLabel(id)}
                </button>
              ))}
            </div>
          </>
        )}
      </header>

      <div className="scrollbar-slim min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {error && <p className="mb-2 px-1 text-xs text-destructive">{error}</p>}
        {!state.enabled ? (
          <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
            <BrainIcon className="size-6 text-muted-foreground" />
            <p className="text-[13px] font-medium">Memory is off</p>
            <p className="text-xs text-balance text-muted-foreground">
              Chats neither read nor save memories. Your {total} saved {total === 1 ? "memory stays" : "memories stay"} on disk.
            </p>
          </div>
        ) : (
          <>
            {draft && !draft.previous && (
              <div className="mb-3">
                <Editor draft={draft} onChange={setDraft} onCancel={() => setDraft(null)} onSave={() => void save()} saving={saving} canPickScope />
              </div>
            )}
            {total === 0 && !draft ? (
              <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
                <BrainIcon className="size-6 text-brand" />
                <p className="text-[13px] font-medium">Nothing remembered yet</p>
                <p className="text-xs text-balance text-muted-foreground">
                  The agent saves what will help in later chats — your preferences, corrections, project decisions. Ask it
                  directly too: “remember that we deploy on Fridays”.
                </p>
              </div>
            ) : (
              groups.map((group) => (
                <section key={group.scope} className="mb-3 flex flex-col gap-0.5">
                  <p className="flex items-baseline gap-1.5 px-2 pb-1 text-[11px] font-medium text-muted-foreground">
                    <span className="truncate">{group.title}</span>
                    <span className="shrink-0 font-normal opacity-70">{group.hint}</span>
                  </p>
                  {group.items.length === 0 ? (
                    <p className="px-2 pb-1 text-xs text-muted-foreground/80">{q || filter !== "all" ? "No matches" : "None yet"}</p>
                  ) : (
                    group.items.map((item) => {
                      const key = `${item.scope}:${item.name}`;
                      return draft?.previous === item.name && draft.scope === item.scope ? (
                        <Editor
                          key={key}
                          draft={draft}
                          onChange={setDraft}
                          onCancel={() => setDraft(null)}
                          onSave={() => void save()}
                          saving={saving}
                          canPickScope={false}
                        />
                      ) : (
                        <MemoryCard
                          key={key}
                          item={item}
                          open={open === key}
                          onToggle={() => setOpen(open === key ? null : key)}
                          onEdit={() =>
                            setDraft({
                              scope: item.scope,
                              name: item.name,
                              description: item.description,
                              type: item.type,
                              content: item.content,
                              previous: item.name,
                            })
                          }
                          onDelete={() => void request("delete_memory", { scope: item.scope, name: item.name })}
                        />
                      );
                    })
                  )}
                </section>
              ))
            )}
          </>
        )}
      </div>
    </div>
  );
}
