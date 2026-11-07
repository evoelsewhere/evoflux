import * as React from "react";
import { FolderIcon, FolderOpenIcon, FolderUpIcon, ShieldAlertIcon, UserRoundIcon } from "lucide-react";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Spinner } from "@/components/ui/spinner";
import { baseName } from "@/lib/format";
import { modKey } from "@/lib/platform";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { Badge, EmptyNote, IconAction, ListRow, Split } from "./customize-parts";

// Customize → Instructions: standing text added to the agent's system prompt,
// in the instruction files the engine already reads (RPC `list_instructions`
// / `save_instructions`, crates/evo-engine/src/instructions.rs): yours for
// every chat, the project's for chats in that folder, and the parent folders'
// files, shown read-only.

interface InstructionFile {
  path: string;
  exists: boolean;
  content: string;
  tooLarge: boolean;
  folder?: string;
}

interface InstructionsState {
  personal: InstructionFile;
  project: InstructionFile | null;
  parents: InstructionFile[];
  trusted: boolean;
}

type Scope = "personal" | "project";
type Selection = Scope | `parent:${number}`;

const EXAMPLE = `- Reply in the language I write in; keep code and identifiers in English.
- Prefer small, focused changes; explain the plan before large edits.
- Run the tests after changing code.`;

const folderOf = (path: string) => path.replace(/[\\/][^\\/]*$/, "");

function lineCount(text: string) {
  const lines = text.trim() ? text.trim().split("\n").length : 0;
  return lines === 1 ? "1 line" : `${lines} lines`;
}

function Editor({
  scope,
  file,
  draft,
  onDraft,
  onSave,
  saving,
  trusted,
}: {
  scope: Scope;
  file: InstructionFile;
  draft: string;
  onDraft(text: string): void;
  onSave(): void;
  saving: boolean;
  trusted: boolean;
}) {
  const [mode, setMode] = React.useState<"edit" | "preview">("edit");
  const dirty = draft !== file.content;
  const personal = scope === "personal";
  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand/12 text-brand">
          {personal ? <UserRoundIcon className="size-5" /> : <FolderIcon className="size-5" />}
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold">
              {personal ? "Personal instructions" : `Instructions for ${baseName(file.folder ?? folderOf(file.path))}`}
            </h2>
            <Badge>{personal ? "Every chat" : "This project"}</Badge>
            {!file.exists && <Badge>Not created yet</Badge>}
          </div>
          <p className="text-[13px] leading-relaxed text-muted-foreground">
            {personal
              ? "How you like to work: language, tone, habits. Added to every chat, in every project."
              : "Conventions for this codebase: how to build and test, style, what to avoid. Added to chats in this folder; it lives in the project, so it can be shared with your team."}
          </p>
        </div>
        {file.exists && (
          <IconAction label="Show in folder" onClick={() => void revealItemInDir(file.path).catch(() => undefined)}>
            <FolderOpenIcon />
          </IconAction>
        )}
      </header>

      {!personal && !trusted && (
        <div className="flex items-start gap-2 rounded-xl bg-status-warn/10 px-3 py-2 text-[13px]">
          <ShieldAlertIcon className="mt-0.5 size-4 shrink-0 text-status-warn" />
          <span>This folder is not trusted yet, so chats here do not read its files. Trust the folder to use these instructions.</span>
        </div>
      )}

      <div className="flex flex-col overflow-hidden rounded-xl ring-1 ring-border focus-within:ring-brand/50">
        <div className="flex items-center gap-1 border-b border-border/60 bg-muted/40 px-2 py-1 dark:bg-accent/30">
          {(["edit", "preview"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={cn(
                "h-6 rounded-md px-2 text-xs capitalize transition-colors",
                mode === m ? "bg-background text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {m}
            </button>
          ))}
          <span className="ml-auto truncate font-mono text-[11px] text-muted-foreground" title={file.path}>
            {file.path}
          </span>
        </div>
        {mode === "edit" ? (
          <textarea
            value={draft}
            readOnly={file.tooLarge}
            onChange={(e) => onDraft(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
                e.preventDefault();
                if (dirty) onSave();
              }
            }}
            placeholder={EXAMPLE}
            spellCheck={false}
            aria-label={personal ? "Personal instructions" : "Project instructions"}
            className="field-sizing-content min-h-72 w-full resize-none bg-background px-4 py-3 font-mono text-[13px] leading-6 outline-none placeholder:text-muted-foreground/70 focus-visible:shadow-none"
          />
        ) : (
          <div className="min-h-72 bg-background px-4 py-3 text-[13px]">
            {draft.trim() ? <Markdown>{draft}</Markdown> : <p className="text-muted-foreground">Nothing yet.</p>}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">
          {file.tooLarge
            ? "Too large to edit here; open the file."
            : dirty
              ? draft.trim()
                ? "Unsaved changes"
                : "Saving empty text removes the file"
              : file.exists
                ? `${lineCount(file.content)} · applies from the next message`
                : "Write in plain markdown."}
        </span>
        <span className="flex-1" />
        {dirty && (
          <Button size="sm" variant="ghost" onClick={() => onDraft(file.content)}>
            Revert
          </Button>
        )}
        <Button size="sm" disabled={!dirty || saving || file.tooLarge} onClick={onSave} className="gap-2">
          {saving && <Spinner className="size-3.5" />}
          Save
          <Kbd className="bg-transparent text-current opacity-70">{modKey}+S</Kbd>
        </Button>
      </div>
    </div>
  );
}

function ParentView({ file }: { file: InstructionFile }) {
  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground dark:bg-accent">
          <FolderUpIcon className="size-5" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold">{baseName(folderOf(file.path))}</h2>
            <Badge>Parent folder</Badge>
          </div>
          <p className="text-[13px] leading-relaxed text-muted-foreground">
            Chats in this project also read the instruction files of the folders above it.
          </p>
        </div>
        <IconAction label="Show in folder" onClick={() => void revealItemInDir(file.path).catch(() => undefined)}>
          <FolderOpenIcon />
        </IconAction>
      </header>
      <div className="rounded-xl px-4 py-3 text-[13px] ring-1 ring-border">
        <Markdown>{file.content || "_Empty_"}</Markdown>
      </div>
      <p className="truncate font-mono text-[11px] text-muted-foreground" title={file.path}>
        {file.path}
      </p>
    </div>
  );
}

export function InstructionsSection() {
  const engineReady = useEngineStore((s) => (s.activeId ? s.runtimes[s.activeId]?.status === "ready" : false));
  const activeId = useEngineStore((s) => s.activeId);
  const [state, setState] = React.useState<InstructionsState | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<Selection>("personal");
  const [drafts, setDrafts] = React.useState<Partial<Record<Scope, string>>>({});
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (!engineReady) return;
    let live = true;
    useEngineStore
      .getState()
      .request<InstructionsState>("list_instructions")
      .then((next) => {
        if (!live) return;
        setState(next);
        setError(null);
        setDrafts({});
      })
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [engineReady, activeId]);

  if (!state) {
    return (
      <div className="flex flex-1 items-center justify-center">
        {error ? (
          <p className="max-w-sm text-center text-[13px] text-muted-foreground">Could not read instructions: {error}</p>
        ) : engineReady ? (
          <Spinner className="size-4 text-muted-foreground" />
        ) : (
          <p className="max-w-sm text-center text-[13px] text-muted-foreground">Open a chat to edit instructions.</p>
        )}
      </div>
    );
  }

  const fileOf = (scope: Scope) => (scope === "personal" ? state.personal : state.project);
  const draftOf = (scope: Scope) => drafts[scope] ?? fileOf(scope)?.content ?? "";
  const dirty = (scope: Scope) => drafts[scope] !== undefined && drafts[scope] !== fileOf(scope)?.content;

  const save = async (scope: Scope) => {
    setSaving(true);
    try {
      const engine = useEngineStore.getState();
      const next = await engine.request<InstructionsState>("save_instructions", { scope, content: draftOf(scope) });
      setState(next);
      setDrafts((d) => ({ ...d, [scope]: undefined }));
      setError(null);
      // Other idle chats re-read their instruction files too.
      await engine.reloadIdleResources().catch(() => undefined);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const parentIndex = selected.startsWith("parent:") ? Number(selected.slice(7)) : -1;
  const current: Scope | null = selected === "personal" || (selected === "project" && state.project) ? (selected as Scope) : null;
  const meta = (scope: Scope) => {
    const file = fileOf(scope);
    if (dirty(scope)) return <span className="size-1.5 shrink-0 rounded-full bg-brand" aria-label="Unsaved" />;
    return (
      <span className="shrink-0 text-[11px] text-muted-foreground">{file?.exists ? lineCount(file.content) : "Empty"}</span>
    );
  };

  return (
    <Split
      intro="Standing instructions the agent follows in every reply. Write them as plain markdown."
      list={
        <>
          <div className="flex flex-col gap-0.5">
            <p className="px-2.5 pt-3 pb-1 text-[11px] font-medium text-muted-foreground">Yours</p>
            <ListRow
              selected={selected === "personal"}
              onSelect={() => setSelected("personal")}
              icon={<UserRoundIcon />}
              title="Personal"
              meta={meta("personal")}
              description="Every chat, every project"
            />
          </div>
          {state.project && (
            <div className="flex flex-col gap-0.5">
              <p className="px-2.5 pt-3 pb-1 text-[11px] font-medium text-muted-foreground">This project</p>
              <ListRow
                selected={selected === "project"}
                onSelect={() => setSelected("project")}
                icon={<FolderIcon />}
                title={baseName(state.project.folder ?? folderOf(state.project.path))}
                meta={meta("project")}
                description={state.trusted ? "Chats in this folder" : "Not read until the folder is trusted"}
                dimmed={!state.trusted}
              />
            </div>
          )}
          {state.parents.length > 0 && (
            <div className="flex flex-col gap-0.5">
              <p className="px-2.5 pt-3 pb-1 text-[11px] font-medium text-muted-foreground">Also read</p>
              {state.parents.map((file, index) => (
                <ListRow
                  key={file.path}
                  selected={parentIndex === index}
                  onSelect={() => setSelected(`parent:${index}`)}
                  icon={<FolderUpIcon />}
                  title={baseName(folderOf(file.path))}
                  description={file.content.trim().split("\n")[0] ?? ""}
                />
              ))}
            </div>
          )}
          {!state.project && (
            <EmptyNote title="No project">
              Open a chat in a project folder to give that project its own instructions.
            </EmptyNote>
          )}
        </>
      }
      detail={
        <>
          {error && <p className="mb-3 text-xs text-destructive">{error}</p>}
          {current ? (
            <Editor
              key={current}
              scope={current}
              file={fileOf(current)!}
              draft={draftOf(current)}
              onDraft={(text) => setDrafts((d) => ({ ...d, [current]: text }))}
              onSave={() => void save(current)}
              saving={saving}
              trusted={state.trusted}
            />
          ) : parentIndex >= 0 && state.parents[parentIndex] ? (
            <ParentView file={state.parents[parentIndex]} />
          ) : null}
        </>
      }
    />
  );
}
