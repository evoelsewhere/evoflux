import * as React from "react";
import { CircleAlertIcon, CircleCheckIcon, LightbulbIcon, RefreshCwIcon, Trash2Icon, XIcon } from "lucide-react";
import { UsageIcon } from "@/components/icons/tool-icons";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { ModelDescriptor } from "@/engine/protocol";
import type { UsageEvent, UsageSource, UsageSummary } from "@/lib/db";
import { formatDuration, formatRelative, formatTokens } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { useSessionStore } from "@/stores/session-store";
import { useUiStore } from "@/stores/ui-store";
import { BUCKETS, rangeStart, USAGE_RANGES, useUsageStore, type UsageRange } from "@/stores/usage-store";
import { Badge, EmptyNote } from "@/features/customize/customize-parts";
import {
  alternatives,
  DAY_MS,
  efficiency,
  fillSeries,
  findModel,
  hasPrice,
  insights,
  modelKey,
  OTHER,
  OTHER_COLOR,
  promptOf,
  tokensOf,
  type Insight,
  type ModelEfficiency,
} from "./analysis";
import { Legend, ModelBars, TimeChart, type Metric, type SeriesInfo } from "./usage-charts";

// Usage (sidebar → Usage): what the models cost and how well they used it,
// from the history every chat's engine records (`stores/usage-store.ts`).
// Totals and rates; spend, tokens or responses over time by model; what
// stands out; model efficiency (cost per response, per 1k output tokens,
// speed, cache, failures) against today's models.dev prices; what the same
// tokens would cost on other models; then by chat, by source and the latest
// responses. Design: docs/features/usage-and-cost/sdd.md.

const REFRESH_MS = 15_000;

const SOURCE_LABELS: Record<UsageSource, string> = {
  chat: "Chats",
  subagent: "Subagents",
  plugin: "Plugin runs",
  side: "Side questions",
};

const METRICS: { id: Metric; label: string }[] = [
  { id: "cost", label: "Spend" },
  { id: "tokens", label: "Tokens" },
  { id: "requests", label: "Responses" },
];

/** $0, <$0.0001, $0.0042, $0.053, $1.27, $128. */
function usd(value: number): string {
  if (!value) return "$0";
  if (value < 0.0001) return "<$0.0001";
  if (value >= 100) return `$${Math.round(value).toLocaleString()}`;
  if (value >= 1) return `$${value.toFixed(2)}`;
  if (value >= 0.01) return `$${value.toFixed(3)}`;
  return `$${value.toFixed(4)}`;
}

/** A per-million rate: $3, $0.3, $15. */
function rate(value: number): string {
  if (!value) return "$0";
  return `$${Number(value.toPrecision(3))}`;
}

const percent = (value: number | null) => (value === null ? "—" : `${Math.round(value * 100)}%`);

function responses(count: number): string {
  return `${count.toLocaleString()} ${count === 1 ? "response" : "responses"}`;
}

export function UsagePage() {
  const { range, bucket, model, summary, recent, loading, error, setRange, setBucket, setModel, load } = useUsageStore();
  const models = useEngineStore((s) => s.models);

  React.useEffect(() => {
    void useUsageStore.getState().load();
    const timer = window.setInterval(() => void useUsageStore.getState().load(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  const modelName = model ? (findModel(models, model.providerId, model.modelId)?.name ?? model.modelId) : null;

  return (
    <div className="@container flex h-full min-h-0 flex-col bg-background min-[900px]:rounded-tl-xl">
      <header className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border/60 px-4 py-2.5">
        <UsageIcon className="size-4 text-brand" />
        <h1 className="text-sm font-semibold">Usage</h1>
        <Segmented label="Time range" options={USAGE_RANGES} value={range} onChange={setRange} />
        <span className="h-4 w-px bg-border" />
        <Segmented label="Group by" options={BUCKETS} value={bucket} onChange={setBucket} />
        {model && (
          <span className="inline-flex h-7 items-center gap-1 rounded-md bg-muted pr-1 pl-2.5 text-xs dark:bg-accent">
            {modelName}
            <button
              type="button"
              aria-label="Show every model"
              onClick={() => setModel(null)}
              className="flex size-5 items-center justify-center rounded text-muted-foreground hover:text-foreground"
            >
              <XIcon className="size-3" />
            </button>
          </span>
        )}
        <span className="flex-1" />
        <Button size="icon-sm" variant="ghost" aria-label="Refresh" onClick={() => void load()} className="text-muted-foreground">
          {loading ? <Spinner className="size-3.5" /> : <RefreshCwIcon className="size-3.5" />}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => useUiStore.getState().closeCustomize()}>
          Close
        </Button>
      </header>
      <div className="scrollbar-slim min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-6xl flex-col gap-7 px-6 py-5">
          {!summary ? (
            <div className="flex justify-center py-16">
              {error ? (
                <p className="max-w-sm text-center text-[13px] text-muted-foreground">Could not read the usage history: {error}</p>
              ) : (
                <Spinner className="size-4 text-muted-foreground" />
              )}
            </div>
          ) : summary.totals.requests === 0 ? (
            <EmptyNote title={summary.firstMs === null ? "No usage yet" : "Nothing in this range"}>
              {summary.firstMs === null
                ? "Every model response a chat gets is counted here with its tokens, time and cost at the model's models.dev price."
                : "Pick a longer range, or show every model."}
            </EmptyNote>
          ) : (
            <UsageReport summary={summary} recent={recent} range={range} models={models} />
          )}
          {summary && summary.firstMs !== null && <ClearHistory />}
        </div>
      </div>
    </div>
  );
}

function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { id: T; label: string }[];
  value: T;
  onChange(value: T): void;
}) {
  return (
    <div className="flex gap-0.5" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={value === o.id}
          onClick={() => onChange(o.id)}
          className={cn(
            "h-7 rounded-md px-2.5 text-xs transition-colors",
            value === o.id ? "bg-brand/12 text-brand" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function UsageReport({
  summary,
  recent,
  range,
  models,
}: {
  summary: UsageSummary;
  recent: UsageEvent[];
  range: UsageRange;
  models: ModelDescriptor[];
}) {
  const { totals } = summary;
  // Rates over the days the history covers: a range longer than the history
  // would understate them.
  const first = summary.firstMs === null ? Date.now() : new Date(summary.firstMs).setHours(0, 0, 0, 0);
  const start = Math.max(rangeStart(range) ?? first, first);
  const days = Math.max(1, Math.ceil((Date.now() - start) / DAY_MS));
  const perDay = totals.costUsd / days;
  const prompt = promptOf(totals);
  const rows = React.useMemo(() => efficiency(summary, models), [summary, models]);
  const saved = rows.reduce((sum, r) => sum + (r.cacheSaved ?? 0), 0);
  const speed = totals.timedMs > 0 ? totals.timedOutput / (totals.timedMs / 1000) : null;
  const notes = React.useMemo(() => insights(summary, rows, usd, formatTokens), [summary, rows]);

  return (
    <>
      <section className="grid grid-cols-2 gap-3 @2xl:grid-cols-4" aria-label="Totals">
        <Stat label="Spend" value={usd(totals.costUsd)} note={responses(totals.requests)} />
        <Stat label="Per day" value={usd(perDay)} note={`≈ ${usd(perDay * 30)} a month at this rate`} />
        <Stat
          label="Per response"
          value={usd(totals.requests ? totals.costUsd / totals.requests : 0)}
          note={`${formatTokens(totals.requests ? prompt / totals.requests : 0)} prompt · ${formatTokens(totals.requests ? totals.output / totals.requests : 0)} out on average`}
        />
        <Stat label="Tokens" value={formatTokens(tokensOf(totals))} note={`${formatTokens(totals.input)} in · ${formatTokens(totals.output)} out`} />
        <Stat
          label="From cache"
          value={prompt ? `${Math.round((totals.cacheRead / prompt) * 100)}%` : "—"}
          note={`${formatTokens(totals.cacheRead)} read · ${formatTokens(totals.cacheWrite)} written`}
        />
        <Stat label="Saved by cache" value={saved > 0 ? usd(saved) : "—"} note="at today's models.dev input price" />
        <Stat
          label="Speed"
          value={speed === null ? "—" : `${Math.round(speed)} tok/s`}
          note={totals.timed ? `${formatDuration(totals.timedMs / totals.timed)} per response` : "timed responses only"}
        />
        <Stat
          label="Failed or stopped"
          value={totals.errors.toLocaleString()}
          note={totals.errors ? `${usd(totals.costErrors)} spent on them` : "none in this range"}
        />
      </section>

      <OverTime summary={summary} rows={rows} start={start} />

      {notes.length > 0 && <Insights notes={notes} />}

      <ModelEfficiencySection rows={rows} />

      <PriceCheck rows={rows} models={models} />

      <section className="grid gap-6 @3xl:grid-cols-2">
        <Panel title="What it went on">
          <Shares
            total={totals.costUsd}
            rows={[
              ["Input", totals.costInput, `${formatTokens(totals.input)} tokens`],
              ["Output", totals.costOutput, `${formatTokens(totals.output)} tokens`],
              ["Cache reads", totals.costCacheRead, `${formatTokens(totals.cacheRead)} tokens`],
              ["Cache writes", totals.costCacheWrite, `${formatTokens(totals.cacheWrite)} tokens`],
            ]}
          />
        </Panel>
        <Panel title="By source">
          <Shares
            total={totals.costUsd}
            rows={summary.bySource.map((s) => [
              SOURCE_LABELS[s.source] ?? s.source,
              s.costUsd,
              `${responses(s.requests)} · ${formatTokens(tokensOf(s))} tokens`,
            ])}
          />
        </Panel>
      </section>

      <ChatTable summary={summary} />
      <RecentTable recent={recent} models={models} />
    </>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-xl p-3.5 shadow-[0_0_0_1px_var(--border)]">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-2xl font-semibold tracking-tight">{value}</span>
      <span className="truncate text-xs text-muted-foreground" title={note}>
        {note}
      </span>
    </div>
  );
}

function Panel({ title, note, action, children }: { title: string; note?: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="flex min-w-0 flex-col gap-2.5">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <h2 className="text-[13px] font-medium">{title}</h2>
        {note && <span className="text-xs text-muted-foreground">{note}</span>}
        <span className="flex-1" />
        {action}
      </div>
      {children}
    </section>
  );
}

const CARD = "rounded-xl shadow-[0_0_0_1px_var(--border)]";

function OverTime({ summary, rows, start }: { summary: UsageSummary; rows: ModelEfficiency[]; start: number }) {
  const [metric, setMetric] = React.useState<Metric>("cost");
  const buckets = React.useMemo(() => fillSeries(summary, start), [summary, start]);
  const series: SeriesInfo[] = rows.slice(0, 4).map((r) => ({ key: r.key, name: r.name, color: r.color }));
  if (rows.length > 4) series.push({ key: OTHER, name: `Other (${rows.length - 4})`, color: OTHER_COLOR });
  const format = metric === "cost" ? usd : metric === "tokens" ? formatTokens : (v: number) => String(Math.round(v * 10) / 10);
  const unit = summary.bucket === "hour" ? "hour" : summary.bucket === "week" ? "week" : "day";
  return (
    <Panel
      title="Over time"
      note={`per ${unit}, by model`}
      action={<Segmented<Metric> label="Measure" options={METRICS} value={metric} onChange={setMetric} />}
    >
      <div className={cn(CARD, "flex flex-col gap-3 p-3.5")}>
        <Legend series={series} />
        <TimeChart buckets={buckets} bucket={summary.bucket} metric={metric} series={series} format={format} />
      </div>
    </Panel>
  );
}

function Insights({ notes }: { notes: Insight[] }) {
  return (
    <Panel title="What stands out">
      <ul className={cn(CARD, "flex flex-col divide-y divide-border/60")}>
        {notes.map((n, i) => (
          <li key={i} className="flex gap-2.5 px-3.5 py-2.5 text-[13px]">
            {n.tone === "warn" ? (
              <CircleAlertIcon className="mt-0.5 size-4 shrink-0 text-amber-500" aria-label="Worth a look" />
            ) : n.tone === "good" ? (
              <CircleCheckIcon className="mt-0.5 size-4 shrink-0 text-emerald-500" aria-label="Good" />
            ) : (
              <LightbulbIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-label="Note" />
            )}
            <span className="text-pretty">{n.text}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

const TH = "px-2 py-1.5 text-left text-xs font-normal whitespace-nowrap text-muted-foreground";
const TD = "px-2 py-2 align-top";

function ModelEfficiencySection({ rows }: { rows: ModelEfficiency[] }) {
  const setModel = useUsageStore((s) => s.setModel);
  const filtered = useUsageStore((s) => s.model);
  return (
    <Panel title="Model efficiency" note="what each model costs for the work it does">
      <div className="grid gap-3 @3xl:grid-cols-3">
        <ModelBars title="Cost per response" note="lower is cheaper per turn" rows={rows} value={(r) => r.costPerResponse} format={usd} better="low" />
        <ModelBars
          title="Cost per 1k output tokens"
          note="what produced text costs, prompt included"
          rows={rows}
          value={(r) => r.costPer1kOutput}
          format={usd}
          better="low"
        />
        <ModelBars
          title="Output speed"
          note="tokens per second over the whole response"
          rows={rows}
          value={(r) => r.speed}
          format={(v) => `${Math.round(v)} tok/s`}
          better="high"
        />
      </div>
      <div className={cn(CARD, "overflow-x-auto")}>
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-border/60">
              <th className={TH}>Model</th>
              <th className={cn(TH, "text-right")}>Spend</th>
              <th className={cn(TH, "text-right")}>Responses</th>
              <th className={cn(TH, "text-right")} title="Prompt tokens per response: input, cache reads and writes">
                Avg prompt
              </th>
              <th className={cn(TH, "text-right")}>Avg output</th>
              <th className={cn(TH, "text-right")}>Cache hit</th>
              <th className={cn(TH, "text-right")} title="What was paid per million tokens of every kind">
                Paid / 1M
              </th>
              <th className={TH}>Price now (models.dev)</th>
              <th className={cn(TH, "text-right")}>Latency</th>
              <th className={cn(TH, "text-right")}>Failed</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.key}
                onClick={() => setModel(filtered ? null : { providerId: r.providerId, modelId: r.modelId })}
                title={filtered ? "Show every model" : "Show only this model"}
                className="cursor-default border-b border-border/40 last:border-0 hover:bg-accent/40"
              >
                <td className={TD}>
                  <div className="flex items-start gap-2">
                    <span className="mt-1.5 size-2.5 shrink-0 rounded-[3px]" style={{ background: r.color }} />
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate font-medium">{r.name}</span>
                      <span className="truncate text-xs text-muted-foreground">
                        {r.providerId} · {formatRelative(r.totals.lastMs)}
                      </span>
                    </div>
                  </div>
                </td>
                <td className={cn(TD, "text-right tabular-nums")}>
                  <div className="flex flex-col">
                    <span className="font-medium">{usd(r.totals.costUsd)}</span>
                    <span className="text-xs text-muted-foreground">{percent(r.share)}</span>
                  </div>
                </td>
                <td className={cn(TD, "text-right tabular-nums")}>{r.totals.requests.toLocaleString()}</td>
                <td className={cn(TD, "text-right tabular-nums")}>{formatTokens(r.avgPrompt)}</td>
                <td className={cn(TD, "text-right tabular-nums")}>{formatTokens(r.avgOutput)}</td>
                <td className={cn(TD, "text-right tabular-nums")}>
                  <div className="flex flex-col">
                    <span>{percent(r.cacheHit)}</span>
                    {r.cacheSaved !== null && r.cacheSaved > 0 && <span className="text-xs text-muted-foreground">saved {usd(r.cacheSaved)}</span>}
                  </div>
                </td>
                <td className={cn(TD, "text-right tabular-nums")}>{r.effectivePerM === null ? "—" : rate(r.effectivePerM)}</td>
                <td className={TD}>
                  <Price row={r} />
                </td>
                <td className={cn(TD, "text-right whitespace-nowrap tabular-nums")}>
                  {r.avgLatencyMs === null ? "—" : formatDuration(r.avgLatencyMs)}
                </td>
                <td className={cn(TD, "text-right tabular-nums")}>
                  {r.totals.errors ? (
                    <div className="flex flex-col">
                      <span>{percent(r.errorRate)}</span>
                      <span className="text-xs text-muted-foreground">{usd(r.totals.costErrors)}</span>
                    </div>
                  ) : (
                    "0"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

/** Today's models.dev price for a model, or why there is none. */
function Price({ row }: { row: ModelEfficiency }) {
  const cost = row.price;
  if (!hasPrice(cost)) {
    if (row.priceConfigured) return <Badge>Free</Badge>;
    return (
      <span title="models.dev has no price for this model, so its responses count as $0">
        <Badge>No price</Badge>
      </span>
    );
  }
  const tiers = cost.tiers?.length ?? 0;
  return (
    <span
      className="text-xs whitespace-nowrap text-muted-foreground tabular-nums"
      title={`Per million tokens: input ${rate(cost.input)}, output ${rate(cost.output)}, cache read ${rate(cost.cacheRead)}, cache write ${rate(cost.cacheWrite)}${tiers ? `; higher rates above ${formatTokens(cost.tiers![0].inputTokensAbove)} input tokens` : ""}`}
    >
      {rate(cost.input)} in · {rate(cost.output)} out
      {cost.cacheRead > 0 && ` · ${rate(cost.cacheRead)} cached`}
      {tiers > 0 && " · tiered"}
    </span>
  );
}

const ALTERNATIVES_SHOWN = 8;

function PriceCheck({ rows, models }: { rows: ModelEfficiency[]; models: ModelDescriptor[] }) {
  const candidates = rows.filter((r) => tokensOf(r.totals) > 0);
  const [picked, setPicked] = React.useState<string | null>(null);
  const row = candidates.find((r) => r.key === picked) ?? candidates[0];
  const used = React.useMemo(() => new Set(rows.map((r) => r.key)), [rows]);
  const list = React.useMemo(() => (row ? alternatives(row, models, used) : []), [row, models, used]);
  if (!row || list.length < 2) return null;
  const current = list.find((a) => a.current);
  const shown = list.slice(0, ALTERNATIVES_SHOWN);
  if (current && !shown.includes(current)) shown.push(current);
  const max = Math.max(...shown.map((a) => a.cost), row.totals.costUsd);
  return (
    <Panel
      title="Price check"
      note="the same tokens at other models' models.dev prices — price only, not quality"
      action={
        candidates.length > 1 && (
          <select
            value={row.key}
            onChange={(e) => setPicked(e.target.value)}
            className="h-7 rounded-md bg-muted px-2 text-xs outline-none dark:bg-accent"
            aria-label="Model to compare"
          >
            {candidates.map((r) => (
              <option key={r.key} value={r.key}>
                {r.name}
              </option>
            ))}
          </select>
        )
      }
    >
      <div className={cn(CARD, "flex flex-col gap-2 p-3.5")}>
        <p className="text-xs text-muted-foreground">
          {row.name} used {formatTokens(row.totals.input)} input, {formatTokens(row.totals.cacheRead)} cached,{" "}
          {formatTokens(row.totals.cacheWrite)} cache-write and {formatTokens(row.totals.output)} output tokens for {usd(row.totals.costUsd)}.
        </p>
        {shown.map((a) => (
          <div key={modelKey(a.descriptor.provider, a.descriptor.id)} className="grid grid-cols-[minmax(0,14rem)_1fr_auto_auto] items-center gap-3 text-xs">
            <span className={cn("truncate", a.current && "font-medium")}>
              {a.descriptor.name}
              {a.descriptor.provider !== row.providerId && <span className="text-muted-foreground"> · {a.descriptor.provider}</span>}
            </span>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted dark:bg-accent">
              <div
                className={cn("h-full rounded-full", a.current ? "bg-brand" : "bg-foreground/30")}
                style={{ width: `${max > 0 ? (a.cost / max) * 100 : 0}%` }}
              />
            </div>
            <span className="w-16 text-right font-medium tabular-nums">{usd(a.cost)}</span>
            <span className={cn("w-20 text-right tabular-nums", a.current ? "text-muted-foreground" : a.delta < 0 ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground")}>
              {a.current ? "current" : `${a.delta < 0 ? "−" : "+"}${percent(Math.abs(a.delta) / Math.max(row.totals.costUsd, 1e-9))}`}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

/** Rows of label, amount and a meter of its share of `total`. */
function Shares({ total, rows }: { total: number; rows: [string, number, string][] }) {
  return (
    <div className={cn(CARD, "flex flex-col gap-2.5 p-3.5")}>
      {rows.map(([label, amount, note]) => {
        const share = total > 0 ? amount / total : 0;
        return (
          <div key={label} className="flex flex-col gap-1">
            <div className="flex items-baseline gap-2 text-[13px]">
              <span>{label}</span>
              <span className="truncate text-xs text-muted-foreground">{note}</span>
              <span className="flex-1" />
              <span className="tabular-nums">{usd(amount)}</span>
              <span className="w-10 text-right text-xs text-muted-foreground tabular-nums">{Math.round(share * 100)}%</span>
            </div>
            <div className="h-1 overflow-hidden rounded-full bg-muted dark:bg-accent">
              <div className="h-full rounded-full bg-brand" style={{ width: `${Math.min(100, Math.max(0, share * 100))}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

const CHATS_SHOWN = 10;

function ChatTable({ summary }: { summary: UsageSummary }) {
  const [all, setAll] = React.useState(false);
  const sessions = useSessionStore((s) => s.sessions);
  const rows = all ? summary.byChat : summary.byChat.slice(0, CHATS_SHOWN);
  const open = (id: string) => {
    useUiStore.getState().closeCustomize();
    void useEngineStore.getState().selectSession(id);
  };
  return (
    <Panel
      title="By chat"
      action={
        summary.byChat.length > CHATS_SHOWN && (
          <button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setAll(!all)}>
            {all ? "Show fewer" : `Show ${summary.byChat.length}`}
          </button>
        )
      }
    >
      <div className={cn(CARD, "overflow-x-auto")}>
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-border/60">
              <th className={TH}>Chat</th>
              <th className={cn(TH, "text-right")}>Responses</th>
              <th className={cn(TH, "text-right")}>Tokens</th>
              <th className={cn(TH, "text-right")}>Per response</th>
              <th className={cn(TH, "text-right")}>Last used</th>
              <th className={cn(TH, "text-right")}>Spend</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const live = c.chatId ? sessions.some((s) => s.id === c.chatId) : false;
              const title = c.chatTitle ?? (c.chatId ? "Deleted chat" : "No chat");
              return (
                <tr key={c.chatId ?? "none"} className="border-b border-border/40 last:border-0">
                  <td className={cn(TD, "w-full max-w-0")}>
                    {live ? (
                      <button type="button" className="block max-w-full truncate text-left hover:underline" onClick={() => open(c.chatId!)}>
                        {title}
                      </button>
                    ) : (
                      <span className="block truncate text-muted-foreground">{title}</span>
                    )}
                  </td>
                  <td className={cn(TD, "text-right tabular-nums")}>{c.requests.toLocaleString()}</td>
                  <td className={cn(TD, "text-right tabular-nums")}>{formatTokens(tokensOf(c))}</td>
                  <td className={cn(TD, "text-right tabular-nums")}>{usd(c.requests ? c.costUsd / c.requests : 0)}</td>
                  <td className={cn(TD, "text-right whitespace-nowrap text-muted-foreground")}>{formatRelative(c.lastMs)}</td>
                  <td className={cn(TD, "text-right font-medium tabular-nums")}>{usd(c.costUsd)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function RecentTable({ recent, models }: { recent: UsageEvent[]; models: ModelDescriptor[] }) {
  if (!recent.length) return null;
  return (
    <Panel title="Latest responses">
      <div className={cn(CARD, "overflow-x-auto")}>
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-border/60">
              <th className={TH}>When</th>
              <th className={TH}>Chat</th>
              <th className={TH}>Model</th>
              <th className={cn(TH, "text-right")}>In</th>
              <th className={cn(TH, "text-right")}>Cached</th>
              <th className={cn(TH, "text-right")}>Out</th>
              <th className={cn(TH, "text-right")}>Time</th>
              <th className={cn(TH, "text-right")}>Cost</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((e) => (
              <tr key={e.id} className="border-b border-border/40 last:border-0">
                <td className={cn(TD, "whitespace-nowrap text-muted-foreground")} title={new Date(e.atMs).toLocaleString()}>
                  {formatRelative(e.atMs)}
                </td>
                <td className={cn(TD, "w-1/2 max-w-0")}>
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="truncate">{e.chatTitle ?? (e.chatId ? "Deleted chat" : "No chat")}</span>
                    {e.source !== "chat" && <Badge>{SOURCE_LABELS[e.source] ?? e.source}</Badge>}
                    {(e.stopReason === "error" || e.stopReason === "aborted") && <Badge>{e.stopReason}</Badge>}
                  </span>
                </td>
                <td className={cn(TD, "w-1/2 max-w-0 truncate text-muted-foreground")}>
                  {findModel(models, e.providerId, e.modelId)?.name ?? e.modelId}
                </td>
                <td className={cn(TD, "text-right tabular-nums")}>{formatTokens(e.input)}</td>
                <td className={cn(TD, "text-right tabular-nums text-muted-foreground")}>{formatTokens(e.cacheRead + e.cacheWrite)}</td>
                <td className={cn(TD, "text-right tabular-nums")}>{formatTokens(e.output)}</td>
                <td className={cn(TD, "text-right whitespace-nowrap tabular-nums text-muted-foreground")}>
                  {e.durationMs ? formatDuration(e.durationMs) : "—"}
                </td>
                <td className={cn(TD, "text-right font-medium tabular-nums")}>{usd(e.costUsd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function ClearHistory() {
  const clear = useUsageStore((s) => s.clear);
  const [armed, setArmed] = React.useState(false);
  React.useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), 4000);
    return () => window.clearTimeout(timer);
  }, [armed]);
  return (
    <div className="flex items-center gap-3 border-t border-border/60 pt-4 text-xs text-muted-foreground">
      <span className="flex-1">
        Kept on this computer in <code className="rounded-sm bg-muted px-1">evo.db</code>. Chats keep their own totals when the history is cleared.
      </span>
      <Button
        size="sm"
        variant="ghost"
        className={cn("gap-1.5", armed && "text-destructive")}
        onClick={() => (armed ? (setArmed(false), void clear()) : setArmed(true))}
      >
        <Trash2Icon className="size-3.5" />
        {armed ? "Click again to clear" : "Clear history"}
      </Button>
    </div>
  );
}
