import * as React from "react";
import { BracesIcon, ChevronRightIcon, CircleAlertIcon, DownloadIcon, SparklesIcon, Trash2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { baseName } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { Badge } from "./customize-parts";

// Customize → Code intelligence: the language servers behind the agent's
// `lsp` tool (diagnostics, definitions, references, hover, symbols). The
// project's languages come first, with an Install button; every server shows
// where it comes from (installed by evo, on PATH, the Rust toolchain, or an
// editor extension) and can be switched off. RPC `list_language_servers`,
// `install_language_server`, … (crates/evo-engine/src/lsp_tool.rs).

interface ServerInfo {
  id: string;
  name: string;
  language: string;
  extensions: string[];
  install: { kind: string; packages?: string[]; module?: string; component?: string; tool?: string; gem?: string; repo?: string; hint?: string };
  requires: string[];
  missing: string[];
  installed: { path: string; source: "managed" | "path" | "toolchain" | "editor" } | null;
  enabled: boolean;
  installing: boolean;
  log: string[];
  error: string | null;
}

interface Detected {
  server: string;
  files: number;
  markers: string[];
}

export interface LanguagesState {
  servers: ServerInfo[];
  detected: Detected[];
  running: { server: string; root: string; indexing: boolean; alive: boolean }[];
  lspDir: string;
  folder: string;
}

const SOURCE: Record<string, string> = {
  managed: "Installed by evo",
  path: "On PATH",
  toolchain: "Rust toolchain",
  editor: "From your editor",
};

const PROGRAM: Record<string, string> = { node: "Node.js", npm: "npm", go: "Go", dotnet: ".NET SDK", gem: "Ruby", rustup: "rustup", java: "Java" };

function howItInstalls(install: ServerInfo["install"]): string {
  switch (install.kind) {
    case "npm":
      return `npm install ${install.packages?.join(" ")}`;
    case "go":
      return `go install ${install.module}@latest`;
    case "rustup":
      return `rustup component add ${install.component}`;
    case "dotnet":
      return `dotnet tool install ${install.tool}`;
    case "gem":
      return `gem install ${install.gem}`;
    case "githubRelease":
      return `Latest release of ${install.repo} from GitHub`;
    default:
      return install.hint ?? "Comes with its toolchain";
  }
}

function useLanguages() {
  const ready = useEngineStore((s) => (s.activeId ? s.runtimes[s.activeId]?.status === "ready" : false));
  const chat = useEngineStore((s) => s.activeId);
  const [state, setState] = React.useState<LanguagesState | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const request = React.useCallback(async (command: string, args?: Record<string, unknown>) => {
    try {
      setState(await useEngineStore.getState().request<LanguagesState>(command, args));
      setError(null);
    } catch (e) {
      setError(String(e).replace(/^Error:\s*/, ""));
    }
  }, []);
  React.useEffect(() => {
    if (ready) void request("list_language_servers");
  }, [ready, chat, request]);
  // Follow installs while they run.
  const installing = state?.servers.some((s) => s.installing);
  React.useEffect(() => {
    if (!installing) return;
    const timer = setInterval(() => void request("list_language_servers"), 1500);
    return () => clearInterval(timer);
  }, [installing, request]);
  return { state, error, ready, request };
}

function InstallButton({ server, onInstall }: { server: ServerInfo; onInstall(): void }) {
  if (server.installing)
    return (
      <Button size="sm" variant="outline" disabled className="gap-1.5">
        <Spinner className="size-3.5" /> Installing
      </Button>
    );
  if (server.install.kind === "system") return null;
  // Only evo's own installs are reinstalled here; a toolchain's, PATH's or
  // editor's server is updated where it came from.
  if (server.installed && server.installed.source !== "managed") return null;
  if (server.missing.length)
    return (
      <span className="text-[11px] text-muted-foreground">
        Needs {server.missing.map((m) => PROGRAM[m] ?? m).join(" and ")}
      </span>
    );
  return (
    <Button size="sm" variant={server.installed ? "ghost" : "outline"} className="gap-1.5" onClick={onInstall}>
      <DownloadIcon className="size-3.5" /> {server.installed ? "Reinstall" : "Install"}
    </Button>
  );
}

function ServerRow({
  server,
  detected,
  running,
  request,
}: {
  server: ServerInfo;
  detected?: Detected;
  running: boolean;
  request(command: string, args?: Record<string, unknown>): Promise<void>;
}) {
  const [open, setOpen] = React.useState(false);
  const showLog = server.installing || server.error;
  return (
    <div className={cn("rounded-xl ring-1 ring-border transition-colors", open && "bg-muted/30 dark:bg-accent/20")}>
      <div className="flex items-center gap-3 px-3 py-2.5">
        <button type="button" onClick={() => setOpen(!open)} className="flex min-w-0 flex-1 items-center gap-3 text-left">
          <ChevronRightIcon className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
          <span
            className={cn(
              "flex size-8 shrink-0 items-center justify-center rounded-lg",
              server.installed ? "bg-brand/12 text-brand" : "bg-muted text-muted-foreground dark:bg-accent",
            )}
          >
            <BracesIcon className="size-4" />
          </span>
          <span className="flex min-w-0 flex-col">
            <span className="flex min-w-0 items-center gap-2">
              <span className="truncate text-[13px] font-medium">{server.language}</span>
              {detected && <Badge tone="brand">In this project</Badge>}
              {running && <Badge>Running</Badge>}
            </span>
            <span className="truncate text-xs text-muted-foreground">
              {server.name} ·{" "}
              {server.installed ? SOURCE[server.installed.source] : server.error ? "Install failed" : "Not installed"}
            </span>
          </span>
        </button>
        <InstallButton server={server} onInstall={() => void request("install_language_server", { server: server.id })} />
        {server.installed && (
          <Switch
            aria-label={`Use ${server.name}`}
            checked={server.enabled}
            onCheckedChange={(on) => void request("set_language_server_enabled", { server: server.id, enabled: on })}
          />
        )}
      </div>
      {(open || showLog) && (
        <div className="flex flex-col gap-2 border-t border-border/60 px-4 py-3 text-xs">
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
            <dt className="text-muted-foreground">Files</dt>
            <dd>{server.extensions.map((e) => `.${e}`).join(" ")}</dd>
            <dt className="text-muted-foreground">Install</dt>
            <dd className="font-mono">{howItInstalls(server.install)}</dd>
            {server.requires.length > 0 && (
              <>
                <dt className="text-muted-foreground">Needs</dt>
                <dd>
                  {server.requires.map((r) => (
                    <span key={r} className={cn("mr-2", server.missing.includes(r) && "text-destructive")}>
                      {PROGRAM[r] ?? r}
                      {server.missing.includes(r) ? " (missing)" : ""}
                    </span>
                  ))}
                </dd>
              </>
            )}
            {server.installed && (
              <>
                <dt className="text-muted-foreground">Path</dt>
                <dd className="truncate font-mono" title={server.installed.path}>
                  {server.installed.path}
                </dd>
              </>
            )}
            {detected && (
              <>
                <dt className="text-muted-foreground">Project</dt>
                <dd>
                  {detected.files} files{detected.markers.length ? ` · ${detected.markers.join(", ")}` : ""}
                </dd>
              </>
            )}
          </dl>
          {server.error && (
            <p className="flex items-start gap-1.5 text-destructive">
              <CircleAlertIcon className="mt-0.5 size-3.5 shrink-0" />
              <span className="whitespace-pre-wrap">{server.error}</span>
            </p>
          )}
          {server.log.length > 0 && (
            <pre className="scrollbar-slim max-h-40 overflow-auto rounded-md bg-muted px-2 py-1.5 font-mono text-[11px] leading-4 dark:bg-accent/40">
              {server.log.join("\n")}
            </pre>
          )}
          {server.installed?.source === "managed" && !server.installing && (
            <div>
              <Button
                size="sm"
                variant="ghost"
                className="gap-1.5 text-muted-foreground"
                onClick={() => void request("uninstall_language_server", { server: server.id })}
              >
                <Trash2Icon className="size-3.5" /> Uninstall
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function LanguagesSection({ query }: { query: string }) {
  const { state, error, ready, request } = useLanguages();
  if (!state) {
    return (
      <div className="flex flex-1 items-center justify-center p-6 text-center text-[13px] text-muted-foreground">
        {error ? `Could not read language servers: ${error}` : ready ? <Spinner className="size-4" /> : "Open a chat to set up code intelligence."}
      </div>
    );
  }
  const q = query.trim().toLowerCase();
  const matches = (s: ServerInfo) =>
    !q || `${s.language} ${s.name} ${s.extensions.join(" ")}`.toLowerCase().includes(q);
  const detectedOf = (id: string) => state.detected.find((d) => d.server === id);
  const runningOf = (id: string) => state.running.some((r) => r.server === id && r.alive);
  const project = state.detected
    .map((d) => state.servers.find((s) => s.id === d.server))
    .filter((s): s is ServerInfo => Boolean(s) && matches(s!));
  const rest = state.servers.filter((s) => !detectedOf(s.id) && matches(s));
  const missing = project.filter((s) => !s.installed && !s.installing && !s.missing.length && s.install.kind !== "system");

  return (
    <div className="scrollbar-slim min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-5 px-6 py-5">
        <div className="flex flex-col gap-1">
          <h2 className="text-base font-semibold">Code intelligence</h2>
          <p className="text-[13px] text-muted-foreground">
            Language servers let the agent check a file for errors after editing it, jump to definitions, find every real
            use of a symbol and read types — more precise than searching text. A server starts the first time the agent
            needs it and runs while the chat is open.
          </p>
        </div>

        {project.length > 0 && (
          <section className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <SparklesIcon className="size-4 text-brand" />
              <h3 className="text-[13px] font-medium">Suggested for {baseName(state.folder)}</h3>
              <span className="flex-1" />
              {missing.length > 1 && (
                <Button
                  size="sm"
                  className="gap-1.5"
                  onClick={() => missing.forEach((s) => void request("install_language_server", { server: s.id }))}
                >
                  <DownloadIcon className="size-3.5" /> Install all {missing.length}
                </Button>
              )}
            </div>
            {project.map((server) => (
              <ServerRow key={server.id} server={server} detected={detectedOf(server.id)} running={runningOf(server.id)} request={request} />
            ))}
          </section>
        )}

        <section className="flex flex-col gap-2">
          <h3 className="text-[13px] font-medium">{project.length ? "Other languages" : "Languages"}</h3>
          {rest.length === 0 ? (
            <p className="text-xs text-muted-foreground">No matches.</p>
          ) : (
            rest.map((server) => <ServerRow key={server.id} server={server} running={runningOf(server.id)} request={request} />)
          )}
        </section>
        <p className="text-[11px] text-muted-foreground">
          evo installs servers into <span className="font-mono">{state.lspDir}</span>. Servers already on your PATH, in the
          Rust toolchain or bundled with VS Code-style editors are used as they are.
        </p>
      </div>
    </div>
  );
}
