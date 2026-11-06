import * as React from "react";
import {
  CheckIcon,
  ChevronRightIcon,
  CopyIcon,
  ExternalLinkIcon,
  KeyRoundIcon,
  LoaderCircleIcon,
  LogInIcon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { ProviderIcon } from "@/components/provider-icon";
import { StatusDot } from "@/components/status-dot";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import type { ProviderKind, ProviderRow, ProviderUsage, UsageLimit } from "@/engine/protocol";
import { openLink } from "@/features/shell/app-commands";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { byRank, matchesProvider, useProviderStore } from "@/stores/provider-store";
import { modelKey } from "@/components/ai-elements/model-selector";
import { SettingsGroup, SettingsHeader, SettingsRow } from "../settings-controls";

const KIND_LABEL: Record<ProviderKind, string> = {
  api_key: "API key",
  oauth: "OAuth",
  local: "Local",
  cloud: "Cloud",
};

/** Long-tail rows shown before "Show all". */
const CATALOG_PREVIEW = 12;

export function ProviderSettings() {
  const status = useEngineStore((s) => s.status);
  const providers = useProviderStore((s) => s.providers);
  const connected = useProviderStore((s) => s.connected);
  const loading = useProviderStore((s) => s.loading);
  const error = useProviderStore((s) => s.error);
  const load = useProviderStore((s) => s.load);
  const [query, setQuery] = React.useState("");
  const [openId, setOpenId] = React.useState<string | null>(null);
  const [showAll, setShowAll] = React.useState(false);

  React.useEffect(() => {
    if (status === "ready") void load();
  }, [status, load]);

  const visible = providers.filter((row) => matchesProvider(row, query));
  const searching = query.trim().length > 0;
  const sections = React.useMemo(() => {
    const sorted = [...visible].sort(byRank);
    const used = new Set<string>();
    const take = (rows: ProviderRow[]) => {
      rows.forEach((row) => used.add(row.id));
      return rows;
    };
    const connectedRows = take(sorted.filter((row) => row.connected));
    const recommended = take(sorted.filter((row) => !used.has(row.id) && row.recommended));
    const curated = take(sorted.filter((row) => !used.has(row.id) && row.source === "curated" && row.supported));
    const catalog = take(sorted.filter((row) => !used.has(row.id) && row.source !== "curated"));
    const unavailable = sorted.filter((row) => !used.has(row.id));
    return { connectedRows, recommended, curated, catalog, unavailable };
  }, [visible]);
  const open = providers.find((row) => row.id === openId) ?? null;
  const catalogRows = searching || showAll ? sections.catalog : sections.catalog.slice(0, CATALOG_PREVIEW);

  return (
    <div className="flex flex-col gap-8">
      <SettingsHeader
        icon={KeyRoundIcon}
        title="Providers"
        description="Connect a model provider so the agent can run. API keys are stored on this computer only, and changes apply without restarting."
      >
        <span className="flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs text-muted-foreground shadow-hairline">
          <StatusDot tone={connected > 0 ? "ok" : "idle"} />
          {connected} connected
        </span>
      </SettingsHeader>

      <DefaultModelGroup />

      <label className="flex h-10 items-center gap-2 rounded-lg bg-card px-3 text-sm shadow-hairline focus-within:shadow-[0_0_0_1px_var(--ring)]">
        <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape" && query) {
              event.preventDefault();
              setQuery("");
            }
          }}
          placeholder={`Search ${providers.length || ""} providers…`.replace("  ", " ")}
          aria-label="Search providers"
          className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground focus-visible:shadow-none"
        />
        {query && (
          <button type="button" aria-label="Clear search" onClick={() => setQuery("")} className="text-muted-foreground hover:text-foreground">
            <XIcon className="size-3.5" />
          </button>
        )}
        <span className="font-mono text-xs text-muted-foreground">{visible.length} providers</span>
      </label>
      <ModelsDevLine />

      {status !== "ready" && providers.length === 0 ? (
        <p className="text-sm text-muted-foreground">Providers appear once the engine is running.</p>
      ) : loading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoaderCircleIcon className="size-4 animate-spin" /> Loading providers…
        </p>
      ) : error ? (
        <div className="flex items-center justify-between gap-3 rounded-lg bg-card px-4 py-3 text-sm shadow-hairline">
          <span className="text-muted-foreground">Could not load providers: {error}</span>
          <Button size="sm" variant="outline" onClick={() => void load()}>
            Retry
          </Button>
        </div>
      ) : (
        <>
          <ProviderSection title="Connected" rows={sections.connectedRows} onOpen={setOpenId} />
          <ProviderSection
            title="Recommended"
            description="Where most people start — frontier vendors, the subscriptions you may already pay for, and MiMo."
            rows={sections.recommended}
            onOpen={setOpenId}
          />
          <ProviderSection title="More providers" rows={sections.curated} onOpen={setOpenId} />
          <ProviderSection
            title="From the models.dev catalog"
            description="Any OpenAI-compatible endpoint models.dev lists. Models are read from the provider once you connect it."
            rows={catalogRows}
            onOpen={setOpenId}
            footer={
              !searching && sections.catalog.length > CATALOG_PREVIEW ? (
                <button
                  type="button"
                  onClick={() => setShowAll((value) => !value)}
                  className="w-full px-5 py-3 text-left text-[13px] text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                >
                  {showAll ? "Show fewer" : `Show all ${sections.catalog.length}`}
                </button>
              ) : undefined
            }
          />
          <ProviderSection
            title="Coming soon"
            description="These need a sign-in flow or cloud credentials evo does not support yet."
            rows={sections.unavailable}
            onOpen={setOpenId}
          />
          {visible.length === 0 && <p className="text-sm text-muted-foreground">No provider matches “{query}”.</p>}
        </>
      )}

      <ProviderDialog row={open} onClose={() => setOpenId(null)} />
    </div>
  );
}

/** Where model lists, limits and prices come from: the models.dev database. */
/** The model new chats start with: the saved choice, or the engine's automatic pick. */
function DefaultModelGroup() {
  const models = useEngineStore((s) => s.models);
  const defaultModel = useEngineStore((s) => s.defaultModel);
  const saved = useEngineStore((s) => s.defaultSaved);
  const ready = useEngineStore((s) => s.status === "ready");
  const setDefaultModel = useEngineStore((s) => s.setDefaultModel);
  const current = models.find((m) => modelKey(m) === defaultModel);
  const groups = React.useMemo(() => {
    const byProvider = new Map<string, typeof models>();
    for (const model of models) byProvider.set(model.provider, [...(byProvider.get(model.provider) ?? []), model]);
    return [...byProvider.entries()];
  }, [models]);

  return (
    <SettingsGroup title="Default model">
      <SettingsRow
        label="New chats start with"
        description={
          saved
            ? "Saved in ~/.evo/agent/settings.json. Chats you already have keep their own model."
            : "Picked automatically from the providers you connected. Choose one to always start with it."
        }
        control={
          <div className="flex items-center gap-2">
            {saved && (
              <Button variant="ghost" size="sm" onClick={() => void setDefaultModel(null)}>
                Use automatic
              </Button>
            )}
            <DropdownMenu>
              <DropdownMenuTrigger
                disabled={!ready || models.length === 0}
                render={<Button variant="outline" size="sm" className="max-w-64" />}
              >
                {current && <ProviderIcon id={current.provider} size="xs" />}
                <span className="truncate">{current ? current.name || current.id : defaultModel ?? "Choose a model"}</span>
                {!saved && <span className="text-muted-foreground">· auto</span>}
                <ChevronRightIcon className="rotate-90" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="max-h-96 w-64">
                <DropdownMenuRadioGroup
                  value={saved ? (defaultModel ?? "") : ""}
                  onValueChange={(value) => {
                    const model = models.find((m) => modelKey(m) === value);
                    if (model) void setDefaultModel(model);
                  }}
                >
                  {groups.map(([provider, items], index) => (
                    <React.Fragment key={provider}>
                      {index > 0 && <DropdownMenuSeparator />}
                      <DropdownMenuGroup>
                        <DropdownMenuLabel className="flex items-center gap-2">
                          <ProviderIcon id={provider} size="xs" />
                          {provider}
                        </DropdownMenuLabel>
                        {items.map((model) => (
                          <DropdownMenuRadioItem key={modelKey(model)} value={modelKey(model)}>
                            <span className="truncate">{model.name || model.id}</span>
                          </DropdownMenuRadioItem>
                        ))}
                      </DropdownMenuGroup>
                    </React.Fragment>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        }
      />
    </SettingsGroup>
  );
}

function ModelsDevLine() {
  const status = useProviderStore((s) => s.modelsDev);
  const refreshCatalog = useProviderStore((s) => s.refreshCatalog);
  const [refreshing, setRefreshing] = React.useState(false);
  if (!status) return null;
  const updated = status.checkedAt ?? status.fetchedAt;
  return (
    <p className="-mt-5 flex flex-wrap items-center gap-x-1.5 px-1 text-xs text-muted-foreground">
      Models, limits and prices from
      <button type="button" className="underline underline-offset-2 hover:text-foreground" onClick={() => openLink("https://models.dev")}>
        models.dev
      </button>
      · {status.modelCount.toLocaleString()} models ·{" "}
      {status.source === "bundled" ? "offline snapshot" : updated ? `checked ${formatRelative(updated * 1000)}` : "cached"}
      <button
        type="button"
        disabled={refreshing}
        className="ml-1 inline-flex items-center gap-1 hover:text-foreground disabled:opacity-60"
        onClick={() => {
          setRefreshing(true);
          void refreshCatalog().finally(() => setRefreshing(false));
        }}
      >
        <RefreshCwIcon className={cn("size-3", refreshing && "animate-spin")} />
        Refresh
      </button>
    </p>
  );
}

function ProviderSection({
  title,
  description,
  rows,
  onOpen,
  footer,
}: {
  title: string;
  description?: string;
  rows: ProviderRow[];
  onOpen(id: string): void;
  footer?: React.ReactNode;
}) {
  if (rows.length === 0) return null;
  return (
    <section>
      <h2 className="text-sm font-semibold">{title}</h2>
      {description && <p className="mt-1 max-w-lg text-[13px] text-muted-foreground">{description}</p>}
      <div className="mt-3 divide-y overflow-hidden rounded-xl bg-card shadow-hairline">
        {rows.map((row) => (
          <ProviderListItem key={row.id} row={row} onOpen={() => onOpen(row.id)} />
        ))}
        {footer}
      </div>
    </section>
  );
}

function ProviderMark({ row, size = "md" }: { row: ProviderRow; size?: "md" | "lg" }) {
  return <ProviderIcon id={row.id} label={row.label} size={size} />;
}

function KindBadge({ kind }: { kind: ProviderKind }) {
  return (
    <span className="rounded border px-1.5 py-px font-mono text-[10px] tracking-wide text-muted-foreground uppercase">
      {KIND_LABEL[kind]}
    </span>
  );
}

function ProviderListItem({ row, onOpen }: { row: ProviderRow; onOpen(): void }) {
  const busy = useProviderStore((s) => s.busy[row.id]);
  return (
    <div className={cn("flex items-stretch", !row.supported && "opacity-70")}>
      <button
        type="button"
        onClick={onOpen}
        className="flex min-w-0 flex-1 items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none"
      >
        <ProviderMark row={row} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium">{row.label}</span>
            <KindBadge kind={row.kind} />
          </div>
          <p className="mt-0.5 truncate text-[13px] text-muted-foreground">
            {row.supported ? row.description : (row.unsupportedReason ?? row.description)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {busy && <LoaderCircleIcon className="size-3.5 animate-spin text-muted-foreground" />}
          {row.connected && (
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <StatusDot tone={row.discoveryError ? "warn" : "ok"} />
              Connected
            </span>
          )}
          {row.connected && row.modelCount > 0 && (
            <span className="rounded border px-1.5 py-px font-mono text-[11px] text-muted-foreground">
              {row.modelCount} models
            </span>
          )}
          <ChevronRightIcon className="size-4 text-muted-foreground" />
        </div>
      </button>
      {row.docsUrl && (
        <button
          type="button"
          aria-label={`Open ${row.label} website`}
          title="Get an API key"
          onClick={() => openLink(row.docsUrl)}
          className="flex w-12 shrink-0 items-center justify-center border-l text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
        >
          <ExternalLinkIcon className="size-4" />
        </button>
      )}
    </div>
  );
}

function ProviderDialog({ row, onClose }: { row: ProviderRow | null; onClose(): void }) {
  // Keep the last row while the dialog animates out.
  const [shown, setShown] = React.useState(row);
  React.useEffect(() => {
    if (row) setShown(row);
  }, [row]);
  return (
    <Dialog open={row !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">{shown && <ProviderForm key={shown.id} row={shown} />}</DialogContent>
    </Dialog>
  );
}

function ProviderForm({ row }: { row: ProviderRow }) {
  const busy = useProviderStore((s) => s.busy[row.id]);
  const save = useProviderStore((s) => s.save);
  const refreshModels = useProviderStore((s) => s.refreshModels);
  const remove = useProviderStore((s) => s.remove);
  const initial = React.useMemo(
    () => Object.fromEntries(row.fields.filter((f) => !f.secret).map((f) => [f.name, f.value ?? ""])),
    [row.fields],
  );
  const [values, setValues] = React.useState<Record<string, string>>(initial);
  const [message, setMessage] = React.useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const setValue = (name: string, value: string) => setValues((current) => ({ ...current, [name]: value }));

  // Only what the user changed is sent: a blank secret keeps the saved one.
  const changed = Object.fromEntries(
    Object.entries(values).filter(([name, value]) => {
      const field = row.fields.find((f) => f.name === name);
      if (!field) return false;
      return field.secret ? value.trim() !== "" : value.trim() !== (field.value ?? "");
    }),
  );
  const missing = row.fields.some(
    (f) => f.required && !f.hasValue && !f.fromEnv && !(f.value ?? "").trim() && !(values[f.name] ?? "").trim(),
  );
  const canSave =
    row.supported && !busy && !missing && (Object.keys(changed).length > 0 || (!row.connected && row.fields.length > 0));
  const hasSomething = row.connected || row.fields.some((f) => f.hasValue || f.value);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSave) return;
    setMessage(null);
    try {
      const result = await save(row.id, changed);
      setValues((current) =>
        Object.fromEntries(Object.entries(current).map(([name, value]) => [name, row.fields.find((f) => f.name === name)?.secret ? "" : value])),
      );
      if (result.reload?.error) setMessage({ tone: "error", text: `Saved, but the engine could not switch: ${result.reload.error}` });
      else if (result.discovery && !result.discovery.ok)
        setMessage({ tone: "error", text: `Saved, but checking the connection failed: ${result.discovery.error}` });
      else
        setMessage({
          tone: "ok",
          text: result.discovery?.modelCount
            ? `Connected — ${result.discovery.modelCount} models available.`
            : `Saved — ${result.provider?.modelCount ?? 0} models available.`,
        });
    } catch (error) {
      setMessage({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  async function refresh() {
    setMessage(null);
    try {
      const result = await refreshModels(row.id);
      setMessage(
        result.discovery?.ok
          ? { tone: "ok", text: `${result.provider?.modelCount ?? result.discovery.modelCount ?? 0} models available.` }
          : { tone: "error", text: result.discovery?.error ?? "Could not list models." },
      );
    } catch (error) {
      setMessage({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  async function disconnect() {
    setMessage(null);
    try {
      await remove(row.id);
      setValues(Object.fromEntries(Object.keys(values).map((name) => [name, ""])));
      setMessage({ tone: "ok", text: row.login ? "Signed out." : "Disconnected. The saved credentials were removed." });
    } catch (error) {
      setMessage({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-5">
      <DialogHeader className="flex-row items-center gap-3">
        <ProviderMark row={row} size="lg" />
        <div className="min-w-0 flex-1">
          <DialogTitle className="flex items-center gap-2">
            {row.label}
            <KindBadge kind={row.kind} />
          </DialogTitle>
          <DialogDescription className="mt-0.5">{row.description}</DialogDescription>
        </div>
      </DialogHeader>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-lg bg-muted/40 px-3 py-2.5 text-[13px]">
        <dt className="text-muted-foreground">Status</dt>
        <dd className="flex items-center gap-1.5">
          <StatusDot tone={!row.supported ? "idle" : row.connected ? (row.discoveryError ? "warn" : "ok") : "idle"} />
          {!row.supported ? "Not available yet" : row.connected ? "Connected" : "Not connected"}
          {row.connected && row.account && <span className="truncate text-muted-foreground">· {row.account}</span>}
          {row.connected &&
            !row.login &&
            row.credentialSource &&
            !["auth.json", "anonymous", "oauth"].includes(row.credentialSource) && (
              <span className="text-muted-foreground">· key from {row.credentialSource}</span>
            )}
        </dd>
        {row.baseUrl && (
          <>
            <dt className="text-muted-foreground">Endpoint</dt>
            <dd className="truncate font-mono text-xs leading-5" title={row.baseUrl}>
              {row.baseUrl}
            </dd>
          </>
        )}
        <dt className="text-muted-foreground">Protocol</dt>
        <dd className="font-mono text-xs leading-5">{row.api}</dd>
        {row.supported && (
          <>
            <dt className="text-muted-foreground">Models</dt>
            <dd>
              {row.modelCount}
              <span className="text-muted-foreground">
                {row.discoveredAt ? ` · listed by ${row.label} ${formatRelative(row.discoveredAt * 1000)}` : " · from models.dev"}
              </span>
            </dd>
          </>
        )}
        {row.discoveryError && (
          <>
            <dt className="text-muted-foreground">Last check</dt>
            <dd className="text-destructive">{row.discoveryError}</dd>
          </>
        )}
      </dl>

      {!row.supported ? (
        <p className="text-sm text-muted-foreground">{row.unsupportedReason}</p>
      ) : row.login ? (
        <SignInPanel row={row} />
      ) : (
        <div className="flex flex-col gap-4">
          {row.keyLogin && <KeySignIn row={row} />}
          {row.id === "bedrock" && (
            <p className="text-[13px] text-muted-foreground">
              Use one of: a Bedrock API key, an IAM access key pair, or an AWS profile from ~/.aws (SSO,
              credential_process or keys). Leave the others blank.
            </p>
          )}
          {row.fields.map((field) => (
            <label key={field.name} className="flex flex-col gap-1.5">
              <span className="flex items-center justify-between text-[13px] font-medium">
                {field.label}
                {field.env ? (
                  <span className="font-mono text-[11px] font-normal text-muted-foreground">{field.env}</span>
                ) : field.name === "baseUrl" ? (
                  <span className="text-[11px] font-normal text-muted-foreground">Optional — for proxies and regional hosts</span>
                ) : field.name === "deployments" ? (
                  <span className="text-[11px] font-normal text-muted-foreground">Comma-separated deployment names</span>
                ) : null}
              </span>
              <Input
                type={field.secret ? "password" : "text"}
                autoComplete="off"
                spellCheck={false}
                value={values[field.name] ?? ""}
                onChange={(event) => setValue(field.name, event.target.value)}
                placeholder={
                  field.secret
                    ? field.hasValue
                      ? "Saved — enter a new value to replace it"
                      : field.fromEnv
                        ? `Using ${field.fromEnv} from the environment`
                        : "Paste here"
                    : (field.placeholder ?? "")
                }
                className={cn("font-mono", !field.secret && "text-xs")}
              />
            </label>
          ))}
        </div>
      )}

      {row.supported && row.usage && row.connected && <PlanUsage providerId={row.id} />}

      {message && (
        <p
          role="status"
          className={cn("flex items-start gap-1.5 text-[13px]", message.tone === "error" ? "text-destructive" : "text-muted-foreground")}
        >
          {message.tone === "ok" && <CheckIcon className="mt-0.5 size-3.5 shrink-0" />}
          {message.text}
        </p>
      )}

      <DialogFooter className="flex-row items-center sm:justify-between">
        <div className="flex items-center gap-1">
          {row.docsUrl && (
            <Button type="button" variant="ghost" size="sm" onClick={() => openLink(row.docsUrl)}>
              <ExternalLinkIcon />
              {row.login ? "Plans" : "Get a key"}
            </Button>
          )}
        </div>
        <div className="flex items-center gap-2">
          {row.supported && hasSomething && (
            <Button type="button" variant="ghost" size="sm" disabled={Boolean(busy)} onClick={() => void disconnect()}>
              {busy === "removing" ? <LoaderCircleIcon className="animate-spin" /> : <Trash2Icon />}
              {row.login ? "Sign out" : "Disconnect"}
            </Button>
          )}
          {row.supported && row.connected && (
            <Button type="button" variant="outline" size="sm" disabled={Boolean(busy)} onClick={() => void refresh()}>
              {busy === "refreshing" ? <LoaderCircleIcon className="animate-spin" /> : <RefreshCwIcon />}
              Refresh models
            </Button>
          )}
          {row.supported && !row.login && (
            <Button type="submit" size="sm" disabled={!canSave}>
              {busy === "saving" && <LoaderCircleIcon className="animate-spin" />}
              {row.connected ? "Save" : "Connect"}
            </Button>
          )}
        </div>
      </DialogFooter>
    </form>
  );
}

const SIGN_IN_LABEL: Record<string, string> = {
  codex: "Sign in with ChatGPT",
  copilot: "Sign in with GitHub",
  xiaomi: "Sign in with Xiaomi",
};

/**
 * A sign-in that creates the API key for the person (Xiaomi MiMo): the
 * platform mints a key and hands it back encrypted, so nothing is pasted.
 */
function KeySignIn({ row }: { row: ProviderRow }) {
  const login = useProviderStore((s) => s.login);
  const cancelLogin = useProviderStore((s) => s.cancelLogin);
  const busy = useProviderStore((s) => s.busy[row.id]);
  const state = row.loginState;
  const pending = state?.status === "pending";
  const [error, setError] = React.useState<string>();

  async function start() {
    setError(undefined);
    try {
      const started = await login(row.id);
      if (started.url) openLink(started.url);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg px-3 py-2.5 shadow-hairline">
      {pending ? (
        <div className="flex items-center justify-between gap-3 text-[13px] text-muted-foreground">
          <span className="flex items-center gap-2">
            <LoaderCircleIcon className="size-3.5 animate-spin" />
            Finish signing in in your browser…
            {state?.url && (
              <button type="button" className="underline underline-offset-2" onClick={() => openLink(state.url!)}>
                Open again
              </button>
            )}
          </span>
          <Button type="button" variant="ghost" size="sm" onClick={() => void cancelLogin(row.id)}>
            Cancel
          </Button>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-3">
          <span className="text-[13px] text-muted-foreground">
            {row.connected ? "Signed in? Sign in again to create a new key." : "No key yet? Sign in and evo creates one for you."}
          </span>
          <Button type="button" size="sm" variant="outline" onClick={() => void start()} disabled={Boolean(busy)}>
            {busy === "signing-in" ? <LoaderCircleIcon className="animate-spin" /> : <LogInIcon />}
            {SIGN_IN_LABEL[row.keyLogin ?? ""] ?? "Sign in"}
          </Button>
        </div>
      )}
      {(error || state?.status === "error") && (
        <p role="alert" className="text-[13px] text-destructive">
          {error ?? state?.error}
        </p>
      )}
      {state?.status === "success" && !pending && (
        <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
          <CheckIcon className="size-3.5" /> Key created{state.account ? ` for ${state.account}` : ""}.
        </p>
      )}
    </div>
  );
}

/** "in 3 h", "in 2 d", "now". */
function until(at: number): string {
  const minutes = Math.round((at * 1000 - Date.now()) / 60_000);
  if (minutes <= 0) return "now";
  if (minutes < 60) return `in ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `in ${hours} h`;
  return `in ${Math.round(hours / 24)} d`;
}

function UsageRow({ limit }: { limit: UsageLimit }) {
  const percent = limit.usedPercent ?? undefined;
  const counted = limit.total != null && limit.used != null ? `${Math.round(limit.used)} / ${Math.round(limit.total)}` : null;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3 text-[13px]">
        <span className={cn("font-medium", limit.reached && "text-destructive")}>{limit.name}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {limit.unlimited
            ? "Unlimited"
            : [counted, percent !== undefined ? `${Math.round(percent)}% used` : null, limit.resetsAt ? `resets ${until(limit.resetsAt)}` : null]
                .filter(Boolean)
                .join(" · ")}
        </span>
      </div>
      {!limit.unlimited && percent !== undefined && (
        <Progress value={Math.min(100, Math.max(0, percent))} className={cn(limit.reached && "[&_[data-slot=progress-indicator]]:bg-destructive")} />
      )}
    </div>
  );
}

/** How much of the subscription is left (Codex, Copilot, OpenCode Go). */
function PlanUsage({ providerId }: { providerId: string }) {
  const usage = useProviderStore((s) => s.usage);
  const [data, setData] = React.useState<ProviderUsage>();
  const [error, setError] = React.useState<string>();
  const [loading, setLoading] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(undefined);
    try {
      setData(await usage(providerId));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setLoading(false);
    }
  }, [usage, providerId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="flex flex-col gap-3 rounded-lg px-3 py-3 shadow-hairline">
      <div className="flex items-center justify-between">
        <h3 className="text-[13px] font-semibold">
          Plan usage
          {data?.plan && <span className="ml-1.5 font-normal text-muted-foreground capitalize">· {data.plan}</span>}
        </h3>
        <Button type="button" variant="ghost" size="icon-sm" aria-label="Refresh usage" onClick={() => void load()} disabled={loading}>
          <RefreshCwIcon className={cn(loading && "animate-spin")} />
        </Button>
      </div>
      {error ? (
        <p className="text-[13px] text-destructive">{error}</p>
      ) : !data ? (
        <p className="text-[13px] text-muted-foreground">Loading…</p>
      ) : data.limits.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">The provider reported no limits.</p>
      ) : (
        data.limits.map((limit) => <UsageRow key={limit.id} limit={limit} />)
      )}
    </section>
  );
}

/** Subscription sign-in: opens the browser, shows the device code, waits. */
function SignInPanel({ row }: { row: ProviderRow }) {
  const login = useProviderStore((s) => s.login);
  const cancelLogin = useProviderStore((s) => s.cancelLogin);
  const busy = useProviderStore((s) => s.busy[row.id]);
  const state = row.loginState;
  const pending = state?.status === "pending";
  const [copied, setCopied] = React.useState(false);
  const [error, setError] = React.useState<string>();

  async function start() {
    setError(undefined);
    try {
      const started = await login(row.id);
      if (started.url) openLink(started.url);
      if (started.userCode) void navigator.clipboard?.writeText(started.userCode).catch(() => undefined);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  }

  if (row.connected && !pending) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-[13px] shadow-hairline">
        <span className="flex min-w-0 items-center gap-2">
          <CheckIcon className="size-4 shrink-0 text-brand" />
          <span className="truncate">Signed in{row.account ? ` as ${row.account}` : ""}.</span>
        </span>
        <Button type="button" variant="ghost" size="sm" onClick={() => void start()} disabled={Boolean(busy)}>
          Switch account
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {pending ? (
        <div className="flex flex-col gap-3 rounded-lg px-4 py-3 shadow-hairline">
          {state?.userCode ? (
            <>
              <p className="text-[13px] text-muted-foreground">
                Enter this code on GitHub to let evo use your Copilot subscription. It was copied to your clipboard.
              </p>
              <div className="flex items-center justify-between gap-3">
                <code className="rounded-md bg-muted px-3 py-1.5 font-mono text-lg tracking-[0.3em]">{state.userCode}</code>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      void navigator.clipboard?.writeText(state.userCode ?? "");
                      setCopied(true);
                      window.setTimeout(() => setCopied(false), 1500);
                    }}
                  >
                    {copied ? <CheckIcon /> : <CopyIcon />}
                    {copied ? "Copied" : "Copy"}
                  </Button>
                  {state.url && (
                    <Button type="button" size="sm" onClick={() => openLink(state.url!)}>
                      <ExternalLinkIcon />
                      Open GitHub
                    </Button>
                  )}
                </div>
              </div>
            </>
          ) : (
            <p className="text-[13px] text-muted-foreground">
              Finish signing in in your browser.{" "}
              {state?.url && (
                <button type="button" className="underline underline-offset-2" onClick={() => openLink(state.url!)}>
                  Open the sign-in page again
                </button>
              )}
            </p>
          )}
          <div className="flex items-center justify-between text-[13px] text-muted-foreground">
            <span className="flex items-center gap-2">
              <LoaderCircleIcon className="size-3.5 animate-spin" /> Waiting for approval…
            </span>
            <Button type="button" variant="ghost" size="sm" onClick={() => void cancelLogin(row.id)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <Button type="button" onClick={() => void start()} disabled={Boolean(busy)} className="self-start">
          {busy === "signing-in" ? <LoaderCircleIcon className="animate-spin" /> : <LogInIcon />}
          {SIGN_IN_LABEL[row.login ?? ""] ?? "Sign in"}
        </Button>
      )}
      {(error || state?.status === "error") && (
        <p role="alert" className="text-[13px] text-destructive">
          {error ?? state?.error}
        </p>
      )}
    </div>
  );
}
