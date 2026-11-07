import { CornerDownLeftIcon, ImageIcon, PencilIcon, SendHorizontalIcon, XIcon } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useEngineStore } from "@/stores/engine-store";
import { cn } from "@/lib/utils";
import type { QueuedMessage } from "./transcript";
import { splitPrompt } from "./composer-input";
import { parseAnnotatedMessage } from "@/lib/document-annotations";

function RowButton({ label, onClick, children }: { label: string; onClick(): void; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            aria-label={label}
            onClick={onClick}
            className="grid size-6 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground [&_svg]:size-3.5"
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

/**
 * Messages sent while the agent works and not read yet, above the field.
 * "Send now" turns a queued one into a steer; "Edit" takes it back into the
 * field; the cross takes it back altogether.
 */
export function QueuedMessages({ onEdit }: { onEdit(text: string): void }) {
  const queued = useEngineStore((s) => s.transcript.queued);
  if (!queued?.length) return null;
  const { cancelQueued, queueMessage } = useEngineStore.getState();

  async function sendNow(item: QueuedMessage) {
    await cancelQueued(item.entryId);
    const images = (item.images ?? []).flatMap((url) => {
      const match = /^data:([^;]+);base64,(.*)$/.exec(url);
      return match ? [{ mimeType: match[1], data: match[2] }] : [];
    });
    await queueMessage(item.text, images, "steer").catch(() => onEdit(item.text));
  }

  return (
    <div className="mx-2 mb-1.5 flex flex-col gap-1" aria-label="Waiting messages">
      {queued.map((item) => {
        const { text, files, pasted } = splitPrompt(parseAnnotatedMessage(item.text)?.text ?? item.text);
        const extra = files.length + pasted.length;
        return (
          <div
            key={item.entryId}
            className="flex min-w-0 items-center gap-2 rounded-xl border border-border/70 bg-card/80 py-1 pr-1 pl-3 text-sm shadow-border-small"
          >
            <span
              className={cn(
                "shrink-0 text-[11px] font-medium",
                item.deliverAs === "steer" ? "text-brand" : "text-muted-foreground",
              )}
            >
              {item.deliverAs === "steer" ? "Next step" : "Queued"}
            </span>
            <span className="min-w-0 flex-1 truncate" title={item.text}>
              {text || (item.images?.length ? "Picture" : "Attachment")}
            </span>
            {item.images?.length ? (
              <span className="flex shrink-0 items-center gap-0.5 text-xs text-muted-foreground">
                <ImageIcon className="size-3.5" />
                {item.images.length}
              </span>
            ) : null}
            {extra > 0 && <span className="shrink-0 text-xs text-muted-foreground">+{extra}</span>}
            {item.deliverAs === "followUp" && (
              <RowButton label="Send now" onClick={() => void sendNow(item)}>
                <SendHorizontalIcon />
              </RowButton>
            )}
            <RowButton
              label="Edit"
              onClick={() => {
                void cancelQueued(item.entryId);
                onEdit(item.text);
              }}
            >
              <PencilIcon />
            </RowButton>
            <RowButton label="Remove" onClick={() => void cancelQueued(item.entryId)}>
              <XIcon />
            </RowButton>
          </div>
        );
      })}
      <p className="flex items-center gap-1 px-1 text-[11px] text-muted-foreground">
        <CornerDownLeftIcon className="size-3" />
        Read at the agent's next step · Queued ones after it finishes
      </p>
    </div>
  );
}
