import { cn } from "@/lib/utils";

const tones = {
  ok: "bg-status-ok",
  warn: "bg-status-warn",
  error: "bg-status-error",
  info: "bg-status-info",
  idle: "bg-muted-foreground/50",
} as const;

/** Status colour lives only in dots (DESIGN.md §2). */
export function StatusDot({
  tone,
  pulse = false,
  className,
  label,
}: {
  tone: keyof typeof tones;
  pulse?: boolean;
  className?: string;
  label?: string;
}) {
  return (
    <span
      role={label ? "status" : undefined}
      aria-label={label}
      className={cn("relative inline-flex size-2 shrink-0 rounded-full", tones[tone], className)}
    >
      {pulse && <span className={cn("absolute inset-0 animate-ping rounded-full opacity-60", tones[tone])} />}
    </span>
  );
}
