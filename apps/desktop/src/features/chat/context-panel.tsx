import * as React from "react";
import { ChevronRightIcon, LoaderCircleIcon } from "lucide-react";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { ContextBreakdown, ContextCategory } from "@/engine/protocol";
import { formatRelative, formatTokens } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";

/** One colour per category; the request's fixed parts in the accent hues, the rest grey. */
const SWATCH: Record<string, string> = {
  messages: "bg-status-info",
  system_tools: "bg-status-warn",
  plugin_tools: "bg-status-ok",
  system_prompt: "bg-muted-foreground",
  context_files: "bg-muted-foreground/80",
  skills: "bg-muted-foreground/60",
  autocompact_buffer: "bg-muted-foreground/35",
  free: "bg-muted",
};

const swatch = (id: string) => SWATCH[id] ?? "bg-muted-foreground/50";
const percent = (value: number) => `${value.toFixed(1)}%`;
const basename = (path: string) => path.split(/[\\/]/).filter(Boolean).pop() ?? path;

/** The window as one bar, segment widths proportional to each category. */
function SegmentBar({ breakdown }: { breakdown: ContextBreakdown }) {
  const shown = breakdown.categories.filter((c) => c.id !== "free" && c.tokens > 0);
  return (
    <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
      {shown.map((category) => (
        <div
          key={category.id}
          className={cn("h-full", swatch(category.id))}
          style={{ width: `${Math.max(category.percent, category.tokens > 0 ? 0.6 : 0)}%` }}
        />
      ))}
    </div>
  );
}

function CategoryRow({ category }: { category: ContextCategory }) {
  return (
    <div className="flex items-center gap-2.5 py-1 text-[13px]">
      <span className={cn("size-2.5 shrink-0 rounded-[3px]", swatch(category.id))} />
      <span className="flex-1 truncate">{category.label}</span>
      <span className="w-16 text-right font-mono text-xs text-muted-foreground tabular-nums">
        {formatTokens(category.tokens)}
      </span>
      <span className="w-12 text-right font-mono text-xs text-muted-foreground tabular-nums">
        {percent(category.percent)}
      </span>
    </div>
  );
}

/** An expandable list of what a category holds (tools, skills, files). */
function ItemList({ label, items }: { label: string; items: { name: string; tokens: number; hint?: string }[] }) {
  if (items.length === 0) return null;
  return (
    <Collapsible>
      <CollapsibleTrigger className="group flex w-full items-center gap-2 py-1 text-left text-[13px] text-foreground/90 hover:text-foreground">
        <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground transition-transform group-data-[panel-open]:rotate-90" />
        <span className="flex-1">{label}</span>
        <span className="font-mono text-xs text-muted-foreground tabular-nums">{items.length}</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="h-(--collapsible-panel-height) overflow-hidden transition-[height] duration-200 data-ending-style:h-0 data-starting-style:h-0">
        <ul className="ml-5 max-h-40 overflow-y-auto border-l py-1 pl-3">
          {items.map((item) => (
            <li key={item.name} className="flex items-center gap-2 py-0.5 text-xs" title={item.hint ?? item.name}>
              <span className="min-w-0 flex-1 truncate font-mono">{item.name}</span>
              <span className="font-mono text-muted-foreground tabular-nums">{formatTokens(item.tokens)}</span>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

function Breakdown({ breakdown }: { breakdown: ContextBreakdown }) {
  const compact = useEngineStore((s) => s.compact);
  const busy = useEngineStore((s) => s.transcript.busy);
  const updatedAt = useEngineStore((s) => s.contextBreakdownAt);
  const [compacting, setCompacting] = React.useState(false);
  const usedPercent = breakdown.window ? (breakdown.total / breakdown.window) * 100 : 0;
  const builtin = breakdown.tools.filter((t) => t.source === "builtin");
  const plugin = breakdown.tools.filter((t) => t.source === "plugin");

  return (
    <div className="flex flex-col">
      <div className="flex flex-col gap-2 p-3">
        <p className="text-sm font-semibold">Context</p>
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-sm font-medium">{Math.round(usedPercent)}% used</span>
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {formatTokens(breakdown.total)} / {formatTokens(breakdown.window)}
          </span>
        </div>
        <SegmentBar breakdown={breakdown} />
      </div>

      <div className="border-t px-3 py-2">
        {breakdown.categories.map((category) => (
          <CategoryRow key={category.id} category={category} />
        ))}
      </div>

      <div className="border-t px-3 py-2">
        <ItemList label="System tools" items={builtin} />
        <ItemList label="Plugin tools" items={plugin} />
        <ItemList label="Skills" items={breakdown.skills} />
        <ItemList
          label="Context files"
          items={breakdown.contextFiles.map((f) => ({ name: basename(f.path), tokens: f.tokens, hint: f.path }))}
        />
      </div>

      <div className="flex items-center justify-between gap-3 border-t px-3 py-2.5 text-[13px]">
        <span className="text-muted-foreground">
          {breakdown.compactionEnabled && breakdown.untilCompact !== null
            ? `${formatTokens(breakdown.untilCompact)} until auto-compact`
            : "Auto-compact is off"}
        </span>
        <Button
          size="sm"
          variant="secondary"
          disabled={busy || compacting}
          onClick={() => {
            setCompacting(true);
            void compact().finally(() => setCompacting(false));
          }}
        >
          {compacting && <LoaderCircleIcon className="animate-spin" />}
          Compact session
        </Button>
      </div>

      <p className="border-t px-3 py-2 text-xs text-muted-foreground">
        {breakdown.estimated ? "Estimated until the model reports usage. " : ""}
        {updatedAt ? `Last updated ${formatRelative(updatedAt)}.` : ""} Refreshes when each turn ends.
      </p>
    </div>
  );
}

/**
 * The context window (shadcn/ui AI Elements · Context): a Hover Card on a
 * small button, opening onto what fills the window, category by category.
 * It opens on hover like the pattern, and on click so Compact is reachable.
 */
export function ContextPanel({ className }: { className?: string }) {
  const breakdown = useEngineStore((s) => s.contextBreakdown);
  const fallback = useEngineStore((s) => s.state.context);
  const load = useEngineStore((s) => s.loadContextBreakdown);
  const [open, setOpen] = React.useState(false);
  const used = breakdown?.total ?? fallback?.tokens ?? 0;
  const window = breakdown?.window ?? fallback?.window ?? 0;
  React.useEffect(() => {
    if (open) void load();
  }, [open, load]);
  if (!window) return null;
  const percentUsed = Math.round((used / window) * 100);

  return (
    <HoverCard open={open} onOpenChange={setOpen}>
      <HoverCardTrigger
        delay={10}
        closeDelay={100}
        onClick={() => setOpen((value) => !value)}
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            className={cn("size-8", className)}
            aria-label={`${percentUsed}% of context used`}
          />
        }
      >
        <UsageRing percent={percentUsed} />
      </HoverCardTrigger>
      <HoverCardContent align="end" className="w-80 p-0">
        {breakdown ? (
          <Breakdown breakdown={breakdown} />
        ) : (
          <p className="flex items-center gap-2 p-3 text-xs text-muted-foreground">
            <LoaderCircleIcon className="size-3.5 animate-spin" /> Measuring the context window…
          </p>
        )}
      </HoverCardContent>
    </HoverCard>
  );
}

/** A small ring showing how full the window is. */
function UsageRing({ percent }: { percent: number }) {
  const radius = 6;
  const circumference = 2 * Math.PI * radius;
  return (
    <svg viewBox="0 0 16 16" className="size-4 -rotate-90" aria-hidden>
      <circle cx="8" cy="8" r={radius} fill="none" stroke="currentColor" strokeOpacity={0.2} strokeWidth="2" />
      <circle
        cx="8"
        cy="8"
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - Math.min(percent, 100) / 100)}
      />
    </svg>
  );
}
