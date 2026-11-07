// What the Usage page works out from the history and today's models.dev
// prices: per-model efficiency figures, the time series filled out to whole
// buckets, observations worth acting on, and what the same tokens would have
// cost on other models. Pure functions, no React.

import type { ModelCost, ModelDescriptor } from "@/engine/protocol";
import type { UsageBucket, UsageSummary, UsageTotals } from "@/lib/db";

export const HOUR_MS = 3_600_000;
export const DAY_MS = 24 * HOUR_MS;

/** Models the charts colour, in spend order; the rest fold into "Other". */
export const SERIES_SLOTS = 4;
export const OTHER = "__other__";
export const SERIES_COLORS = ["var(--viz-1)", "var(--viz-2)", "var(--viz-3)", "var(--viz-4)"];
export const OTHER_COLOR = "var(--viz-other)";

export function modelKey(providerId: string, modelId: string): string {
  return `${providerId}/${modelId}`;
}

export function findModel(models: ModelDescriptor[], providerId: string, modelId: string): ModelDescriptor | undefined {
  return models.find((m) => m.provider === providerId && m.id === modelId);
}

export function tokensOf(t: UsageTotals): number {
  return t.input + t.output + t.cacheRead + t.cacheWrite;
}

export function promptOf(t: UsageTotals): number {
  return t.input + t.cacheRead + t.cacheWrite;
}

/** Whether models.dev gives a non-zero price. */
export function hasPrice(cost: ModelCost | undefined): cost is ModelCost {
  return !!cost && (cost.input > 0 || cost.output > 0 || cost.cacheRead > 0 || cost.cacheWrite > 0);
}

/** What `t`'s tokens cost at `cost`'s base rates (long-context tiers aside). */
export function priceTokens(t: UsageTotals, cost: ModelCost): number {
  return (t.input * cost.input + t.output * cost.output + t.cacheRead * cost.cacheRead + t.cacheWrite * cost.cacheWrite) / 1e6;
}

// ── Efficiency ─────────────────────────────────────────────────────────────

export interface ModelEfficiency {
  key: string;
  providerId: string;
  modelId: string;
  name: string;
  color: string;
  totals: UsageSummary["byModel"][number];
  share: number;
  costPerResponse: number;
  /** USD per 1,000 output tokens: what a unit of produced text costs. */
  costPer1kOutput: number | null;
  /** USD per million tokens of every kind, as actually paid. */
  effectivePerM: number | null;
  avgPrompt: number;
  avgOutput: number;
  cacheHit: number | null;
  /** What cached reads saved at today's price, when the model has one. */
  cacheSaved: number | null;
  /** Output tokens per second over the whole response, when timed. */
  speed: number | null;
  avgLatencyMs: number | null;
  errorRate: number;
  price: ModelCost | undefined;
  priceConfigured: boolean;
}

export function seriesColors(summary: UsageSummary): Map<string, string> {
  const colors = new Map<string, string>();
  summary.byModel.slice(0, SERIES_SLOTS).forEach((m, i) => colors.set(modelKey(m.providerId, m.modelId), SERIES_COLORS[i]));
  return colors;
}

export function colorOf(colors: Map<string, string>, key: string): string {
  return colors.get(key) ?? OTHER_COLOR;
}

export function efficiency(summary: UsageSummary, models: ModelDescriptor[]): ModelEfficiency[] {
  const colors = seriesColors(summary);
  const total = summary.totals.costUsd;
  return summary.byModel.map((m) => {
    const key = modelKey(m.providerId, m.modelId);
    const descriptor = findModel(models, m.providerId, m.modelId);
    const prompt = promptOf(m);
    const tokens = tokensOf(m);
    const price = descriptor?.cost;
    return {
      key,
      providerId: m.providerId,
      modelId: m.modelId,
      name: descriptor?.name ?? m.modelId,
      color: colorOf(colors, key),
      totals: m,
      share: total > 0 ? m.costUsd / total : 0,
      costPerResponse: m.requests ? m.costUsd / m.requests : 0,
      costPer1kOutput: m.output > 0 ? (m.costUsd / m.output) * 1000 : null,
      effectivePerM: tokens > 0 ? (m.costUsd / tokens) * 1e6 : null,
      avgPrompt: m.requests ? prompt / m.requests : 0,
      avgOutput: m.requests ? m.output / m.requests : 0,
      cacheHit: prompt > 0 ? m.cacheRead / prompt : null,
      cacheSaved: hasPrice(price) && price.input > price.cacheRead ? (m.cacheRead * (price.input - price.cacheRead)) / 1e6 : null,
      speed: m.timed > 0 && m.timedMs > 0 ? m.timedOutput / (m.timedMs / 1000) : null,
      avgLatencyMs: m.timed > 0 ? m.timedMs / m.timed : null,
      errorRate: m.requests ? m.errors / m.requests : 0,
      price,
      priceConfigured: !!descriptor?.costConfigured,
    };
  });
}

// ── Time series ────────────────────────────────────────────────────────────

const pad = (n: number) => String(n).padStart(2, "0");

/** The bucket key of a local time, as SQLite's `localtime` writes it. */
export function bucketKey(at: number, bucket: UsageBucket): string {
  const d = new Date(at);
  if (bucket === "week") {
    const monday = new Date(d.getFullYear(), d.getMonth(), d.getDate() - ((d.getDay() + 6) % 7));
    return `${monday.getFullYear()}-${pad(monday.getMonth() + 1)}-${pad(monday.getDate())}`;
  }
  const day = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return bucket === "hour" ? `${day} ${pad(d.getHours())}` : day;
}

/** The local start time of a bucket key. */
export function bucketTime(key: string): number {
  const [date, hour] = key.split(" ");
  const [y, m, d] = date.split("-").map(Number);
  return new Date(y, m - 1, d, hour ? Number(hour) : 0).getTime();
}

function step(at: number, bucket: UsageBucket): number {
  const d = new Date(at);
  if (bucket === "hour") d.setHours(d.getHours() + 1);
  else d.setDate(d.getDate() + (bucket === "week" ? 7 : 1));
  return d.getTime();
}

export interface SeriesBucket {
  key: string;
  at: number;
  /** Per series (model key or OTHER), the bucket's totals. */
  parts: Map<string, UsageTotals>;
  total: UsageTotals;
}

const MAX_BUCKETS = 400;

function emptyTotals(): UsageTotals {
  return {
    requests: 0, input: 0, output: 0, cacheRead: 0, cacheWrite: 0, reasoning: 0,
    costInput: 0, costOutput: 0, costCacheRead: 0, costCacheWrite: 0, costUsd: 0,
    errors: 0, costErrors: 0, timed: 0, timedMs: 0, timedOutput: 0,
  };
}

function addInto(target: UsageTotals, add: UsageTotals) {
  for (const key of Object.keys(target) as (keyof UsageTotals)[]) target[key] += add[key];
}

/**
 * Every bucket from `start` to now, with each model's usage (models past the
 * colored ones folded into OTHER). Empty buckets are kept so gaps show.
 */
export function fillSeries(summary: UsageSummary, start: number, now = Date.now()): SeriesBucket[] {
  const bucket = summary.bucket;
  const colors = seriesColors(summary);
  const byKey = new Map<string, SeriesBucket>();
  const buckets: SeriesBucket[] = [];
  let at = bucketTime(bucketKey(start, bucket));
  const last = bucketKey(now, bucket);
  for (let i = 0; i < 2000; i++) {
    const key = bucketKey(at, bucket);
    const entry = { key, at, parts: new Map(), total: emptyTotals() };
    buckets.push(entry);
    byKey.set(key, entry);
    if (key >= last) break;
    at = step(at, bucket);
  }
  for (const point of summary.series) {
    const entry = byKey.get(point.bucket);
    if (!entry) continue;
    const key = modelKey(point.providerId, point.modelId);
    const series = colors.has(key) ? key : OTHER;
    const part = entry.parts.get(series) ?? emptyTotals();
    addInto(part, point);
    entry.parts.set(series, part);
    addInto(entry.total, point);
  }
  return buckets.slice(-MAX_BUCKETS);
}

// ── Observations ───────────────────────────────────────────────────────────

export interface Insight {
  tone: "info" | "warn" | "good";
  text: string;
}

const pct = (value: number) => `${Math.round(value * 100)}%`;

export function insights(
  summary: UsageSummary,
  rows: ModelEfficiency[],
  usd: (value: number) => string,
  tokens: (value: number) => string,
): Insight[] {
  const out: Insight[] = [];
  const t = summary.totals;
  if (t.requests === 0) return out;

  const promptCost = t.costInput + t.costCacheRead + t.costCacheWrite;
  if (t.costUsd > 0 && promptCost / t.costUsd >= 0.7) {
    out.push({
      tone: "info",
      text: `${pct(promptCost / t.costUsd)} of spend is the prompt, at about ${tokens(promptOf(t) / t.requests)} tokens per response. Every turn resends the chat so far: compacting long chats or starting fresh ones cuts this most.`,
    });
  }

  for (const row of rows) {
    if (!hasPrice(row.price) || row.cacheHit === null) continue;
    const prompt = promptOf(row.totals);
    const cheaper = row.price.cacheRead > 0 && row.price.cacheRead < row.price.input;
    if (cheaper && row.cacheHit < 0.5 && prompt >= 20_000) {
      const factor = row.price.input / row.price.cacheRead;
      out.push({
        tone: "warn",
        text: `Only ${pct(row.cacheHit)} of ${row.name}'s prompt tokens came from cache, though a cached token costs ${factor >= 2 ? `${Math.round(factor)}×` : "much"} less. Steady system prompts and fewer edits early in a chat keep the cache warm.`,
      });
    }
    if (row.cacheSaved && row.cacheSaved >= 0.01) {
      out.push({ tone: "good", text: `Cached reads saved about ${usd(row.cacheSaved)} on ${row.name} at today's price.` });
    }
  }

  const priced = rows.filter((r) => r.totals.costUsd > 0 && r.totals.requests >= 2);
  if (priced.length >= 2) {
    const byCost = [...priced].sort((a, b) => b.costPerResponse - a.costPerResponse);
    const [high, low] = [byCost[0], byCost.at(-1)!];
    const ratio = high.costPerResponse / low.costPerResponse;
    if (ratio >= 2) {
      out.push({
        tone: "info",
        text: `A response from ${high.name} costs ${ratio.toFixed(1)}× one from ${low.name} (${usd(high.costPerResponse)} vs ${usd(low.costPerResponse)}). Routine work — searches, small edits, subagents — may not need the dearer model.`,
      });
    }
  }

  const timed = rows.filter((r) => r.speed !== null && r.totals.timed >= 2);
  if (timed.length >= 2) {
    const bySpeed = [...timed].sort((a, b) => b.speed! - a.speed!);
    const [fast, slow] = [bySpeed[0], bySpeed.at(-1)!];
    if (fast.speed! / slow.speed! >= 1.5) {
      out.push({
        tone: "info",
        text: `${fast.name} writes ${Math.round(fast.speed!)} tokens/s, ${slow.name} ${Math.round(slow.speed!)} tokens/s (whole response, including reading the prompt).`,
      });
    }
  }

  if (t.errors > 0) {
    out.push({
      tone: "warn",
      text: `${t.errors} ${t.errors === 1 ? "response" : "responses"} failed or ${t.errors === 1 ? "was" : "were"} stopped${t.costErrors > 0 ? `, costing ${usd(t.costErrors)} (${pct(t.costErrors / Math.max(t.costUsd, 1e-9))} of spend)` : ""}.`,
    });
  }

  for (const row of rows) {
    if (!hasPrice(row.price) && !row.priceConfigured && tokensOf(row.totals) > 0 && row.totals.costUsd === 0) {
      out.push({
        tone: "warn",
        text: `${row.name} has no price on models.dev, so its ${row.totals.requests} responses count as $0 here.`,
      });
    }
  }

  const sub = summary.bySource.filter((s) => s.source !== "chat").reduce((sum, s) => sum + s.costUsd, 0);
  if (t.costUsd > 0 && sub / t.costUsd >= 0.3) {
    out.push({
      tone: "info",
      text: `${pct(sub / t.costUsd)} of spend came from subagents, plugin runs and side questions rather than the chats themselves.`,
    });
  }
  return out;
}

// ── Price check ────────────────────────────────────────────────────────────

export interface Alternative {
  descriptor: ModelDescriptor;
  cost: number;
  /** Compared with what was actually paid: negative is cheaper. */
  delta: number;
  current: boolean;
}

/**
 * What `row`'s tokens would cost on every priced model of the same provider
 * (and the other models in the history), cheapest first.
 */
export function alternatives(row: ModelEfficiency, models: ModelDescriptor[], used: Set<string>): Alternative[] {
  const seen = new Set<string>();
  const list: Alternative[] = [];
  for (const m of models) {
    const key = modelKey(m.provider, m.id);
    if (seen.has(key) || !hasPrice(m.cost)) continue;
    if (m.provider !== row.providerId && !used.has(key)) continue;
    seen.add(key);
    const cost = priceTokens(row.totals, m.cost);
    list.push({ descriptor: m, cost, delta: cost - row.totals.costUsd, current: key === row.key });
  }
  return list.sort((a, b) => a.cost - b.cost);
}
