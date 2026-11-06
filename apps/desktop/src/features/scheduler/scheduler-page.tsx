import * as React from "react";
import {
  CalendarClockIcon,
  CircleAlertIcon,
  FolderIcon,
  MessageSquareIcon,
  PlayIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DateTimeField, MinuteField, TimeField } from "./time-fields";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { StatusDot } from "@/components/status-dot";
import { baseName, formatRelative } from "@/lib/format";
import { describeSchedule, formatWhen, nextRun, scheduleProblem, type Schedule } from "@/lib/schedule";
import { cn } from "@/lib/utils";
import { useEngineStore } from "@/stores/engine-store";
import { useSchedulerStore, type ScheduledTask, type TaskInput } from "@/stores/scheduler-store";
import { useSessionStore } from "@/stores/session-store";
import { useUiStore } from "@/stores/ui-store";
import { Badge, EmptyNote, ListRow, Split } from "@/features/customize/customize-parts";

// Scheduler (sidebar → Scheduler): prompts that run as new chats on a
// schedule (`stores/scheduler-store.ts`). A list of tasks on the left, the
// chosen one on the right — its prompt, folder, schedule and past runs.

const KINDS: { id: Schedule["kind"]; label: string }[] = [
  { id: "manual", label: "Manual" },
  { id: "once", label: "Once" },
  { id: "hourly", label: "Hourly" },
  { id: "daily", label: "Daily" },
  { id: "weekdays", label: "Weekdays" },
  { id: "weekly", label: "Weekly" },
  { id: "cron", label: "Custom" },
];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const EXAMPLES: TaskInput[] = [
  {
    name: "Morning briefing",
    prompt: "Summarise what changed in this repository since yesterday: new commits, open pull requests and failing checks. Keep it short and list anything that needs my attention first.",
    folder: null,
    schedule: { kind: "weekdays", time: "09:00" },
  },
  {
    name: "Dependency check",
    prompt: "Check this project's dependencies for available updates and known vulnerabilities. List what is worth updating and why; do not change any files.",
    folder: null,
    schedule: { kind: "weekly", time: "10:00", days: [1] },
  },
  {
    name: "End-of-day notes",
    prompt: "Look at today's changes in this repository and write short notes on what was done and what is left, as a markdown list.",
    folder: null,
    schedule: { kind: "weekdays", time: "17:30" },
  },
];

/** Default schedule fields when switching kinds. */
function scheduleOf(kind: Schedule["kind"], from: Schedule): Schedule {
  const time = "time" in from ? from.time : "09:00";
  switch (kind) {
    case "manual":
      return { kind };
    case "once": {
      const at = new Date(Date.now() + 3600_000);
      at.setMinutes(0, 0, 0);
      return { kind, at: at.getTime() };
    }
    case "hourly":
      return { kind, minute: 0 };
    case "daily":
    case "weekdays":
      return { kind, time };
    case "weekly":
      return { kind, time, days: [1] };
    case "cron":
      return { kind, expression: "0 9 * * 1-5" };
  }
}

const input = "h-8 rounded-md border border-border bg-background px-2 text-[13px] outline-none focus-visible:border-brand";

function ScheduleEditor({ value, onChange }: { value: Schedule; onChange(next: Schedule): void }) {
  const problem = scheduleProblem(value);
  const next = problem ? null : nextRun(value);
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap gap-1">
        {KINDS.map((kind) => (
          <button
            key={kind.id}
            type="button"
            onClick={() => kind.id !== value.kind && onChange(scheduleOf(kind.id, value))}
            className={cn(
              "h-7 rounded-md px-2.5 text-xs transition-colors",
              value.kind === kind.id ? "bg-brand/15 text-brand" : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            {kind.label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        {value.kind === "once" && (
          <DateTimeField value={value.at} onChange={(at) => onChange({ ...value, at })} />
        )}
        {value.kind === "hourly" && (
          <label className="flex items-center gap-2">
            At minute
            <MinuteField value={value.minute} onChange={(minute) => onChange({ ...value, minute })} />
          </label>
        )}
        {(value.kind === "daily" || value.kind === "weekdays" || value.kind === "weekly") && (
          <label className="flex items-center gap-2">
            At
            <TimeField value={value.time} onChange={(time) => onChange({ ...value, time })} />
          </label>
        )}
        {value.kind === "weekly" && (
          <div className="flex gap-1">
            {DAYS.map((day, index) => {
              const on = value.days.includes(index);
              return (
                <button
                  key={day}
                  type="button"
                  aria-pressed={on}
                  onClick={() =>
                    onChange({ ...value, days: on ? value.days.filter((d) => d !== index) : [...value.days, index] })
                  }
                  className={cn(
                    "h-7 w-10 rounded-md text-xs transition-colors",
                    on ? "bg-brand text-brand-foreground" : "bg-muted text-muted-foreground hover:bg-accent dark:bg-accent/50",
                  )}
                >
                  {day}
                </button>
              );
            })}
          </div>
        )}
        {value.kind === "cron" && (
          <input
            value={value.expression}
            onChange={(e) => onChange({ ...value, expression: e.target.value })}
            placeholder="minute hour day month weekday"
            aria-label="Cron expression"
            className={cn(input, "w-56 font-mono")}
          />
        )}
      </div>
      <p className={cn("text-xs", problem ? "text-destructive" : "text-muted-foreground")}>
        {problem
          ? problem
          : value.kind === "manual"
            ? "Runs only when you press Run now."
            : next
              ? `${describeSchedule(value)} · next ${formatWhen(next)}`
              : "That time has passed."}
      </p>
    </div>
  );
}

function FolderPicker({ value, onChange }: { value: string | null; onChange(next: string | null): void }) {
  const workspaces = useSessionStore((s) => s.workspaces);
  const choose = async () => {
    const picked = await openDialog({ directory: true, multiple: false }).catch(() => null);
    if (typeof picked === "string") onChange(picked);
  };
  const known = value === null || workspaces.some((w) => w.path === value);
  const items = [
    { value: "", label: "This computer (home folder)" },
    ...workspaces.map((w) => ({ value: w.path, label: `${baseName(w.path)} — ${w.path}` })),
    ...(!known && value ? [{ value, label: value }] : []),
    { value: "__choose", label: "Choose a folder…" },
  ];
  return (
    <div className="flex items-center gap-2">
      <Select
        value={value ?? ""}
        items={items}
        onValueChange={(v) => (v === "__choose" ? void choose() : onChange(v || null))}
      >
        <SelectTrigger aria-label="Folder" className="min-w-0 max-w-full flex-1">
          <SelectValue />
        </SelectTrigger>
        <SelectContent alignItemWithTrigger={false} align="start">
          {items.map((i) => (
            <SelectItem key={i.value} value={i.value}>
              {i.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function Runs({ task }: { task: ScheduledTask }) {
  const sessions = useSessionStore((s) => s.sessions);
  const archived = useSessionStore((s) => s.archived);
  const runtimes = useEngineStore((s) => s.runtimes);
  const busyElsewhere = useEngineStore((s) => s.busyElsewhere);
  if (!task.runs.length) return <p className="text-xs text-muted-foreground">No runs yet.</p>;
  return (
    <ul className="flex flex-col">
      {task.runs.map((run) => {
        const chat = run.chatId ? (sessions.find((s) => s.id === run.chatId) ?? archived.find((s) => s.id === run.chatId)) : undefined;
        const running = run.chatId ? Boolean(runtimes[run.chatId]?.transcript.busy || busyElsewhere[run.chatId]) : false;
        return (
          <li key={run.id}>
            <button
              type="button"
              disabled={!chat}
              onClick={() => chat && void useEngineStore.getState().selectSession(chat.id)}
              className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors enabled:hover:bg-accent/60"
            >
              {run.error ? (
                <StatusDot tone="error" />
              ) : running ? (
                <Spinner className="size-3.5 text-muted-foreground" />
              ) : (
                <StatusDot tone={chat?.unread ? "info" : "ok"} />
              )}
              <span className="w-36 shrink-0 tabular-nums">{formatWhen(run.at)}</span>
              <span className="min-w-0 flex-1 truncate text-muted-foreground">
                {run.error ?? chat?.preview ?? (chat ? chat.title : "Chat removed")}
              </span>
              {run.trigger !== "schedule" && <Badge>{run.trigger === "manual" ? "Run now" : "Caught up"}</Badge>}
              {chat && <MessageSquareIcon className="size-3.5 shrink-0 text-muted-foreground" />}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function TaskEditor({ task, initial, onDone }: { task: ScheduledTask | null; initial: TaskInput; onDone(id: string | null): void }) {
  const store = useSchedulerStore();
  const [draft, setDraft] = React.useState<TaskInput>(initial);
  const [busy, setBusy] = React.useState(false);
  const [confirmDelete, setConfirmDelete] = React.useState(false);
  const dirty = !task || JSON.stringify({ ...initial }) !== JSON.stringify({ ...draft });
  const problem = scheduleProblem(draft.schedule);
  const valid = draft.name.trim() && draft.prompt.trim() && !problem;

  const save = async () => {
    if (!valid) return;
    setBusy(true);
    const saved = task ? await store.update(task.id, draft) : await store.create(draft);
    setBusy(false);
    onDone(saved?.id ?? null);
  };

  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand/12 text-brand">
          <CalendarClockIcon className="size-5" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <input
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            placeholder="Task name"
            aria-label="Task name"
            className="-mx-1 rounded-md bg-transparent px-1 text-base font-semibold outline-none hover:bg-accent/40 focus-visible:bg-accent/40"
          />
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {task ? (
              <>
                <Badge tone={task.enabled ? "brand" : undefined}>{task.enabled ? "On" : "Paused"}</Badge>
                {task.createdBy === "agent" && <Badge>Made by an agent</Badge>}
                {task.nextRunAt && <span>Next {formatWhen(task.nextRunAt)}</span>}
                {task.runs[0] && <span>· last {formatRelative(task.runs[0].at)}</span>}
              </>
            ) : (
              <span>New task</span>
            )}
          </div>
        </div>
        {task && (
          <div className="flex shrink-0 items-center gap-1.5">
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5"
              onClick={() => void store.run(task.id, "manual").then((chat) => chat && void useEngineStore.getState().selectSession(chat))}
            >
              <PlayIcon className="size-3.5" /> Run now
            </Button>
            <Switch
              aria-label="Task on"
              checked={task.enabled}
              onCheckedChange={(on) => void store.update(task.id, { enabled: on })}
            />
          </div>
        )}
      </header>

      <section className="flex flex-col gap-1.5">
        <h3 className="text-xs font-medium text-muted-foreground">Prompt</h3>
        <textarea
          value={draft.prompt}
          onChange={(e) => setDraft({ ...draft, prompt: e.target.value })}
          placeholder="What the chat should do each time. It starts fresh, so say everything it needs."
          aria-label="Prompt"
          className="field-sizing-content min-h-32 resize-none rounded-xl border border-border bg-background px-3 py-2.5 text-[13px] leading-6 outline-none focus-visible:border-brand"
        />
      </section>

      <section className="flex flex-col gap-1.5">
        <h3 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <FolderIcon className="size-3.5" /> Works in
        </h3>
        <FolderPicker value={draft.folder} onChange={(folder) => setDraft({ ...draft, folder })} />
      </section>

      <section className="flex flex-col gap-1.5">
        <h3 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <CalendarClockIcon className="size-3.5" /> Runs
        </h3>
        <ScheduleEditor value={draft.schedule} onChange={(schedule) => setDraft({ ...draft, schedule })} />
      </section>

      <div className="flex items-center gap-2 border-t border-border/60 pt-4">
        {task &&
          (confirmDelete ? (
            <>
              <span className="text-xs text-muted-foreground">Delete this task? Its past chats stay.</span>
              <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>
                Keep
              </Button>
              <Button size="sm" variant="destructive" onClick={() => void store.remove(task.id).then(() => onDone(null))}>
                Delete
              </Button>
            </>
          ) : (
            <Button size="sm" variant="ghost" className="gap-1.5 text-muted-foreground" onClick={() => setConfirmDelete(true)}>
              <Trash2Icon className="size-3.5" /> Delete
            </Button>
          ))}
        <span className="flex-1" />
        {dirty && task && (
          <Button size="sm" variant="ghost" onClick={() => setDraft(initial)}>
            Revert
          </Button>
        )}
        {!task && (
          <Button size="sm" variant="ghost" onClick={() => onDone(null)}>
            Cancel
          </Button>
        )}
        <Button size="sm" disabled={!dirty || !valid || busy} onClick={() => void save()} className="gap-1.5">
          {busy && <Spinner className="size-3.5" />}
          {task ? "Save" : "Create task"}
        </Button>
      </div>

      {task && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-xs font-medium text-muted-foreground">Past runs</h3>
          <Runs task={task} />
        </section>
      )}
    </div>
  );
}

function Intro({ onExample }: { onExample(example: TaskInput): void }) {
  return (
    <div className="flex flex-col gap-4 py-6">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold">Run prompts on a schedule</h2>
        <p className="text-[13px] text-muted-foreground">
          Each run starts a new chat in the folder you pick, with your prompt, and shows up in the sidebar like any other
          chat. Tasks run while evo is open — with the tray icon on, closing the window keeps them going. Agents can
          schedule tasks too, after you approve.
        </p>
      </div>
      <div className="grid gap-2 @2xl:grid-cols-3">
        {EXAMPLES.map((example) => (
          <button
            key={example.name}
            type="button"
            onClick={() => onExample(example)}
            className="flex flex-col gap-1 rounded-xl bg-muted/60 px-3 py-2.5 text-left transition-colors hover:bg-accent dark:bg-accent/40"
          >
            <span className="text-[13px] font-medium">{example.name}</span>
            <span className="text-xs text-brand">{describeSchedule(example.schedule)}</span>
            <span className="line-clamp-3 text-xs text-muted-foreground">{example.prompt}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function SchedulerPage() {
  const { tasks, loaded, selectedId, select, load } = useSchedulerStore();
  const [creating, setCreating] = React.useState<TaskInput | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const cwd = useEngineStore((s) => s.cwd);

  React.useEffect(() => {
    if (!loaded) void load().catch((error) => setLoadError(String(error)));
  }, [loaded, load]);

  const current = creating ? null : (tasks.find((t) => t.id === selectedId) ?? tasks[0] ?? null);
  const startNew = (from?: TaskInput) =>
    setCreating(
      from ? { ...from, folder: from.folder ?? cwd ?? null } : { name: "", prompt: "", folder: cwd ?? null, schedule: { kind: "daily", time: "09:00" } },
    );
  const sorted = [...tasks].sort(
    (a, b) => Number(b.enabled) - Number(a.enabled) || (a.nextRunAt ?? Infinity) - (b.nextRunAt ?? Infinity),
  );

  return (
    <div className="@container flex h-full min-h-0 flex-col bg-background min-[900px]:rounded-tl-xl">
      <header className="flex shrink-0 items-center gap-3 border-b border-border/60 px-4 py-2.5">
        <CalendarClockIcon className="size-4 text-brand" />
        <h1 className="text-sm font-semibold">Scheduler</h1>
        <span className="text-xs text-muted-foreground">
          {tasks.filter((t) => t.enabled).length} on · {tasks.length} in all
        </span>
        <span className="flex-1" />
        <Button size="sm" className="gap-1.5" onClick={() => startNew()}>
          <PlusIcon className="size-3.5" /> New task
        </Button>
        <Button size="sm" variant="ghost" onClick={() => useUiStore.getState().closeCustomize()}>
          Close
        </Button>
      </header>
      {!loaded ? (
        <div className="flex flex-1 items-center justify-center">
          {loadError ? (
            <p className="max-w-sm text-center text-[13px] text-muted-foreground">Could not read scheduled tasks: {loadError}</p>
          ) : (
            <Spinner className="size-4 text-muted-foreground" />
          )}
        </div>
      ) : (
        <Split
          list={
            sorted.length === 0 ? (
              <EmptyNote title="No scheduled tasks">Create one, or pick an example on the right.</EmptyNote>
            ) : (
              <div className="flex flex-col gap-0.5 pt-2">
                {sorted.map((task) => {
                  const failed = Boolean(task.runs[0]?.error);
                  return (
                    <ListRow
                      key={task.id}
                      selected={!creating && current?.id === task.id}
                      onSelect={() => {
                        setCreating(null);
                        select(task.id);
                      }}
                      icon={failed ? <CircleAlertIcon className="text-destructive" /> : <CalendarClockIcon />}
                      title={task.name}
                      meta={!task.enabled ? <span className="shrink-0 text-[11px] text-muted-foreground">Paused</span> : null}
                      description={`${describeSchedule(task.schedule)}${
                        task.enabled && task.nextRunAt ? ` · next ${formatWhen(task.nextRunAt)}` : ""
                      }`}
                      dimmed={!task.enabled}
                      trailing={
                        <Switch
                          aria-label={`${task.name} on`}
                          checked={task.enabled}
                          onCheckedChange={(on) => void useSchedulerStore.getState().update(task.id, { enabled: on })}
                        />
                      }
                    />
                  );
                })}
              </div>
            )
          }
          detail={
            creating ? (
              <TaskEditor
                key="new"
                task={null}
                initial={creating}
                onDone={(id) => {
                  setCreating(null);
                  if (id) select(id);
                }}
              />
            ) : current ? (
              <TaskEditor
                key={`${current.id}:${current.updatedAt}`}
                task={current}
                initial={{ name: current.name, prompt: current.prompt, folder: current.folder, schedule: current.schedule }}
                onDone={(id) => select(id)}
              />
            ) : (
              <Intro onExample={(example) => startNew(example)} />
            )
          }
        />
      )}
    </div>
  );
}
