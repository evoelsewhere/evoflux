import * as React from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// Pieces shared by the Customize sections: list rows, badges, a properties
// grid, empty notes and the list/detail split.

export function IconAction({ label, onClick, children }: { label: string; onClick(): void; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger render={<Button size="icon-sm" variant="ghost" aria-label={label} onClick={onClick} className="text-muted-foreground" />}>
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

export function Badge({ children, tone }: { children: React.ReactNode; tone?: "brand" }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-md px-1.5 text-[11px]",
        tone === "brand" ? "bg-brand/12 text-brand" : "bg-muted text-muted-foreground dark:bg-accent",
      )}
    >
      {children}
    </span>
  );
}

/** Label/value pairs in a quiet grid. */
export function Properties({ items }: { items: [string, React.ReactNode][] }) {
  const shown = items.filter(([, value]) => value !== null && value !== undefined && value !== "");
  if (!shown.length) return null;
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 text-[13px] @2xl:grid-cols-[max-content_1fr_max-content_1fr]">
      {shown.map(([label, value]) => (
        <React.Fragment key={label}>
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

export function ListRow({
  selected,
  onSelect,
  icon,
  title,
  meta,
  description,
  trailing,
  dimmed,
}: {
  selected: boolean;
  onSelect(): void;
  icon: React.ReactNode;
  title: string;
  meta?: React.ReactNode;
  description: string;
  trailing?: React.ReactNode;
  dimmed?: boolean;
}) {
  return (
    <div
      role="option"
      aria-selected={selected}
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && (event.preventDefault(), onSelect())}
      className={cn(
        "group flex cursor-default items-start gap-3 rounded-lg px-2.5 py-2 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-brand/40",
        selected ? "bg-brand/10" : "hover:bg-accent/60",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md [&_svg]:size-4",
          selected ? "bg-brand/15 text-brand" : "bg-muted text-muted-foreground dark:bg-accent",
        )}
      >
        {icon}
      </span>
      <span className={cn("flex min-w-0 flex-1 flex-col gap-0.5", dimmed && "opacity-50")}>
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-[13px] font-medium">{title}</span>
          {meta}
        </span>
        <span className="line-clamp-2 text-xs text-muted-foreground">{description || "No description"}</span>
      </span>
      {trailing && (
        <span className="shrink-0 pt-1" onClick={(event) => event.stopPropagation()}>
          {trailing}
        </span>
      )}
    </div>
  );
}

export function EmptyNote({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 px-3 py-8 text-center">
      <p className="text-[13px] font-medium">{title}</p>
      <div className="text-xs text-balance text-muted-foreground [&_code]:rounded-sm [&_code]:bg-muted [&_code]:px-1">{children}</div>
    </div>
  );
}

export function Split({
  list,
  detail,
  intro,
  footer,
}: {
  list: React.ReactNode;
  detail: React.ReactNode;
  intro?: string;
  /** Below the list, outside its scroll (settings for the whole section). */
  footer?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex w-80 max-w-[42%] shrink-0 flex-col border-r border-border/60">
        <div role="listbox" className="scrollbar-slim min-h-0 flex-1 overflow-y-auto px-2 pb-4">
          {intro && <p className="px-2.5 pt-3 text-xs text-muted-foreground">{intro}</p>}
          {list}
        </div>
        {footer && <div className="shrink-0 border-t border-border/60 p-2">{footer}</div>}
      </div>
      <div className="scrollbar-slim min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl px-6 py-5">{detail}</div>
      </div>
    </div>
  );
}

