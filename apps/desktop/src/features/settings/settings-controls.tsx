// Building blocks of a settings page: a section header, titled groups of
// rows split by hairlines, and the controls those rows use.

import * as React from "react";
import { Radio } from "@base-ui/react/radio";
import { RadioGroup } from "@base-ui/react/radio-group";
import { Slider } from "@base-ui/react/slider";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/** The page's heading: the section name, a line about it, and optional actions. */
export function SettingsHeader({
  title,
  description,
  children,
}: {
  /** Kept for the call sites; the settings list beside the page shows the icon. */
  icon?: LucideIcon;
  title: string;
  description: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <header className="flex items-start gap-4">
      <div className="min-w-0 flex-1">
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        <p className="mt-0.5 text-[13px] text-muted-foreground">{description}</p>
      </div>
      {children}
    </header>
  );
}

/** A titled group of rows, split by hairlines. */
export function SettingsGroup({
  title,
  description,
  children,
  id,
}: {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  id?: string;
}) {
  return (
    <section id={id} className="scroll-mt-6">
      <h2 className="text-[15px] font-semibold">{title}</h2>
      {description && <p className="mt-1 max-w-xl text-[13px] text-muted-foreground">{description}</p>}
      <div className="mt-1 divide-y">{children}</div>
    </section>
  );
}

/**
 * One setting: label and description on the left, a compact control (or a
 * value readout) on the right, and wide controls such as pickers below.
 */
export function SettingsRow({
  label,
  description,
  control,
  children,
  labelId,
}: {
  label: React.ReactNode;
  description?: React.ReactNode;
  control?: React.ReactNode;
  children?: React.ReactNode;
  labelId?: string;
}) {
  return (
    <div className="py-3.5">
      <div className="flex items-center justify-between gap-6">
        <div className="min-w-0 flex-1">
          <div id={labelId} className="text-sm">
            {label}
          </div>
          {description && <p className="mt-1 max-w-xl text-[13px] text-muted-foreground">{description}</p>}
        </div>
        {control && <div className="shrink-0">{control}</div>}
      </div>
      {children && <div className="mt-4">{children}</div>}
    </div>
  );
}

// ── Segmented control ────────────────────────────────────────────────────────

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  icon?: LucideIcon;
}

/** A row of mutually exclusive options; arrow keys move between them. */
export function Segmented<T extends string>({
  value,
  onValueChange,
  options,
  labelledBy,
  iconOnly,
}: {
  value: T;
  onValueChange(value: T): void;
  options: SegmentOption<T>[];
  labelledBy?: string;
  iconOnly?: boolean;
}) {
  return (
    <RadioGroup
      value={value}
      onValueChange={(next) => onValueChange(next as T)}
      aria-labelledby={labelledBy}
      className="inline-flex items-center gap-0.5 rounded-lg bg-muted p-0.5 shadow-hairline"
    >
      {options.map((option) => (
        <Radio.Root
          key={option.value}
          value={option.value}
          aria-label={iconOnly ? option.label : undefined}
          title={iconOnly ? option.label : undefined}
          className={cn(
            "inline-flex h-7 items-center justify-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium text-muted-foreground transition-colors outline-none",
            "hover:text-foreground data-checked:bg-background data-checked:text-foreground data-checked:shadow-border-small",
            "focus-visible:shadow-[0_0_0_2px_var(--background),0_0_0_4px_var(--ring)]",
            iconOnly && "w-8 px-0",
          )}
        >
          {option.icon && <option.icon className="size-3.5" />}
          {!iconOnly && option.label}
        </Radio.Root>
      ))}
    </RadioGroup>
  );
}

// ── Choice cards ─────────────────────────────────────────────────────────────

/** Larger radio options laid out in a grid, each with a preview. */
export function ChoiceCards<T extends string>({
  value,
  onValueChange,
  labelledBy,
  className,
  children,
}: {
  value: T;
  onValueChange(value: T): void;
  labelledBy?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <RadioGroup
      value={value}
      onValueChange={(next) => onValueChange(next as T)}
      aria-labelledby={labelledBy}
      className={cn("grid gap-2", className)}
    >
      {children}
    </RadioGroup>
  );
}

export function ChoiceCard({
  value,
  preview,
  title,
  description,
  previewStyle,
}: {
  value: string;
  preview: React.ReactNode;
  title: string;
  description: string;
  previewStyle?: React.CSSProperties;
}) {
  return (
    <Radio.Root
      value={value}
      className={cn(
        "group/choice flex items-center gap-3 rounded-lg bg-background p-2.5 text-left shadow-hairline transition-[box-shadow,background-color] outline-none",
        "hover:bg-accent/60 data-checked:bg-brand/5 data-checked:shadow-[0_0_0_1.5px_var(--brand)]",
        "focus-visible:shadow-[0_0_0_2px_var(--background),0_0_0_4px_var(--ring)]",
      )}
    >
      <span
        style={previewStyle}
        className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted text-sm font-semibold text-foreground group-data-checked/choice:bg-brand group-data-checked/choice:text-brand-foreground"
      >
        {preview}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium" style={previewStyle}>
          {title}
        </span>
        <span className="block truncate text-xs text-muted-foreground">{description}</span>
      </span>
    </Radio.Root>
  );
}

// ── Stepped slider ───────────────────────────────────────────────────────────

/**
 * A slider over a fixed list of stops, labelled under the track. Values that
 * are not a stop (zoomed with the keyboard, say) sit at the nearest one.
 */
export function StepSlider({
  stops,
  value,
  onValueChange,
  format,
  label,
  defaultValue,
}: {
  stops: number[];
  value: number;
  onValueChange(value: number): void;
  format(value: number): string;
  label: string;
  defaultValue?: number;
}) {
  const nearest = stops.reduce(
    (best, stop, index) => (Math.abs(stop - value) < Math.abs(stops[best] - value) ? index : best),
    0,
  );
  const last = stops.length - 1;

  return (
    <div>
      <Slider.Root
        value={nearest}
        min={0}
        max={last}
        step={1}
        onValueChange={(index) => onValueChange(stops[index as number])}
        aria-label={label}
        className="px-2"
      >
        <Slider.Control className="relative flex h-5 w-full touch-none items-center select-none">
          <Slider.Track className="relative h-1.5 w-full rounded-full bg-muted shadow-hairline">
            <Slider.Indicator className="h-full rounded-full bg-brand" />
            {stops.map((stop, index) => (
              <span
                key={stop}
                aria-hidden
                className={cn(
                  "absolute top-1/2 size-1 -translate-x-1/2 -translate-y-1/2 rounded-full",
                  index <= nearest ? "bg-brand-foreground/70" : "bg-muted-foreground/50",
                  (index === 0 || index === last) && "opacity-0",
                )}
                style={{ left: `${(index / last) * 100}%` }}
              />
            ))}
            <Slider.Thumb
              getAriaValueText={(_formatted, index) => format(stops[index] ?? value)}
              className="size-4 rounded-full bg-background shadow-[0_0_0_1px_var(--hairline),0_1px_3px_#0000002e] outline-none after:absolute after:inset-1 after:rounded-full after:bg-brand focus-visible:shadow-[0_0_0_2px_var(--background),0_0_0_4px_var(--ring)] data-dragging:scale-110"
            />
          </Slider.Track>
        </Slider.Control>
      </Slider.Root>
      <div className="relative mt-2 h-4 px-2 font-mono text-[11px] text-muted-foreground">
        {stops.map((stop, index) => (
          <button
            key={stop}
            type="button"
            tabIndex={-1}
            onClick={() => onValueChange(stop)}
            className={cn(
              "absolute -translate-x-1/2 transition-colors hover:text-foreground",
              index === nearest && "font-semibold text-foreground",
              index === 0 && "translate-x-0",
              index === last && "-translate-x-full",
            )}
            style={{ left: `calc(0.5rem + (100% - 1rem) * ${index / last})` }}
          >
            {format(stop)}
            {stop === defaultValue && index !== nearest && <span className="sr-only"> (default)</span>}
          </button>
        ))}
      </div>
    </div>
  );
}
