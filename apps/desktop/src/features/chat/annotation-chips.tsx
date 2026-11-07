// "Annotations: N" chips (docs/features/office-v3-parity/sdd.md, FR-10; port
// of the v3 InputBar and UserBubble chips): the batch waiting in the composer,
// with its list and per-item remove, and the annotations a sent message
// carried, in place of its machine block.

import * as React from "react";
import { ChevronDownIcon, MessageSquareTextIcon, XIcon } from "lucide-react";
import { describeAnnotation, type ParsedAnnotation } from "@/lib/document-annotations";
import { cn } from "@/lib/utils";
import { useAnnotationsStore, usePendingAnnotations } from "@/stores/annotations-store";

/** The chat's batch, above the message field. */
export function ComposerAnnotations({ chatId }: { chatId: string | null }) {
  const annotations = usePendingAnnotations(chatId);
  const [open, setOpen] = React.useState(false);
  React.useEffect(() => {
    if (annotations.length === 0) setOpen(false);
  }, [annotations.length]);
  if (!chatId || annotations.length === 0) return null;
  const store = useAnnotationsStore.getState();
  return (
    <div className="mx-2 mb-1.5 rounded-xl border border-brand/25 bg-brand/5 py-1 pr-1 pl-3" data-testid="composer-annotations">
      <div className="flex min-w-0 items-center gap-2">
        <MessageSquareTextIcon className="size-3.5 shrink-0 text-brand" aria-hidden />
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-1 text-left text-[11px] font-medium text-foreground/80 outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
        >
          Annotations: {annotations.length}
          <ChevronDownIcon className={cn("size-3 shrink-0 transition-transform", open && "rotate-180")} aria-hidden />
        </button>
        <button
          type="button"
          onClick={() => store.clear(chatId)}
          aria-label="Remove all annotations"
          title="Remove all annotations"
          className="grid size-6 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <XIcon className="size-3.5" aria-hidden />
        </button>
      </div>
      {open && (
        <ol className="mt-1 mb-1 flex flex-col gap-1 pr-1">
          {annotations.map((annotation, index) => (
            <li key={annotation.id} className="flex min-w-0 items-start gap-2 text-xs">
              <span className="mt-px grid size-4 shrink-0 place-items-center rounded-full bg-brand text-[10px] font-semibold text-brand-foreground">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[11px] text-muted-foreground">
                  {annotation.file} · {describeAnnotation(annotation)}
                </span>
                <span className="block break-words [overflow-wrap:anywhere]">
                  {annotation.instruction || "Quoted — no instruction"}
                </span>
              </span>
              <button
                type="button"
                onClick={() => store.remove(chatId, annotation.id)}
                aria-label={`Remove annotation ${index + 1}`}
                className="grid size-5 shrink-0 place-items-center rounded text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <XIcon className="size-3" aria-hidden />
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** What a sent message pointed at, under its bubble. */
export function SentAnnotations({ annotations }: { annotations: ParsedAnnotation[] }) {
  const [open, setOpen] = React.useState(false);
  if (annotations.length === 0) return null;
  return (
    <div className="flex max-w-full min-w-0 flex-col items-end">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        data-testid="annotations-chip"
        className="flex items-center gap-1.5 rounded-lg border border-brand/25 bg-brand/5 px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <MessageSquareTextIcon className="size-3.5 text-brand" aria-hidden />
        Annotations: {annotations.length}
        <ChevronDownIcon className={cn("size-3.5 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <ol className="mt-1 flex max-w-full flex-col gap-1.5 rounded-lg border border-border/70 bg-card p-2 text-xs" data-selectable>
          {annotations.map((annotation) => (
            <li key={annotation.n} className="min-w-0">
              <span className="block truncate text-[11px] text-muted-foreground">
                #{annotation.n} {annotation.file} · {describeAnnotation(annotation)}
              </span>
              <span className="block break-words [overflow-wrap:anywhere]">{annotation.instruction || "Quoted — no instruction"}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
