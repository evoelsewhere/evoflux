import * as React from "react";
import { CalendarIcon, ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

const pad = (n: number) => String(n).padStart(2, "0");
const range = (count: number) => Array.from({ length: count }, (_, i) => ({ value: pad(i), label: pad(i) }));
const HOURS = range(24);
const MINUTES = range(60);
const WEEKDAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function NumberSelect({ label, value, items, onChange }: { label: string; value: string; items: { value: string; label: string }[]; onChange(next: string): void }) {
  return (
    <Select value={value} items={items} onValueChange={(v) => v && onChange(v)}>
      <SelectTrigger size="sm" aria-label={label} className="font-mono tabular-nums">
        <SelectValue />
      </SelectTrigger>
      <SelectContent alignItemWithTrigger={false} align="start" className="max-h-64">
        {items.map((i) => (
          <SelectItem key={i.value} value={i.value}>
            {i.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Minute of the hour, 0–59. */
export function MinuteField({ value, onChange }: { value: number; onChange(next: number): void }) {
  return <NumberSelect label="Minute" value={pad(value)} items={MINUTES} onChange={(v) => onChange(Number(v))} />;
}

/** 24-hour `HH:MM`. */
export function TimeField({ value, onChange }: { value: string; onChange(next: string): void }) {
  const [h = "09", m = "00"] = value.split(":");
  return (
    <span className="flex items-center gap-1">
      <NumberSelect label="Hour" value={pad(Number(h) || 0)} items={HOURS} onChange={(v) => onChange(`${v}:${pad(Number(m) || 0)}`)} />
      <span className="text-muted-foreground">:</span>
      <NumberSelect label="Minute" value={pad(Number(m) || 0)} items={MINUTES} onChange={(v) => onChange(`${pad(Number(h) || 0)}:${v}`)} />
    </span>
  );
}

function Calendar({ selected, onPick }: { selected: Date; onPick(day: Date): void }) {
  const [month, setMonth] = React.useState(() => new Date(selected.getFullYear(), selected.getMonth(), 1));
  const first = month.getDay();
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const today = new Date();
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  const step = (by: number) => setMonth(new Date(month.getFullYear(), month.getMonth() + by, 1));
  const nav = "grid size-6 place-items-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground";
  return (
    <div className="flex w-56 flex-col gap-2 text-xs">
      <div className="flex items-center justify-between">
        <button type="button" aria-label="Previous month" className={nav} onClick={() => step(-1)}>
          <ChevronLeftIcon className="size-4" />
        </button>
        <span className="font-medium">{month.toLocaleDateString(undefined, { month: "long", year: "numeric" })}</span>
        <button type="button" aria-label="Next month" className={nav} onClick={() => step(1)}>
          <ChevronRightIcon className="size-4" />
        </button>
      </div>
      <div className="grid grid-cols-7 gap-0.5 text-center">
        {WEEKDAYS.map((d) => (
          <span key={d} className="py-1 text-[11px] text-muted-foreground">
            {d}
          </span>
        ))}
        {Array.from({ length: first }, (_, i) => (
          <span key={`b${i}`} />
        ))}
        {Array.from({ length: days }, (_, i) => {
          const day = new Date(month.getFullYear(), month.getMonth(), i + 1);
          const on = same(day, selected);
          return (
            <button
              key={i}
              type="button"
              aria-pressed={on}
              onClick={() => onPick(day)}
              className={cn(
                "h-7 rounded-md tabular-nums transition-colors",
                on ? "bg-brand text-brand-foreground" : "hover:bg-accent",
                !on && same(day, today) && "font-semibold text-brand",
              )}
            >
              {i + 1}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** A date and a 24-hour time, as epoch milliseconds. */
export function DateTimeField({ value, onChange }: { value: number; onChange(next: number): void }) {
  const date = new Date(Number.isFinite(value) ? value : Date.now());
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const setTime = (next: string) => {
    const [h, m] = next.split(":").map(Number);
    const d = new Date(date);
    d.setHours(h, m, 0, 0);
    onChange(d.getTime());
  };
  const setDay = (day: Date) => {
    const d = new Date(date);
    d.setFullYear(day.getFullYear(), day.getMonth(), day.getDate());
    onChange(d.getTime());
  };
  return (
    <span className="flex items-center gap-2">
      <Popover>
        <PopoverTrigger
          aria-label="Date"
          className="inline-flex h-7 items-center gap-2 rounded-lg bg-input/50 px-2.5 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
        >
          <CalendarIcon className="size-3.5 text-muted-foreground" />
          {date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
        </PopoverTrigger>
        <PopoverContent align="start" className="w-auto p-3">
          <Calendar selected={date} onPick={setDay} />
        </PopoverContent>
      </Popover>
      <TimeField value={time} onChange={setTime} />
    </span>
  );
}
