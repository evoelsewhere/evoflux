// Usage and cost history (sidebar → Usage). Every model response a chat's
// engine makes is a row in `evo.db` (`usage_events`, written by the engine:
// crates/evo-engine/src/usage_log.rs); this store reads totals, the time
// series by model, breakdowns and the latest responses through the shell's
// `usage_summary` / `usage_events` commands. Prices come from models.dev:
// each response's cost was computed from its model's price when it ran, and
// the page compares it with today's prices from the engine's model list.
// Design: docs/features/usage-and-cost/sdd.md.

import { create } from "zustand";
import { db, type UsageBucket, type UsageEvent, type UsageQuery, type UsageSummary } from "@/lib/db";

export type UsageRange = "today" | "7d" | "30d" | "90d" | "all";
export type BucketChoice = "auto" | UsageBucket;

export const USAGE_RANGES: { id: UsageRange; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "7d", label: "7 days" },
  { id: "30d", label: "30 days" },
  { id: "90d", label: "90 days" },
  { id: "all", label: "All time" },
];

export const BUCKETS: { id: BucketChoice; label: string }[] = [
  { id: "auto", label: "Auto" },
  { id: "hour", label: "Hourly" },
  { id: "day", label: "Daily" },
  { id: "week", label: "Weekly" },
];

const RANGE_DAYS: Record<Exclude<UsageRange, "all">, number> = { today: 1, "7d": 7, "30d": 30, "90d": 90 };
const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;

/** Local midnight `days - 1` days ago: the first day a range covers. */
export function rangeStart(range: UsageRange, now = new Date()): number | undefined {
  if (range === "all") return undefined;
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  start.setDate(start.getDate() - (RANGE_DAYS[range] - 1));
  return start.getTime();
}

/**
 * The bucket "Auto" picks: hours while the range (or the history inside it)
 * spans under three days, weeks past four months, days otherwise.
 */
export function autoBucket(range: UsageRange, firstMs: number | null, now = Date.now()): UsageBucket {
  const start = Math.max(rangeStart(range) ?? firstMs ?? now, firstMs ?? now);
  const span = now - start;
  if (span < 3 * DAY_MS) return "hour";
  if (span > 120 * DAY_MS) return "week";
  return "day";
}

/** A model the page narrows to. */
export interface ModelFilter {
  providerId: string;
  modelId: string;
}

const RECENT = 50;

interface UsageStore {
  range: UsageRange;
  bucket: BucketChoice;
  model: ModelFilter | null;
  summary: UsageSummary | null;
  recent: UsageEvent[];
  loading: boolean;
  error: string | null;
  setRange(range: UsageRange): void;
  setBucket(bucket: BucketChoice): void;
  setModel(model: ModelFilter | null): void;
  /** Read the history again for the current range, bucket and filter. */
  load(): Promise<void>;
  /** Forget the whole history. */
  clear(): Promise<void>;
}

let ticket = 0;

export const useUsageStore = create<UsageStore>()((set, get) => ({
  range: "30d",
  bucket: "auto",
  model: null,
  summary: null,
  recent: [],
  loading: false,
  error: null,
  setRange: (range) => {
    set({ range });
    void get().load();
  },
  setBucket: (bucket) => {
    set({ bucket });
    void get().load();
  },
  setModel: (model) => {
    set({ model });
    void get().load();
  },
  async load() {
    const mine = ++ticket;
    const { range, bucket, model, summary } = get();
    const resolved = bucket === "auto" ? autoBucket(range, summary?.firstMs ?? null) : bucket;
    const query: UsageQuery = {
      fromMs: rangeStart(range),
      providerId: model?.providerId,
      modelId: model?.modelId,
      bucket: resolved,
    };
    set({ loading: true });
    try {
      let [next, recent] = await Promise.all([db.usageSummary(query), db.usageEvents(query, undefined, RECENT)]);
      // The first load learns when the history starts; "Auto" may then want another bucket.
      const settled = bucket === "auto" ? autoBucket(range, next.firstMs) : resolved;
      if (settled !== next.bucket) next = await db.usageSummary({ ...query, bucket: settled });
      // Only the latest request's answer shows; an older one finishing late is dropped.
      if (mine === ticket) set({ summary: next, recent, loading: false, error: null });
    } catch (error) {
      if (mine === ticket) set({ loading: false, error: String(error) });
    }
  },
  async clear() {
    await db.clearUsage();
    await get().load();
  },
}));
