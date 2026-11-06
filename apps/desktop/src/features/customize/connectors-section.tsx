import * as React from "react";
import {
  ChevronRightIcon,
  FolderGit2Icon,
  GlobeIcon,
  LogInIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  SquareTerminalIcon,
  Trash2Icon,
  TriangleAlertIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { mcp, type Connector, type ConnectorConfig, type ConnectorStatus, type ProjectState, type ToolPermission } from "@/lib/mcp";
import { useConnectorsStore } from "@/stores/connectors-store";
import { useEngineStore } from "@/stores/engine-store";
import { Badge, EmptyNote, IconAction, ListRow, Properties, Split } from "./customize-parts";

// Customize → Connectors: the MCP servers every chat can use (one shared
// pool in the shell, src-tauri/src/mcp.rs). A connector is a command evo runs
// or a URL it connects to; each tool is allowed, asks first, or is blocked.

const statusText: Record<ConnectorStatus, string> = {
  off: "Off",
  connecting: "Connecting…",
  connected: "Connected",
  "needs-auth": "Needs sign-in",
  failed: "Failed to connect",
};

const statusDot: Record<ConnectorStatus, string> = {
  off: "bg-muted-foreground/40",
  connecting: "bg-amber-500 animate-pulse",
  connected: "bg-status-ok",
  "needs-auth": "bg-amber-500",
  failed: "bg-destructive",
};

function Status({ connector }: { connector: Connector }) {
  const tools = connector.tools.length;
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
      <span className={cn("size-1.5 shrink-0 rounded-full", statusDot[connector.status])} />
      {statusText[connector.status]}
      {connector.status === "connected" && ` · ${tools} ${tools === 1 ? "tool" : "tools"}`}
    </span>
  );
}

const KindIcon = ({ kind }: { kind: Connector["kind"] }) => (kind === "stdio" ? <SquareTerminalIcon /> : <GlobeIcon />);

const permissions: { id: ToolPermission; label: string }[] = [
  { id: "allow", label: "Allow" },
  { id: "ask", label: "Ask" },
  { id: "block", label: "Block" },
];

function PermissionSwitch({ value, onChange }: { value: ToolPermission; onChange(value: ToolPermission): void }) {
  return (
    <div role="radiogroup" className="flex shrink-0 items-center gap-0.5 rounded-lg bg-muted/70 p-0.5 dark:bg-accent/50">
      {permissions.map((option) => (
        <button
          key={option.id}
          type="button"
          role="radio"
          aria-checked={value === option.id}
          onClick={() => onChange(option.id)}
          className={cn(
            "h-6 rounded-md px-2 text-[11px] transition-colors",
            value === option.id
              ? option.id === "block"
                ? "bg-background text-destructive shadow-sm"
                : "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

// ── Add / edit ──────────────────────────────────────────────────────────────

type Mode = "command" | "url" | "json";

/** `a "b c" d` → `["a", "b c", "d"]`. */
function splitArgs(text: string): string[] {
  const out: string[] = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text))) out.push(match[1] ?? match[2] ?? match[3]);
  return out;
}
const joinArgs = (args: string[] = []) => args.map((a) => (/\s/.test(a) ? `"${a}"` : a)).join(" ");

/** `KEY=value` (env) or `Name: value` (headers) lines. */
function parsePairs(text: string, separator: "=" | ":"): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const at = line.indexOf(separator);
    if (at <= 0) continue;
    const key = line.slice(0, at).trim();
    if (key) out[key] = line.slice(at + 1).trim();
  }
  return out;
}
const pairs = (map: Record<string, string> = {}, separator: "=" | ": ") =>
  Object.entries(map)
    .map(([k, v]) => `${k}${separator}${v}`)
    .join("\n");

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
    </label>
  );
}

function ConnectorForm({ editing, onDone }: { editing: Connector | null; onDone(): void }) {
  const config = editing?.config;
  const [mode, setMode] = React.useState<Mode>(editing ? (editing.kind === "stdio" ? "command" : "url") : "command");
  const [name, setName] = React.useState(editing?.name ?? "");
  const [command, setCommand] = React.useState(config?.command ?? "");
  const [args, setArgs] = React.useState(joinArgs(config?.args));
  const [env, setEnv] = React.useState(pairs(config?.env, "="));
  const [cwd, setCwd] = React.useState(config?.cwd ?? "");
  const [url, setUrl] = React.useState(config?.url ?? "");
  const [sse, setSse] = React.useState(config?.type === "sse");
  const [headers, setHeaders] = React.useState(pairs(config?.headers, ": "));
  const [json, setJson] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function save() {
    setError(null);
    setBusy(true);
    try {
      if (mode === "json") {
        const parsed = JSON.parse(json) as Record<string, unknown>;
        const servers = (parsed.mcpServers ?? (name ? { [name]: parsed } : null)) as Record<string, ConnectorConfig> | null;
        if (!servers || !Object.keys(servers).length) throw new Error('Paste {"mcpServers": {…}}, or a single server with a name above.');
        for (const [serverName, server] of Object.entries(servers)) await mcp.upsert(serverName, server);
      } else {
        // Keep what the form does not show (permissions, unknown keys).
        const base: ConnectorConfig = { ...(config ?? {}) };
        delete base.command;
        delete base.args;
        delete base.env;
        delete base.cwd;
        delete base.url;
        delete base.headers;
        delete base.type;
        const next: ConnectorConfig =
          mode === "command"
            ? { ...base, command: command.trim(), args: splitArgs(args), env: parsePairs(env, "="), ...(cwd.trim() ? { cwd: cwd.trim() } : {}) }
            : { ...base, type: sse ? "sse" : "http", url: url.trim(), headers: parsePairs(headers, ":") };
        await mcp.upsert(name.trim(), next, editing?.name);
      }
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const modes: { id: Mode; label: string }[] = [
    { id: "command", label: "Command" },
    { id: "url", label: "URL" },
    ...(editing ? [] : [{ id: "json" as Mode, label: "JSON" }]),
  ];

  return (
    <>
      <DialogHeader>
        <DialogTitle>{editing ? `Edit ${editing.name}` : "Add connector"}</DialogTitle>
        <DialogDescription>
          An MCP server: a command evo starts on this computer, or a URL it connects to. Its tools become available in
          every chat.
        </DialogDescription>
      </DialogHeader>
      <div className="flex flex-col gap-4">
        <div role="tablist" className="flex items-center gap-0.5 self-start rounded-lg bg-muted/70 p-0.5 dark:bg-accent/50">
          {modes.map((m) => (
            <button
              key={m.id}
              type="button"
              role="tab"
              aria-selected={mode === m.id}
              onClick={() => setMode(m.id)}
              className={cn(
                "h-7 rounded-md px-3 text-xs transition-colors",
                mode === m.id ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
        {(mode !== "json" || !json.includes("mcpServers")) && (
          <Field label="Name" hint="Letters, digits, - and _. Tools appear to the agent as mcp__name__tool.">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="github" autoFocus />
          </Field>
        )}
        {mode === "command" && (
          <>
            <Field label="Command">
              <Input value={command} onChange={(e) => setCommand(e.target.value)} placeholder="npx" className="font-mono" />
            </Field>
            <Field label="Arguments">
              <Input
                value={args}
                onChange={(e) => setArgs(e.target.value)}
                placeholder="-y @modelcontextprotocol/server-filesystem C:\work"
                className="font-mono"
              />
            </Field>
            <Field label="Environment" hint="One KEY=value per line. ${VAR} reads from your environment.">
              <Textarea value={env} onChange={(e) => setEnv(e.target.value)} placeholder="GITHUB_TOKEN=${GITHUB_TOKEN}" className="min-h-16 font-mono text-xs" />
            </Field>
            <Field label="Working folder" hint="Optional; your home folder when empty.">
              <Input value={cwd} onChange={(e) => setCwd(e.target.value)} className="font-mono" />
            </Field>
          </>
        )}
        {mode === "url" && (
          <>
            <Field label="Server URL">
              <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/mcp" className="font-mono" />
            </Field>
            <Field label="Headers" hint="One Name: value per line, e.g. Authorization: Bearer ${TOKEN}.">
              <Textarea value={headers} onChange={(e) => setHeaders(e.target.value)} className="min-h-16 font-mono text-xs" />
            </Field>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <Switch checked={sse} onCheckedChange={setSse} />
              Older server (SSE transport)
            </label>
          </>
        )}
        {mode === "json" && (
          <Field label="Configuration" hint='{"mcpServers": {"name": {"command": …}}} adds every server in it.'>
            <Textarea
              value={json}
              onChange={(e) => setJson(e.target.value)}
              placeholder={'{\n  "mcpServers": {\n    "memory": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"] }\n  }\n}'}
              className="min-h-40 font-mono text-xs"
            />
          </Field>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onDone} disabled={busy}>
          Cancel
        </Button>
        <Button onClick={() => void save()} disabled={busy}>
          {busy ? "Connecting…" : editing ? "Save" : "Add"}
        </Button>
      </DialogFooter>
    </>
  );
}

// ── Detail ──────────────────────────────────────────────────────────────────

function ConnectorDetail({ connector, onEdit }: { connector: Connector; onEdit(): void }) {
  const [confirmRemove, setConfirmRemove] = React.useState(false);
  const on = connector.status !== "off";
  const envKeys = Object.keys(connector.config.env ?? {});
  const headerKeys = Object.keys(connector.config.headers ?? {});

  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand/12 text-brand [&_svg]:size-5">
          <KindIcon kind={connector.kind} />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold">{connector.name}</h2>
            <Badge>{connector.kind === "stdio" ? "Command" : connector.kind === "sse" ? "URL · SSE" : "URL"}</Badge>
            {connector.project && <Badge tone="brand">Project</Badge>}
            {connector.signedIn && <Badge>Signed in</Badge>}
            {connector.server?.version && <Badge>v{connector.server.version}</Badge>}
          </div>
          <Status connector={connector} />
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <IconAction label="Reconnect" onClick={() => void mcp.reconnect(connector.key)}>
            <RefreshCwIcon className={cn(connector.status === "connecting" && "animate-spin")} />
          </IconAction>
          {connector.kind !== "stdio" && connector.kind !== "invalid" && (
            <SignInButton connector={connector} />
          )}
          {!connector.project && (
            <IconAction label="Edit" onClick={onEdit}>
              <PencilIcon />
            </IconAction>
          )}
          {confirmRemove ? (
            <Button size="sm" variant="destructive" onClick={() => void mcp.remove(connector.key)} onBlur={() => setConfirmRemove(false)}>
              Remove
            </Button>
          ) : (
            <IconAction label="Remove" onClick={() => setConfirmRemove(true)}>
              <Trash2Icon />
            </IconAction>
          )}
          <Switch aria-label={on ? "Turn off" : "Turn on"} checked={on} onCheckedChange={(next) => void mcp.setEnabled(connector.key, next)} />
        </div>
      </header>

      {connector.error && connector.status !== "connected" && (
        <div className="flex gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/8 px-3.5 py-3 text-[13px]">
          <TriangleAlertIcon className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <div className="flex min-w-0 flex-col gap-1">
            <p className="font-medium">{statusText[connector.status]}</p>
            <p className="break-words font-mono text-xs text-muted-foreground">{connector.error}</p>
            {connector.status === "needs-auth" && (
              <p className="text-xs text-muted-foreground">
                Sign in to let evo use it, or add an <code>Authorization: Bearer …</code> header with a token from the
                service (Edit).
              </p>
            )}
          </div>
        </div>
      )}

      <div className="@container rounded-xl bg-muted/40 px-4 py-3 dark:bg-accent/30">
        <Properties
          items={[
            [connector.kind === "stdio" ? "Runs" : "URL", <code className="font-mono text-xs break-all">{connector.summary}</code>],
            ["Server", connector.server?.title ?? connector.server?.name],
            ["Folder", connector.config.cwd],
            ["Environment", envKeys.length ? envKeys.join(", ") : undefined],
            ["Headers", headerKeys.length ? headerKeys.join(", ") : undefined],
            ["Prompts", connector.prompts.length ? connector.prompts.length : undefined],
            ["From", connector.project ? `${connector.project}/.mcp.json` : undefined],
          ]}
        />
      </div>

      {connector.instructions && (
        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-medium text-muted-foreground">Instructions from the server</h3>
          <p className="text-[13px] whitespace-pre-wrap text-muted-foreground">{connector.instructions}</p>
        </section>
      )}

      <section className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-medium text-muted-foreground">Tools</h3>
          {connector.tools.length > 1 && (
            <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
              Set all:
              {permissions.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="rounded px-1 hover:text-foreground"
                  onClick={() => connector.tools.forEach((t) => void mcp.setPermission(connector.key, t.name, p.id))}
                >
                  {p.label}
                </button>
              ))}
            </div>
          )}
        </div>
        {connector.tools.length === 0 ? (
          <p className="rounded-xl border border-dashed border-border/70 px-4 py-6 text-center text-xs text-muted-foreground">
            {connector.status === "connected" ? "This server offers no tools." : "Tools show here once it is connected."}
          </p>
        ) : (
          <div className="divide-y divide-border/60 overflow-hidden rounded-xl border border-border/70">
            {connector.tools.map((tool) => (
              <div key={tool.name} className="flex items-start gap-3 px-3.5 py-2.5">
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate font-mono text-xs font-medium">{tool.name}</span>
                    {tool.readOnly && <Badge>Read-only</Badge>}
                  </div>
                  {tool.description && <p className="line-clamp-2 text-xs text-muted-foreground">{tool.description}</p>}
                </div>
                <PermissionSwitch value={tool.permission} onChange={(p) => void mcp.setPermission(connector.key, tool.name, p)} />
              </div>
            ))}
          </div>
        )}
      </section>

      {connector.prompts.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-medium text-muted-foreground">Prompts · type / in the message box</h3>
          <div className="flex flex-col gap-1">
            {connector.prompts.map((prompt) => (
              <p key={prompt.name} className="text-xs">
                <code className="font-mono">
                  /{connector.name}:{prompt.name}
                  {prompt.arguments?.length ? ` ${prompt.arguments.map((a) => `<${a.name}>`).join(" ")}` : ""}
                </code>
                {prompt.description && <span className="text-muted-foreground"> — {prompt.description}</span>}
              </p>
            ))}
          </div>
        </section>
      )}

      {connector.resources.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-medium text-muted-foreground">Resources · mention with @ in the message box</h3>
          <div className="flex flex-col gap-1">
            {connector.resources.slice(0, 50).map((resource) => (
              <p key={resource.uri} className="truncate text-xs" title={resource.description ?? resource.uri}>
                <code className="font-mono">
                  @{connector.name}:{resource.uri}
                </code>
                {resource.name && <span className="text-muted-foreground"> — {resource.name}</span>}
              </p>
            ))}
            {connector.resources.length > 50 && (
              <p className="text-xs text-muted-foreground">and {connector.resources.length - 50} more</p>
            )}
          </div>
        </section>
      )}

      {connector.log.length > 0 && (
        <Collapsible>
          <CollapsibleTrigger className="group flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground">
            <ChevronRightIcon className="size-3.5 transition-transform group-data-[panel-open]:rotate-90" />
            Server log ({connector.log.length} lines)
          </CollapsibleTrigger>
          <CollapsibleContent>
            <pre className="mt-2 max-h-64 overflow-auto rounded-xl bg-muted/50 p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap dark:bg-accent/30">
              {connector.log.join("\n")}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  );
}


/** Sign in to a URL connector in the browser, or forget its sign-in. */
function SignInButton({ connector }: { connector: Connector }) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  if (connector.signedIn) {
    return (
      <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={() => void mcp.signOut(connector.key)}>
        Sign out
      </Button>
    );
  }
  return (
    <span className="flex items-center gap-1.5">
      {error && <span className="max-w-48 truncate text-[11px] text-destructive" title={error}>{error}</span>}
      <Button
        size="sm"
        variant={connector.status === "needs-auth" ? "default" : "outline"}
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await mcp.signIn(connector.key);
          } catch (e) {
            setError(String(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        <LogInIcon />
        {busy ? "Waiting for the browser…" : "Sign in"}
      </Button>
    </span>
  );
}

/** The servers of the active chat's project `.mcp.json`, to approve or deny. */
function ProjectServers({ cwd }: { cwd: string }) {
  const servers = useConnectorsStore((s) => s.servers);
  const [state, setState] = React.useState<ProjectState | null>(null);
  const refresh = React.useCallback(() => {
    void mcp.projectState(cwd).then(setState).catch(() => setState(null));
  }, [cwd]);
  // Read again whenever the pool changes (an approval loads or drops one).
  React.useEffect(refresh, [refresh, servers]);
  if (!state?.root || state.servers.length === 0) return null;
  const pending = state.servers.filter((s) => s.approval === "pending");
  return (
    <div className="mb-1.5 flex flex-col gap-1.5 rounded-xl border border-border/70 p-2.5">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
        <FolderGit2Icon className="size-3.5" />
        <span className="truncate" title={state.file}>
          This project · .mcp.json
        </span>
        {pending.length > 0 && <span className="ml-auto text-amber-600 dark:text-amber-400">{pending.length} to review</span>}
      </div>
      {state.servers.map((server) => (
        <div key={server.name} className="flex items-center gap-2">
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="truncate text-xs font-medium">{server.name}</span>
            <span className="truncate font-mono text-[10px] text-muted-foreground">{server.summary}</span>
          </div>
          {server.shadowed ? (
            <span className="text-[10px] text-muted-foreground">Yours is used</span>
          ) : server.approval === "pending" ? (
            <>
              <Button size="xs" variant="ghost" onClick={() => void mcp.setProjectApproval(cwd, server.name, false).then(refresh)}>
                Deny
              </Button>
              <Button size="xs" onClick={() => void mcp.setProjectApproval(cwd, server.name, true).then(refresh)}>
                Approve
              </Button>
            </>
          ) : (
            <Switch
              aria-label={`Use ${server.name}`}
              checked={server.approval === "approved"}
              onCheckedChange={(on) => void mcp.setProjectApproval(cwd, server.name, on).then(refresh)}
            />
          )}
        </div>
      ))}
      {pending.length > 0 && (
        <p className="text-[10px] leading-snug text-muted-foreground">
          A project's servers run commands on this computer. Approve only those you trust.
        </p>
      )}
    </div>
  );
}

// ── Section ─────────────────────────────────────────────────────────────────

export function ConnectorsSection({ query }: { query: string }) {
  const { servers, loaded, error, load } = useConnectorsStore();
  const cwd = useEngineStore((s) => s.cwd);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [dialog, setDialog] = React.useState<{ editing: Connector | null } | null>(null);

  React.useEffect(() => {
    void load();
  }, [load]);

  const q = query.trim().toLowerCase();
  const list = servers.filter((s) => !q || s.name.toLowerCase().includes(q) || s.summary.toLowerCase().includes(q));
  const current = list.find((s) => s.key === selected) ?? list[0];

  return (
    <>
      <Split
        list={
          <div className="flex flex-col gap-0.5 pt-2.5">
            <Button variant="outline" size="sm" className="mb-1.5 justify-start gap-2" onClick={() => setDialog({ editing: null })}>
              <PlusIcon />
              Add connector
            </Button>
            {cwd && <ProjectServers cwd={cwd} />}
            {error && <p className="px-2.5 text-xs text-destructive">{error}</p>}
            {loaded && list.length === 0 ? (
              <EmptyNote title={q ? "No matching connectors" : "No connectors yet"}>
                A connector is an MCP server — a command such as <code>npx -y @modelcontextprotocol/server-memory</code>, or a
                URL. Every chat can use its tools; you choose which ones run without asking.
              </EmptyNote>
            ) : (
              list.map((connector) => (
                <ListRow
                  key={connector.key}
                  selected={current?.key === connector.key}
                  onSelect={() => setSelected(connector.key)}
                  icon={<KindIcon kind={connector.kind} />}
                  title={connector.name}
                  description={connector.summary}
                  meta={<Status connector={connector} />}
                  dimmed={connector.status === "off"}
                  trailing={
                    <Switch
                      aria-label={`Use ${connector.name}`}
                      checked={connector.status !== "off"}
                      onCheckedChange={(on) => void mcp.setEnabled(connector.key, on)}
                    />
                  }
                />
              ))
            )}
          </div>
        }
        detail={current ? <ConnectorDetail key={current.key} connector={current} onEdit={() => setDialog({ editing: current })} /> : null}
      />
      <Dialog open={dialog !== null} onOpenChange={(open) => !open && setDialog(null)}>
        <DialogContent className="sm:max-w-lg">
          {dialog && <ConnectorForm key={dialog.editing?.name ?? "new"} editing={dialog.editing} onDone={() => setDialog(null)} />}
        </DialogContent>
      </Dialog>
    </>
  );
}
