import * as React from "react";
import {
  BlocksIcon,
  DownloadIcon,
  FolderGit2Icon,
  FolderOpenIcon,
  FolderPlusIcon,
  GitBranchIcon,
  RefreshCwIcon,
  StoreIcon,
  Trash2Icon,
  TriangleAlertIcon,
} from "lucide-react";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import { openUrl, revealItemInDir } from "@tauri-apps/plugin-opener";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { plugins, PLUGINS_CHANGED, type CatalogEntry, type InstalledPlugin, type PluginsState } from "@/lib/plugins";
import { Badge, EmptyNote, IconAction, ListRow, Properties, Split } from "./customize-parts";

// Customize → Plugins: bundles of skills, commands, subagents, hooks and
// connectors (src-tauri/src/plugins.rs, crates/evo-plugins). Installed ones
// with a switch each; Discover lists what the added marketplaces offer;
// Marketplaces adds catalogs from GitHub (owner/repo), any git URL (#ref
// for a branch or tag) or a folder.

type Tab = "installed" | "discover" | "marketplaces";

function useBusy() {
  const [busy, setBusy] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const run = async (key: string, work: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await work();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };
  return { busy, error, run, setError };
}

function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="flex gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs">
      <TriangleAlertIcon className="mt-px size-3.5 shrink-0 text-destructive" />
      <span className="min-w-0 break-words">{error}</span>
    </div>
  );
}

const authorName = (author: CatalogEntry["author"]) => (typeof author === "string" ? author : author?.name);

// ── Installed ───────────────────────────────────────────────────────────────

function Contents({ plugin }: { plugin: InstalledPlugin }) {
  const rows: [string, React.ReactNode][] = [
    ["Skills", plugin.skills.length ? plugin.skills.map((s) => `/${plugin.name}:${s}`).join("  ") : undefined],
    ["Commands", plugin.commands || undefined],
    ["Subagents", plugin.agents.length ? plugin.agents.map((a) => `${plugin.name}:${a}`).join(", ") : undefined],
    ["Hooks", plugin.hooks.length ? plugin.hooks.map((h) => `${h.event} (${h.count})`).join(", ") : undefined],
    ["Connectors", plugin.connectors.length ? plugin.connectors.join(", ") : undefined],
    ["Commands on PATH", plugin.bin ? "bin/" : undefined],
  ];
  const any = rows.some(([, v]) => v !== undefined);
  return any ? <Properties items={rows} /> : <p className="text-xs text-muted-foreground">This plugin adds nothing evo can use.</p>;
}

function ConfigForm({ plugin }: { plugin: InstalledPlugin }) {
  const options = Object.entries(plugin.userConfig);
  const [values, setValues] = React.useState<Record<string, unknown>>(plugin.config);
  const { busy, error, run } = useBusy();
  if (!options.length) return null;
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-xs font-medium text-muted-foreground">Settings</h3>
      <div className="flex flex-col gap-3 rounded-xl border border-border/70 p-3.5">
        {options.map(([key, option]) => (
          <label key={key} className="flex flex-col gap-1">
            <span className="text-xs font-medium">
              {option.title ?? key}
              {option.required && <span className="text-destructive"> *</span>}
            </span>
            {option.type === "boolean" ? (
              <Switch checked={Boolean(values[key] ?? option.default)} onCheckedChange={(on) => setValues((v) => ({ ...v, [key]: on }))} />
            ) : (
              <Input
                type={option.sensitive ? "password" : option.type === "number" ? "number" : "text"}
                value={String(values[key] ?? option.default ?? "")}
                onChange={(e) =>
                  setValues((v) => ({ ...v, [key]: option.type === "number" ? Number(e.target.value) : e.target.value }))
                }
                className="font-mono"
              />
            )}
            {option.description && <span className="text-[11px] text-muted-foreground">{option.description}</span>}
          </label>
        ))}
        <ErrorNote error={error} />
        <Button size="sm" className="self-end" disabled={busy !== null} onClick={() => void run("save", () => plugins.setConfig(plugin.id, values))}>
          {busy ? "Saving…" : "Save"}
        </Button>
      </div>
    </section>
  );
}

function InstalledDetail({ plugin }: { plugin: InstalledPlugin }) {
  const { busy, error, run } = useBusy();
  const [confirm, setConfirm] = React.useState(false);
  const local = plugin.marketplace === "local";
  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand/12 text-brand">
          <BlocksIcon className="size-5" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold">{plugin.name}</h2>
            <Badge>v{plugin.version.length > 14 ? plugin.version.slice(0, 12) : plugin.version}</Badge>
            <Badge>{local ? "Folder" : plugin.marketplace}</Badge>
          </div>
          {plugin.description && <p className="text-[13px] leading-relaxed text-muted-foreground">{plugin.description}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <IconAction label="Show in folder" onClick={() => void revealItemInDir(plugin.path).catch(() => undefined)}>
            <FolderOpenIcon />
          </IconAction>
          {!local && (
            <IconAction label="Update" onClick={() => void run("update", () => plugins.update(plugin.id))}>
              <RefreshCwIcon className={cn(busy === "update" && "animate-spin")} />
            </IconAction>
          )}
          {confirm ? (
            <Button size="sm" variant="destructive" onBlur={() => setConfirm(false)} onClick={() => void run("remove", () => plugins.uninstall(plugin.id))}>
              Uninstall
            </Button>
          ) : (
            <IconAction label="Uninstall" onClick={() => setConfirm(true)}>
              <Trash2Icon />
            </IconAction>
          )}
          <Switch aria-label={plugin.enabled ? "Turn off" : "Turn on"} checked={plugin.enabled} onCheckedChange={(on) => void run("toggle", () => plugins.setEnabled(plugin.id, on))} />
        </div>
      </header>
      <ErrorNote error={error} />
      {plugin.problems.length > 0 && (
        <div className="flex flex-col gap-1 rounded-xl border border-amber-500/30 bg-amber-500/8 px-3.5 py-3 text-xs">
          <p className="font-medium">Some parts could not be read</p>
          {plugin.problems.map((p) => (
            <p key={p} className="font-mono break-words text-muted-foreground">
              {p}
            </p>
          ))}
        </div>
      )}
      <div className="@container rounded-xl bg-muted/40 px-4 py-3 dark:bg-accent/30">
        <Properties
          items={[
            ["Author", plugin.author],
            ["License", plugin.license],
            ["Homepage", plugin.homepage && (
              <button type="button" className="text-link hover:underline" onClick={() => void openUrl(plugin.homepage!).catch(() => undefined)}>
                {plugin.homepage}
              </button>
            )],
            ["Repository", plugin.repository],
            ["Keywords", plugin.keywords.length ? plugin.keywords.join(", ") : undefined],
          ]}
        />
      </div>
      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-medium text-muted-foreground">What it adds</h3>
        <div className={cn("@container rounded-xl border border-border/70 px-4 py-3", !plugin.enabled && "opacity-60")}>
          <Contents plugin={plugin} />
        </div>
      </section>
      <ConfigForm key={plugin.id} plugin={plugin} />
      <p className="truncate font-mono text-[11px] text-muted-foreground" title={plugin.path}>
        {plugin.path}
      </p>
    </div>
  );
}

// ── Discover ────────────────────────────────────────────────────────────────

function Discover({ state, query, onGoToMarketplaces }: { state: PluginsState; query: string; onGoToMarketplaces(): void }) {
  const { busy, error, run } = useBusy();
  const q = query.trim().toLowerCase();
  const entries = state.catalog.filter(
    (e) =>
      e.error ||
      !q ||
      e.name.toLowerCase().includes(q) ||
      (e.description ?? "").toLowerCase().includes(q) ||
      (e.keywords ?? []).some((k) => k.toLowerCase().includes(q)),
  );
  if (state.marketplaces.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center px-6">
        <div className="flex max-w-sm flex-col items-center gap-3 text-center">
          <StoreIcon className="size-6 text-muted-foreground" />
          <p className="text-sm font-medium">No marketplaces yet</p>
          <p className="text-[13px] text-muted-foreground">Add a marketplace — a GitHub repository, any git URL or a folder — to browse its plugins.</p>
          <Button size="sm" onClick={onGoToMarketplaces}>
            Add a marketplace
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="scrollbar-slim min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-4xl flex-col gap-3 px-6 py-5">
        <ErrorNote error={error} />
        {entries.length === 0 && <EmptyNote title="No matching plugins">Try another search.</EmptyNote>}
        <div className="grid grid-cols-1 gap-2.5 @xl:grid-cols-2">
          {entries.map((entry) =>
            entry.error ? (
              <div key={entry.marketplace} className="rounded-xl border border-destructive/30 p-3 text-xs">
                <p className="font-medium">{entry.marketplace}</p>
                <p className="text-muted-foreground">{entry.error}</p>
              </div>
            ) : (
              <div key={entry.id} className="flex flex-col gap-2 rounded-xl border border-border/70 p-3.5">
                <div className="flex items-start gap-2.5">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground dark:bg-accent">
                    <BlocksIcon className="size-4" />
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-[13px] font-medium">{entry.name}</span>
                    <span className="truncate text-[11px] text-muted-foreground">
                      {entry.marketplace}
                      {authorName(entry.author) ? ` · ${authorName(entry.author)}` : ""}
                      {entry.version ? ` · v${entry.version}` : ""}
                    </span>
                  </div>
                  {entry.installed ? (
                    <Button size="xs" variant="outline" disabled={busy !== null} onClick={() => void run(entry.id, () => plugins.install(entry.marketplace, entry.name))}>
                      {busy === entry.id ? "Installing…" : "Reinstall"}
                    </Button>
                  ) : (
                    <Button size="xs" disabled={busy !== null} onClick={() => void run(entry.id, () => plugins.install(entry.marketplace, entry.name))}>
                      <DownloadIcon />
                      {busy === entry.id ? "Installing…" : "Install"}
                    </Button>
                  )}
                </div>
                {entry.description && <p className="line-clamp-2 text-xs text-muted-foreground">{entry.description}</p>}
                <div className="flex flex-wrap gap-1">
                  {entry.installed && <Badge tone="brand">Installed</Badge>}
                  {entry.category && <Badge>{entry.category}</Badge>}
                  {(entry.keywords ?? []).slice(0, 4).map((k) => (
                    <Badge key={k}>{k}</Badge>
                  ))}
                </div>
              </div>
            ),
          )}
        </div>
      </div>
    </div>
  );
}

// ── Marketplaces ────────────────────────────────────────────────────────────

function Marketplaces({ state }: { state: PluginsState }) {
  const [source, setSource] = React.useState("");
  const { busy, error, run } = useBusy();
  const add = (value: string) =>
    void run("add", async () => {
      await plugins.addMarketplace(value.trim());
      setSource("");
    });
  return (
    <div className="scrollbar-slim min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-5 px-6 py-5">
        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-medium text-muted-foreground">Add a marketplace</h3>
          <div className="flex items-center gap-2">
            <Input
              value={source}
              onChange={(e) => setSource(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && source.trim() && add(source)}
              placeholder="owner/repo, a git URL (add #branch for a branch or tag), or a folder"
              className="font-mono"
            />
            <Button disabled={!source.trim() || busy !== null} onClick={() => add(source)}>
              {busy === "add" ? "Adding…" : "Add"}
            </Button>
            <IconAction
              label="Choose a folder"
              onClick={async () => {
                const folder = await open({ directory: true, title: "Marketplace folder" });
                if (typeof folder === "string") add(folder);
              }}
            >
              <FolderOpenIcon />
            </IconAction>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Examples: <code>acme/evo-plugins</code>, <code>acme/evo-plugins#v2</code>,{" "}
            <code>https://gitlab.example.com/team/plugins.git#main</code>, <code>git@github.com:acme/plugins.git</code>. The
            repository needs a <code>marketplace.json</code> (or <code>.evo-plugin/marketplace.json</code>,{" "}
            <code>.claude-plugin/marketplace.json</code>).
          </p>
          <ErrorNote error={error} />
        </section>
        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-medium text-muted-foreground">Added</h3>
          {state.marketplaces.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border/70 px-4 py-6 text-center text-xs text-muted-foreground">None yet.</p>
          ) : (
            <div className="divide-y divide-border/60 overflow-hidden rounded-xl border border-border/70">
              {state.marketplaces.map((m) => (
                <div key={m.name} className="flex items-center gap-3 px-3.5 py-2.5">
                  <span className="text-muted-foreground">{m.kind === "git" ? <GitBranchIcon className="size-4" /> : <FolderGit2Icon className="size-4" />}</span>
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="flex items-center gap-1.5 text-[13px] font-medium">
                      {m.name}
                      <span className="text-[11px] font-normal text-muted-foreground">
                        {m.plugins} {m.plugins === 1 ? "plugin" : "plugins"}
                      </span>
                    </span>
                    <span className="truncate font-mono text-[11px] text-muted-foreground" title={m.location}>
                      {m.source}
                    </span>
                    {m.error && <span className="text-[11px] text-destructive">{m.error}</span>}
                  </div>
                  <span className="hidden shrink-0 text-[11px] text-muted-foreground @md:inline">
                    {m.updatedAt ? new Date(m.updatedAt).toLocaleDateString() : ""}
                  </span>
                  <IconAction label="Fetch again" onClick={() => void run(`u:${m.name}`, () => plugins.updateMarketplace(m.name))}>
                    <RefreshCwIcon className={cn(busy === `u:${m.name}` && "animate-spin")} />
                  </IconAction>
                  <IconAction label="Remove" onClick={() => void run(`r:${m.name}`, () => plugins.removeMarketplace(m.name))}>
                    <Trash2Icon />
                  </IconAction>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

// ── Section ─────────────────────────────────────────────────────────────────

export function PluginsSection({ query }: { query: string }) {
  const [state, setState] = React.useState<PluginsState | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [tab, setTab] = React.useState<Tab>("installed");
  const [selected, setSelected] = React.useState<string | null>(null);
  const { busy, error: addError, run } = useBusy();

  const load = React.useCallback(() => {
    void plugins
      .state()
      .then((s) => {
        setState(s);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, []);

  React.useEffect(() => {
    load();
    let stop: (() => void) | undefined;
    void listen(PLUGINS_CHANGED, load)
      .then((unlisten) => (stop = unlisten))
      .catch(() => undefined);
    return () => stop?.();
  }, [load]);

  if (!state) {
    return (
      <div className="flex flex-1 items-center justify-center">
        {error ? <p className="text-[13px] text-muted-foreground">Could not read plugins: {error}</p> : <Spinner className="size-4 text-muted-foreground" />}
      </div>
    );
  }

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "installed", label: "Installed", count: state.installed.length },
    { id: "discover", label: "Discover", count: state.catalog.filter((c) => !c.error).length },
    { id: "marketplaces", label: "Marketplaces", count: state.marketplaces.length },
  ];

  const q = query.trim().toLowerCase();
  const installed = state.installed.filter(
    (p) => !q || p.name.toLowerCase().includes(q) || (p.description ?? "").toLowerCase().includes(q),
  );
  const current = installed.find((p) => p.id === selected) ?? installed[0];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-border/60 px-4 py-1.5">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={cn(
              "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs transition-colors",
              tab === t.id ? "bg-muted text-foreground dark:bg-accent" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
            {t.count ? <span className="text-[11px] text-muted-foreground tabular-nums">{t.count}</span> : null}
          </button>
        ))}
        <span className="flex-1" />
        <Button
          size="xs"
          variant="outline"
          disabled={busy !== null}
          onClick={async () => {
            const folder = await open({ directory: true, title: "Plugin folder" });
            if (typeof folder === "string") void run("folder", () => plugins.installFolder(folder));
          }}
        >
          <FolderPlusIcon />
          Add from folder
        </Button>
      </div>
      {addError && (
        <div className="px-4 pt-3">
          <ErrorNote error={addError} />
        </div>
      )}
      {tab === "discover" ? (
        <div className="@container flex min-h-0 flex-1 flex-col">
          <Discover state={state} query={query} onGoToMarketplaces={() => setTab("marketplaces")} />
        </div>
      ) : tab === "marketplaces" ? (
        <div className="@container flex min-h-0 flex-1 flex-col">
          <Marketplaces state={state} />
        </div>
      ) : (
        <Split
          list={
            installed.length === 0 ? (
              <EmptyNote title={q ? "No matching plugins" : "No plugins yet"}>
                A plugin bundles skills, commands, subagents, hooks and connectors. Install one from{" "}
                <button type="button" className="text-link hover:underline" onClick={() => setTab("discover")}>
                  Discover
                </button>
                , or add a plugin folder.
              </EmptyNote>
            ) : (
              <div className="flex flex-col gap-0.5 pt-2.5">
                {installed.map((plugin) => (
                  <ListRow
                    key={plugin.id}
                    selected={current?.id === plugin.id}
                    onSelect={() => setSelected(plugin.id)}
                    icon={<BlocksIcon />}
                    title={plugin.name}
                    meta={<span className="shrink-0 text-[11px] text-muted-foreground">{plugin.marketplace === "local" ? "folder" : plugin.marketplace}</span>}
                    description={plugin.description ?? ""}
                    dimmed={!plugin.enabled}
                    trailing={
                      <Switch
                        aria-label={`Use ${plugin.name}`}
                        checked={plugin.enabled}
                        onCheckedChange={(on) => void run(plugin.id, () => plugins.setEnabled(plugin.id, on))}
                      />
                    }
                  />
                ))}
              </div>
            )
          }
          detail={current ? <InstalledDetail key={current.id} plugin={current} /> : null}
        />
      )}
    </div>
  );
}
