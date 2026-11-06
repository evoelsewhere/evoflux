import * as React from "react";
import type { UsageBucket, UsageTotals } from "@/lib/db";
import { cn } from "@/lib/utils";
import { OTHER_COLOR, tokensOf, type ModelEfficiency, type SeriesBucket } from "./analysis";

// Charts for the Usage page, drawn with plain elements in the app's tokens:
// a stacked bar chart over time (one colour per model, fixed order, the rest
// as "Other") and horizontal bars comparing models. Hover shows exact values.

export type Metric = "cost" | "tokens" | "requests";

export function metricValue(t: UsageTotals, metric: Metric): number {
  return metric === "cost" ? t.costUsd : metric === "tokens" ? tokensOf(t) : t.requests;
}

/** 0.0137 → 0.02, 7 → 10, 1234 → 1500: a round top for the axis. */
function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const exp = 10 ** Math.floor(Math.log10(value));
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (value <= m * exp) return m * exp;
  return 10 * exp;
}

function bucketLabel(at: number, bucket: UsageBucket, long = false): string {
  const d = new Date(at);
  const day = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  if (bucket === "hour") {
    const hour = `${String(d.getHours()).padStart(2, "0")}:00`;
    return long || d.getHours() === 0 ? `${day} ${hour}` : hour;
  }
  return bucket === "week" ? (long ? `Week of ${day}` : day) : day;
}

export interface SeriesInfo {
  key: string;
  name: string;
  color: string;
}

export function Legend({ series }: { series: SeriesInfo[] }) {
  if (series.length < 2) return null;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {series.map((s) => (
        <span key={s.key} className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-[3px]" style={{ background: s.color }} />
          {s.name}
        </span>
      ))}
    </div>
  );
}

export function TimeChart({
  buckets,
  bucket,
  metric,
  series,
  format,
}: {
  buckets: SeriesBucket[];
  bucket: UsageBucket;
  metric: Metric;
  series: SeriesInfo[];
  format: (value: number) => string;
}) {
  const [hover, setHover] = React.useState<number | null>(null);
  const max = niceCeil(Math.max(0, ...buckets.map((b) => metricValue(b.total, metric))));
  const n = buckets.length;
  const dense = n > 60;
  const labels = React.useMemo(() => {
    const count = Math.min(n, 6);
    const picks = new Set<number>();
    for (let k = 0; k < count; k++) picks.add(Math.round((k * (n - 1)) / Math.max(1, count - 1)));
    return picks;
  }, [n]);
  const shown = hover === null ? null : buckets[hover];
  const order = [...series.map((s) => s.key)];

  return (
    <div className="flex flex-col gap-2">
      <div className="relative h-56 pl-12" onMouseLeave={() => setHover(null)}>
        {[1, 0.5, 0].map((f) => (
          <div
            key={f}
            className={cn("pointer-events-none absolute right-0 left-12 border-t", f === 0 ? "border-border" : "border-dashed border-border/70")}
            style={{ bottom: `${f * 100}%` }}
          >
            <span className="absolute -top-2 -left-12 w-10 text-right text-[10px] text-muted-foreground tabular-nums">{format(max * f)}</span>
          </div>
        ))}
        <div
          className={cn("absolute inset-y-0 right-0 left-12 flex items-end", dense ? "gap-px" : "gap-[2px]")}
          role="img"
          aria-label={`${metric} per ${bucket}, ${n} buckets, highest ${format(Math.max(0, ...buckets.map((b) => metricValue(b.total, metric))))}`}
        >
          {buckets.map((b, i) => {
            const total = metricValue(b.total, metric);
            return (
              <div
                key={b.key}
                onMouseEnter={() => setHover(i)}
                className={cn("relative flex h-full min-w-0 flex-1 flex-col justify-end", hover === i && "bg-foreground/[0.04]")}
              >
                {total > 0 && (
                  <div
                    className="flex w-full flex-col-reverse gap-px overflow-hidden rounded-t-[3px]"
                    style={{ height: `max(${(total / max) * 100}%, 2px)` }}
                  >
                    {order.map((key) => {
                      const part = b.parts.get(key);
                      const value = part ? metricValue(part, metric) : 0;
                      if (value <= 0) return null;
                      const color = series.find((s) => s.key === key)?.color ?? OTHER_COLOR;
                      // Grow by share: grow factors summing under 1 would leave the bar part empty.
                      return <div key={key} style={{ flexGrow: (value / total) * 1000, flexBasis: 0, minHeight: 1, background: color }} />;
                    })}
                  </div>
                )}
              </div>
            );
          })}
          {shown && hover !== null && (
            <div
              className="pointer-events-none absolute top-0 z-10 w-56 rounded-lg bg-popover p-2.5 text-xs text-popover-foreground shadow-[0_0_0_1px_var(--border),0_8px_24px_rgb(0_0_0/0.18)]"
              style={hover < n / 2 ? { left: `calc(${((hover + 1) / n) * 100}% + 8px)` } : { right: `calc(${((n - hover) / n) * 100}% + 8px)` }}
            >
              <div className="mb-1.5 flex items-baseline gap-2">
                <span className="font-medium">{bucketLabel(shown.at, bucket, true)}</span>
                <span className="flex-1" />
                <span className="font-medium tabular-nums">{format(metricValue(shown.total, metric))}</span>
              </div>
              {order.map((key) => {
                const part = shown.parts.get(key);
                if (!part || metricValue(part, metric) <= 0) return null;
                const info = series.find((s) => s.key === key);
                return (
                  <div key={key} className="flex items-center gap-1.5 py-0.5">
                    <span className="size-2 shrink-0 rounded-[2px]" style={{ background: info?.color ?? OTHER_COLOR }} />
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">{info?.name ?? "Other"}</span>
                    <span className="tabular-nums">{format(metricValue(part, metric))}</span>
                  </div>
                );
              })}
              <div className="mt-1.5 border-t border-border/60 pt-1.5 text-muted-foreground">
                {shown.total.requests.toLocaleString()} {shown.total.requests === 1 ? "response" : "responses"}
                {shown.total.errors > 0 && ` · ${shown.total.errors} failed`}
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="relative ml-12 h-3 text-[10px] text-muted-foreground">
        {buckets.map((b, i) =>
          labels.has(i) ? (
            <span
              key={b.key}
              className="absolute whitespace-nowrap"
              style={
                i === 0
                  ? { left: 0 }
                  : i === n - 1
                    ? { right: 0 }
                    : { left: `${((i + 0.5) / n) * 100}%`, transform: "translateX(-50%)" }
              }
            >
              {bucketLabel(b.at, bucket)}
            </span>
          ) : null,
        )}
      </div>
    </div>
  );
}

/** One horizontal bar per model, in the model's colour, longest wins. */
export function ModelBars({
  title,
  note,
  rows,
  value,
  format,
  better,
}: {
  title: string;
  note?: string;
  rows: ModelEfficiency[];
  value: (row: ModelEfficiency) => number | null;
  format: (value: number) => string;
  /** Which end is better, to mark the best model. */
  better: "low" | "high";
}) {
  const values = rows.map((r) => ({ row: r, v: value(r) })).filter((x): x is { row: ModelEfficiency; v: number } => x.v !== null && x.v > 0);
  const max = Math.max(0, ...values.map((x) => x.v));
  const best =
    values.length >= 2 ? values.reduce((a, b) => ((better === "low" ? b.v < a.v : b.v > a.v) ? b : a)).row.key : null;
  return (
    <div className="flex min-w-0 flex-col gap-2.5 rounded-xl p-3.5 shadow-[0_0_0_1px_var(--border)]">
      <div className="flex flex-col">
        <span className="text-[13px] font-medium">{title}</span>
        {note && <span className="text-xs text-muted-foreground">{note}</span>}
      </div>
      {values.length === 0 ? (
        <span className="py-2 text-xs text-muted-foreground">Not enough data yet.</span>
      ) : (
        values.map(({ row, v }) => (
          <div key={row.key} className="flex flex-col gap-1" title={`${row.name}: ${format(v)}`}>
            <div className="flex items-baseline gap-2 text-xs">
              <span className="min-w-0 flex-1 truncate">{row.name}</span>
              {best === row.key && <span className="text-[10px] text-muted-foreground">{better === "low" ? "lowest" : "highest"}</span>}
              <span className="font-medium tabular-nums">{format(v)}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted dark:bg-accent">
              <div className="h-full rounded-full" style={{ width: `${(v / max) * 100}%`, background: row.color }} />
            </div>
          </div>
        ))
      )}
    </div>
  );
}
