import * as React from "react";
import { CheckIcon, ChevronDownIcon, ListChecksIcon } from "lucide-react";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";

// The agent's task list (`update_todos`), pinned above the chat input: the
// latest list of the latest turn that has one. Collapsed it shows progress
// and the task in progress; open, every task with its state.

export interface Todo {
  content: string;
  status: "pending" | "in_progress" | "completed";
  active_form?: string;
}

/** The newest task list in the chat, and whether its turn is still running. */
export function useLatestTodos(): { todos: Todo[]; live: boolean } | null {
  const turns = useEngineStore((s) => s.transcript.turns);
  return React.useMemo(() => {
    for (let t = turns.length - 1; t >= 0; t--) {
      const parts = turns[t].parts;
      for (let p = parts.length - 1; p >= 0; p--) {
        const part = parts[p];
        if (part.kind !== "tool" || part.name !== "update_todos") continue;
        const todos = (part.details?.todos ?? (part.args as any)?.todos) as Todo[] | undefined;
        if (!Array.isArray(todos)) continue;
        // Only the last turn's list stays pinned.
        if (t !== turns.length - 1) return null;
        return { todos, live: turns[t].status === "running" };
      }
    }
    return null;
  }, [turns]);
}

export function TodoIcon({ status, live }: { status: Todo["status"]; live: boolean }) {
  if (status === "completed")
    return (
      <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-brand text-brand-foreground">
        <CheckIcon className="size-3" />
      </span>
    );
  if (status === "in_progress")
    return live ? (
      <Spinner className="size-4 shrink-0 text-brand" />
    ) : (
      <span className="size-4 shrink-0 rounded-full border-2 border-brand" />
    );
  return <span className="size-4 shrink-0 rounded-full border border-muted-foreground/50" />;
}

export function TodoList({ todos, live }: { todos: Todo[]; live: boolean }) {
  return (
    <ul className="flex flex-col gap-1">
      {todos.map((todo, i) => (
        <li key={i} className="flex items-start gap-2 text-[13px] leading-5">
          <TodoIcon status={todo.status} live={live} />
          <span
            className={cn(
              todo.status === "completed" && "text-muted-foreground line-through decoration-muted-foreground/50",
              todo.status === "in_progress" && "font-medium",
            )}
          >
            {todo.status === "in_progress" && live && todo.active_form ? todo.active_form : todo.content}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function TodoBar() {
  const latest = useLatestTodos();
  const [open, setOpen] = React.useState(true);
  if (!latest || latest.todos.length === 0) return null;
  const { todos, live } = latest;
  const done = todos.filter((t) => t.status === "completed").length;
  const current = todos.find((t) => t.status === "in_progress");
  const allDone = done === todos.length;
  return (
    <div className="mb-2 rounded-xl border border-border bg-background/95 px-3 py-2 shadow-xs">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 text-left text-xs"
      >
        <ListChecksIcon className={cn("size-4 shrink-0", allDone ? "text-muted-foreground" : "text-brand")} />
        <span className="font-medium">Tasks</span>
        <span className="text-muted-foreground tabular-nums">
          {done}/{todos.length}
        </span>
        {!open && current && (
          <span className="min-w-0 flex-1 truncate text-muted-foreground">· {live && current.active_form ? current.active_form : current.content}</span>
        )}
        <span className="flex-1" />
        <span className="h-1 w-16 overflow-hidden rounded-full bg-muted">
          <span className="block h-full rounded-full bg-brand transition-all" style={{ width: `${(done / todos.length) * 100}%` }} />
        </span>
        <ChevronDownIcon className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", !open && "-rotate-90")} />
      </button>
      {open && (
        <div className="scrollbar-slim mt-2 max-h-48 overflow-y-auto pl-0.5">
          <TodoList todos={todos} live={live} />
        </div>
      )}
    </div>
  );
}
