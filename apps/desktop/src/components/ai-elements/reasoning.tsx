import { BrainIcon } from "lucide-react";
import {
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@/components/ui/trace";

// shadcn/ui AI Elements · Reasoning on Trace, with DeepSeek Harness's
// behaviour: always starts collapsed, shows a one-line preview of the thinking,
// reads "Thinking" (shimmering) while it streams and "Thought for Ns" after.

/** The line a reader sees: the latest finished paragraph while streaming, else the first. */
function preview(text: string, streaming: boolean): string {
  const paragraphs = text
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  const pick = streaming ? (paragraphs.length > 1 ? paragraphs.at(-2) : paragraphs.at(-1)) : paragraphs[0];
  const line = (pick ?? "").split("\n")[0].replace(/^[#*_>\-\s]+/, "");
  return line.length > 120 ? `${line.slice(0, 119)}…` : line;
}

export function seconds(ms: number): string {
  const s = Math.max(1, Math.round(ms / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

export function Reasoning({
  text,
  streaming,
  startedAt,
  endedAt,
}: {
  text: string;
  streaming: boolean;
  startedAt: number;
  endedAt?: number;
}) {
  const title = streaming ? "Thinking" : endedAt ? `Thought for ${seconds(endedAt - startedAt)}` : "Thought";
  const line = (
    <TraceLine status={streaming ? "running" : undefined}>
      <TraceIcon>
        <BrainIcon />
      </TraceIcon>
      <TraceTitle className="shrink-0">{title}</TraceTitle>
      {text && <TraceDescription className="min-w-0 shrink truncate text-muted-foreground/70">{preview(text, streaming)}</TraceDescription>}
    </TraceLine>
  );
  if (!text) return line;
  return (
    <TraceCollapsible>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent className="whitespace-pre-wrap" data-selectable>
        {text}
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}
