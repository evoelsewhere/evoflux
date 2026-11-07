import * as React from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { AtSignIcon, ChevronDownIcon, PaperclipIcon, PlugIcon, PlusIcon, ShieldCheckIcon, SlashIcon } from "lucide-react";
import { ModelSelector } from "@/components/ai-elements/model-selector";
import { PromptInput, type PromptAttachment } from "@/components/ai-elements/prompt-input";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { InputGroupButton } from "@/components/ui/input-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { UNCONFIGURED_PROVIDER } from "@/engine/protocol";
import { composeAnnotatedMessage } from "@/lib/document-annotations";
import { mcp, type Connector } from "@/lib/mcp";
import { cn } from "@/lib/utils";
import { useAnnotationsStore } from "@/stores/annotations-store";
import { useConnectorsStore } from "@/stores/connectors-store";
import { useCustomizeStore } from "@/stores/customize-store";
import { useEngineStore } from "@/stores/engine-store";
import { useUiStore, type ApprovalMode } from "@/stores/ui-store";
import { ComposerAnnotations } from "./annotation-chips";
import { CommandMenu, commandItems, leadingCommand, matchCommands, type CommandItem } from "./command-menu";
import {
  attachmentsFromPaths,
  attachmentsFromTransfer,
  buildPrompt,
  fileAttachment,
  isLongPaste,
  releaseAttachment,
  textAttachment,
} from "./composer-input";
import { QueuedMessages } from "./queued-messages";

const approvals: { id: ApprovalMode; name: string; hint: string }[] = [
  { id: "ask", name: "Ask every time", hint: "Approve each tool call" },
  { id: "auto-edits", name: "Approve edits", hint: "Edits run, commands ask" },
  { id: "auto", name: "Approve for me", hint: "Everything runs" },
];

/** A draft the empty state or a suggestion can prefill. */
export const composerDraft = {
  listeners: new Set<(text: string) => void>(),
  attachListeners: new Set<(path: string) => void>(),
  set(text: string) {
    for (const listener of this.listeners) listener(text);
  },
  /** Attach a file or folder to the next message (Files tool → Attach as context). */
  attach(path: string) {
    for (const listener of this.attachListeners) listener(path);
  },
};

export function ChatComposer() {
  const [text, setText] = React.useState("");
  const [attachments, setAttachments] = React.useState<PromptAttachment[]>([]);
  const status = useEngineStore((s) => s.status);
  const busy = useEngineStore((s) => s.transcript.busy);
  const models = useEngineStore((s) => s.models);
  const state = useEngineStore((s) => s.state);
  const unconfigured = state.provider === UNCONFIGURED_PROVIDER;
  const thinkingLevels = useEngineStore((s) => s.thinkingLevels);
  const defaultModel = useEngineStore((s) => s.defaultModel);
  const pinnedModels = useUiStore((s) => s.pinnedModels);
  const { sendPrompt, queueMessage, abort, setModel, setThinkingLevel, setDefaultModel } = useEngineStore.getState();
  const queuedCount = useEngineStore((s) => s.transcript.queued?.length ?? 0);
  const [problem, setProblem] = React.useState<string | null>(null);
  const [dropping, setDropping] = React.useState(false);
  const chatId = useEngineStore((s) => s.activeId);
  const approval = useUiStore((s) => s.approval);
  const setApproval = useUiStore((s) => s.setApproval);
  const ready = status === "ready";
  const customizations = useCustomizeStore((s) => s.data);
  const connectors = useConnectorsStore((s) => s.servers);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  // The `/` menu: open while the name after `/` is being typed, until Esc.
  const [menuActive, setMenuActive] = React.useState(0);
  const [menuDismissed, setMenuDismissed] = React.useState(false);
  const items = React.useMemo(() => commandItems(customizations, connectors), [customizations, connectors]);
  const slash = /^\/(\S*)$/.exec(text);
  const query = slash?.[1] ?? "";
  const matches = React.useMemo(() => (slash ? matchCommands(items, query) : []), [items, query, slash !== null]);
  const menuOpen = !!slash && !menuDismissed && ready;
  const command = leadingCommand(text, items);

  // Skills and commands are read when the menu could open, and once ready.
  React.useEffect(() => {
    if (ready) void useCustomizeStore.getState().load();
  }, [ready]);
  React.useEffect(() => {
    if (menuOpen) void useCustomizeStore.getState().load();
  }, [menuOpen]);
  React.useEffect(() => setMenuActive(0), [query]);

  React.useEffect(() => {
    const listener = (draft: string) => setText(draft);
    composerDraft.listeners.add(listener);
    const attachListener = (path: string) => addAttachments([fileAttachment(path)]);
    composerDraft.attachListeners.add(attachListener);
    return () => {
      composerDraft.listeners.delete(listener);
      composerDraft.attachListeners.delete(attachListener);
    };
  }, []);

  /** Add attachments, skipping a path already attached. */
  function addAttachments(list: PromptAttachment[]) {
    if (list.length === 0) return;
    setProblem(null);
    setAttachments((current) => [...current, ...list.filter((file) => !current.some((c) => c.id === file.id))]);
  }

  function removeAttachment(id: string) {
    setAttachments((current) => {
      const gone = current.find((file) => file.id === id);
      if (gone) releaseAttachment(gone);
      return current.filter((file) => file.id !== id);
    });
  }

  async function attach() {
    const files = await open({ multiple: true, title: "Attach files" });
    const list = Array.isArray(files) ? files : files ? [files] : [];
    addAttachments(await attachmentsFromPaths(list));
  }

  /** Pictures and files from the clipboard; long text becomes an attachment. */
  function onPaste(event: React.ClipboardEvent<HTMLTextAreaElement>) {
    const data = event.clipboardData;
    const hasFiles = data.files.length > 0 || [...data.items].some((item) => item.kind === "file");
    if (hasFiles) {
      event.preventDefault();
      void attachmentsFromTransfer(data)
        .then(addAttachments)
        .catch((error) => setProblem(String(error)));
      return;
    }
    const pasted = data.getData("text/plain");
    if (pasted && isLongPaste(pasted)) {
      event.preventDefault();
      addAttachments([textAttachment(pasted)]);
    }
  }

  // Files dragged from the system onto the window attach to the message.
  React.useEffect(() => {
    let stop: (() => void) | undefined;
    let live = true;
    // Outside Tauri (a browser preview) there is no webview: no drops.
    let webview: ReturnType<typeof getCurrentWebview>;
    try {
      webview = getCurrentWebview();
    } catch {
      return;
    }
    void webview
      .onDragDropEvent((event) => {
        const kind = event.payload.type;
        setDropping(kind === "enter" || kind === "over");
        if (kind === "drop" && event.payload.paths.length > 0) {
          void attachmentsFromPaths(event.payload.paths).then(addAttachments);
          textareaRef.current?.focus();
        }
      })
      .then((unlisten) => {
        if (live) stop = unlisten;
        else unlisten();
      })
      .catch(() => undefined);
    return () => {
      live = false;
      stop?.();
    };
  }, []);

  /** Run a command the app handles itself. */
  function runBuiltin(name: string) {
    const engine = useEngineStore.getState();
    if (name === "clear") void engine.newChat();
    else if (name === "compact") void engine.compact();
    else if (name === "fork" && engine.activeId) void engine.forkChat(engine.activeId);
    else if (name === "customize") useUiStore.getState().openCustomize();
    setText("");
  }

  /**
   * Send `message` with the attachments and the chat's document annotations
   * (their block goes last, docs/features/office-v3-parity/sdd.md). While the
   * agent works it is read at its next step, or with `queue` once it
   * finishes; otherwise it starts a turn.
   */
  async function send(message: string, queue = false) {
    const files = attachments;
    const chat = useEngineStore.getState().activeId;
    const annotations = chat ? (useAnnotationsStore.getState().pending[chat] ?? []) : [];
    setText("");
    setAttachments([]);
    setProblem(null);
    if (chat && annotations.length > 0) useAnnotationsStore.getState().clear(chat);
    try {
      const prompt = await buildPrompt(await withResources(message), files);
      const text = composeAnnotatedMessage(prompt.text, annotations);
      if (useEngineStore.getState().transcript.busy) {
        await queueMessage(text, prompt.images, queue ? "followUp" : "steer");
      } else {
        await sendPrompt(text, prompt.images);
      }
      files.forEach(releaseAttachment);
    } catch (error) {
      // Put everything back so nothing is lost.
      setText((current) => current || message);
      setAttachments((current) => (current.length ? current : files));
      if (chat) useAnnotationsStore.getState().restore(chat, annotations);
      setProblem(error instanceof Error ? error.message : String(error));
    }
  }

  // The viewer's "Send now" sends the batch (with whatever is typed) through
  // this composer, as Enter would.
  const submitRequest = useAnnotationsStore((s) => s.submitRequest);
  const pendingAnnotations = useAnnotationsStore((s) => (chatId ? (s.pending[chatId]?.length ?? 0) : 0));
  const handledSubmit = React.useRef(submitRequest?.nonce ?? 0);
  // The effect runs with this render's `send`, `text` and state.
  React.useEffect(() => {
    if (!submitRequest || submitRequest.chatId !== chatId) return;
    if (submitRequest.nonce === handledSubmit.current) return;
    handledSubmit.current = submitRequest.nonce;
    // As v3: nothing is sent while the engine starts or a `/command` is being typed.
    if (!ready || slash !== null) return;
    void send(text, false);
  }, [chatId, submitRequest]);

  /**
   * `@server:uri` of a connected connector: read the resource and add it to
   * the message (the mention stays where it was typed).
   */
  async function withResources(message: string): Promise<string> {
    const known = new Map(
      useConnectorsStore
        .getState()
        .servers.filter((c) => c.status === "connected" && !c.project)
        .map((c) => [c.name, c] as const),
    );
    const mentions = [...message.matchAll(/(^|\s)@([A-Za-z0-9_-]+):(\S+)/g)].filter((m) => known.has(m[2]));
    if (!mentions.length) return message;
    const blocks = await Promise.all(
      mentions.map(async ([, , server, uri]) => {
        const text = await mcp.readResource(server, uri);
        return `<resource server="${server}" uri="${uri.replace(/"/g, "&quot;")}">\n${text}\n</resource>`;
      }),
    );
    return `${message}\n\n${blocks.join("\n\n")}`;
  }

  /** Stop the run; messages it never read go back into the field. */
  async function stop() {
    const unread = await abort();
    if (unread.length) setText((current) => [...unread, current].filter((part) => part.trim()).join("\n\n"));
  }

  // A message that reached the engine just as the run ended stays queued for
  // the next one: send what is left as a new turn.
  React.useEffect(() => {
    if (busy || queuedCount === 0) return;
    const engine = useEngineStore.getState();
    const left = engine.transcript.queued ?? [];
    void engine.request("clear_queue").then(() => {
      for (const item of left) void engine.cancelQueued(item.entryId);
      const text = left.map((item) => item.text).join("\n\n");
      if (text.trim()) void engine.sendPrompt(text);
    });
  }, [busy, queuedCount]);

  /** A connector's prompt: its server fills it in, and that text is sent. */
  async function runMcpPrompt(item: CommandItem, rest: string) {
    if (!item.mcp) return;
    const words = rest.trim() ? rest.trim().split(/\s+/) : [];
    const args: Record<string, string> = {};
    item.mcp.args.forEach((name, index) => {
      // The last argument takes the rest of the line.
      const value = index === item.mcp!.args.length - 1 ? words.slice(index).join(" ") : words[index];
      if (value) args[name] = value;
    });
    setText("");
    try {
      const prompt = await mcp.getPrompt(item.mcp.server, item.mcp.prompt, args);
      void send(prompt || `/${item.name} ${rest}`.trim());
    } catch (error) {
      // Put it back so nothing typed is lost.
      setText(`/${item.name} ${rest}`.trim());
      console.warn(`[connectors] ${item.name}: ${String(error)}`);
    }
  }

  function submit(queue: boolean) {
    if (command?.kind === "builtin") return runBuiltin(command.name);
    if (command?.kind === "mcp") return void runMcpPrompt(command, text.slice(command.name.length + 1));
    void send(text, queue);
  }

  /** Tab, or a command that takes arguments: put it in the input. Enter otherwise runs it. */
  function pick(item: CommandItem, how: "run" | "complete") {
    setMenuDismissed(false);
    if (item.kind === "builtin" && how === "run") return runBuiltin(item.name);
    if (item.kind === "mcp" && how === "run" && !item.argumentHint) return void runMcpPrompt(item, "");
    if (how === "complete" || item.argumentHint) {
      setText(`/${item.name} `);
      requestAnimationFrame(() => textareaRef.current?.focus());
      return;
    }
    void send(`/${item.name}`);
  }

  function onMenuKey(event: React.KeyboardEvent<HTMLTextAreaElement>): boolean {
    if (!menuOpen || event.nativeEvent.isComposing) return false;
    if (event.key === "Escape") {
      event.preventDefault();
      setMenuDismissed(true);
      return true;
    }
    if (matches.length === 0) return false;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setMenuActive((index) => (index + step + matches.length) % matches.length);
      return true;
    }
    if (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey)) {
      event.preventDefault();
      const item = matches[Math.min(menuActive, matches.length - 1)];
      if (item) pick(item, event.key === "Tab" ? "complete" : "run");
      return true;
    }
    return false;
  }

  const currentApproval = approvals.find((a) => a.id === approval) ?? approvals[0];

  return (
    <PromptInput
      canSubmitEmpty={pendingAnnotations > 0}
      value={text}
      onChange={(value) => {
        if (!value.startsWith("/")) setMenuDismissed(false);
        setText(value);
      }}
      textareaRef={textareaRef}
      onKeyDownCapture={onMenuKey}
      highlight={command ? { length: command.name.length + 1, hint: command.argumentHint } : null}
      popover={
        menuOpen ? (
          <CommandMenu
            items={matches}
            query={query}
            active={Math.min(menuActive, Math.max(0, matches.length - 1))}
            onActiveChange={setMenuActive}
            onPick={(item) => pick(item, "run")}
          />
        ) : null
      }
      onSubmit={submit}
      onStop={() => void stop()}
      onPaste={onPaste}
      dropActive={dropping}
      header={
        <>
          <QueuedMessages
            onEdit={(queued) => {
              setText((current) => [current, queued].filter((part) => part.trim()).join("\n\n"));
              requestAnimationFrame(() => textareaRef.current?.focus());
            }}
          />
          <ComposerAnnotations chatId={chatId} />
          {problem && (
            <p role="alert" className="mx-3 mb-1.5 text-xs text-destructive">
              {problem}
            </p>
          )}
        </>
      }
      busy={busy}
      disabled={!ready}
      placeholder={
        !ready
          ? "Starting the engine…"
          : busy
            ? "Enter to send now, Ctrl+Enter to queue for later"
            : "Ask anything — @ to tag files, / for commands"
      }
      attachments={attachments}
      onRemoveAttachment={removeAttachment}
      leading={
        <PlusMenu
          connectors={connectors}
          onAttach={() => void attach()}
          onCommands={() => {
            setText("/");
            requestAnimationFrame(() => textareaRef.current?.focus());
          }}
          onResource={(mention) => {
            setText((current) => `${current}${current && !current.endsWith(" ") ? " " : ""}${mention} `);
            requestAnimationFrame(() => textareaRef.current?.focus());
          }}
        />
      }
      toolbar={
        <>
          <ModelSelector
            models={models}
            provider={unconfigured ? undefined : state.provider}
            modelId={unconfigured ? undefined : (state.modelId ?? state.model)}
            defaultModel={defaultModel}
            pinned={pinnedModels}
            thinkingLevel={state.thinkingLevel}
            thinkingLevels={thinkingLevels}
            disabled={!ready || busy}
            onModelChange={(model) => void setModel(model)}
            onPinnedChange={(keys) => useUiStore.getState().setPinnedModels(keys)}
            onDefaultChange={(model) => void setDefaultModel(model)}
            onThinkingChange={(level) => void setThinkingLevel(level)}
          />
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <InputGroupButton
                  size="sm"
                  variant="ghost"
                  aria-label={`Approvals: ${currentApproval.name}`}
                  title={currentApproval.name}
                />
              }
            >
              <ShieldCheckIcon />
              <span className="hidden @2xl:inline">{currentApproval.name}</span>
              <ChevronDownIcon className="hidden @2xl:block" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" side="top" className="w-56">
              <DropdownMenuGroup>
                <DropdownMenuLabel>Approvals</DropdownMenuLabel>
                <DropdownMenuRadioGroup value={approval} onValueChange={(value) => setApproval(value as ApprovalMode)}>
                  {approvals.map((item) => (
                    <DropdownMenuRadioItem key={item.id} value={item.id} closeOnClick>
                      <div className="flex flex-col">
                        <span>{item.name}</span>
                        <span className="text-xs text-muted-foreground">{item.hint}</span>
                      </div>
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      }
    />
  );
}

const dot: Record<string, string> = {
  connected: "bg-status-ok",
  connecting: "bg-amber-500",
  "needs-auth": "bg-amber-500",
  failed: "bg-destructive",
  off: "bg-muted-foreground/40",
};

/**
 * The composer's + menu: attach files, browse commands, switch connectors on
 * or off for this chat, and mention a connector's resources.
 */
function PlusMenu({
  connectors,
  onAttach,
  onCommands,
  onResource,
}: {
  connectors: Connector[];
  onAttach(): void;
  onCommands(): void;
  onResource(mention: string): void;
}) {
  const chat = useEngineStore((s) => s.activeId);
  const off = useUiStore((s) => (chat ? s.chatConnectorsOff[chat] : undefined)) ?? [];
  const cwd = useEngineStore((s) => s.cwd);
  // Your connectors, and the approved servers of this chat's project.
  const shown = connectors.filter((c) => !c.project || (cwd && c.project && cwdIn(cwd, c.project)));
  const withResources = shown.filter((c) => c.status === "connected" && !c.project && c.resources.length > 0);
  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger
          render={
            <DropdownMenuTrigger render={<InputGroupButton size="icon-sm" variant="ghost" aria-label="Add files, connectors and more" />} />
          }
        >
          <PlusIcon />
        </TooltipTrigger>
        <TooltipContent>Add files, connectors and more</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="start" side="top" className="w-60">
        <DropdownMenuGroup>
          <DropdownMenuItem onClick={onAttach}>
            <PaperclipIcon />
            Attach files…
          </DropdownMenuItem>
          <DropdownMenuItem onClick={onCommands}>
            <SlashIcon />
            Commands and skills
          </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <PlugIcon />
            Connectors
            {shown.length > 0 && (
              <span className="ml-auto text-xs text-muted-foreground tabular-nums">
                {shown.filter((c) => c.status === "connected" && !off.includes(c.key)).length}/{shown.length}
              </span>
            )}
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="w-64">
            <DropdownMenuGroup>
              <DropdownMenuLabel>In this chat</DropdownMenuLabel>
              {shown.length === 0 && <p className="px-2 py-1.5 text-xs text-muted-foreground">No connectors yet.</p>}
              {shown.map((connector) => (
                <DropdownMenuCheckboxItem
                  key={connector.key}
                  checked={!off.includes(connector.key)}
                  disabled={!chat}
                  onCheckedChange={(on) => chat && void useEngineStore.getState().setChatConnector(chat, connector.key, on)}
                >
                  <span className={cn("size-1.5 shrink-0 rounded-full", dot[connector.status] ?? dot.off)} />
                  <span className="truncate">{connector.name}</span>
                  <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">
                    {connector.status === "connected" ? connector.tools.length : ""}
                  </span>
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => useUiStore.getState().openCustomize("connectors")}>Manage connectors…</DropdownMenuItem>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        {withResources.length > 0 && (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <AtSignIcon />
              Resources
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="max-h-80 w-72 overflow-y-auto">
              {withResources.map((connector) => (
                <DropdownMenuGroup key={connector.key}>
                  <DropdownMenuLabel>{connector.name}</DropdownMenuLabel>
                  {connector.resources.slice(0, 30).map((resource) => (
                    <DropdownMenuItem key={resource.uri} onClick={() => onResource(`@${connector.name}:${resource.uri}`)}>
                      <span className="truncate" title={resource.uri}>
                        {resource.name ?? resource.uri}
                      </span>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuGroup>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Whether the chat's folder `cwd` is inside the project root `root` (a pool key). */
function cwdIn(cwd: string, root: string): boolean {
  const norm = (p: string) => p.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  const c = norm(cwd);
  const r = norm(root);
  return c === r || c.startsWith(`${r}/`);
}
