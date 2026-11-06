import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Widths of the reply lines, per placeholder turn (varied so it reads as text). */
const TURNS: { prompt: string; lines: string[] }[] = [
  { prompt: "w-2/5", lines: ["w-full", "w-11/12", "w-3/5"] },
  { prompt: "w-1/4", lines: ["w-10/12", "w-full", "w-9/12", "w-2/5"] },
  { prompt: "w-1/3", lines: ["w-full", "w-7/12"] },
];

/**
 * A chat being opened: the thread's shape (the person's bubble on the right,
 * reply lines on the left) until its messages arrive. It fades in after a beat
 * so a chat that opens at once does not flash it.
 */
export function ChatSkeleton() {
  return (
    <div
      role="status"
      aria-busy
      aria-label="Loading the chat"
      className="mx-auto flex h-full w-full max-w-(--chat-width) animate-in flex-col gap-8 overflow-hidden px-6 py-6 delay-150 duration-300 fill-mode-both fade-in"
    >
      {TURNS.map((turn, index) => (
        <div key={index} className="flex flex-col gap-6">
          <div className="flex justify-end">
            <Skeleton className={cn("h-10 rounded-2xl", turn.prompt)} />
          </div>
          <div className="flex flex-col gap-2.5">
            {turn.lines.map((width, line) => (
              <Skeleton key={line} className={cn("h-3.5 rounded-full", width)} />
            ))}
            <Skeleton className="mt-1.5 h-3 w-40 rounded-full opacity-60" />
          </div>
        </div>
      ))}
    </div>
  );
}
