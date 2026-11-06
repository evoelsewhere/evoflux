// Scheduled tasks: a prompt run as a new chat in a folder, on a schedule
// (`lib/schedule.ts`). Saved in the app database (`scheduler.tasks`). The main
// window runs them: a check every 20 seconds starts the tasks that are due, and
// at launch a task missed while evo was closed runs once to catch up. Runs need
// evo running — the tray icon and Keep awake (Settings → General) let tasks
// carry on with the window closed or the computer idle.

import { create } from "zustand";
import { notify } from "@/features/notifications/notify";
import { db } from "@/lib/db";
import { describeSchedule, nextRun, type Schedule } from "@/lib/schedule";
import { useEngineStore } from "./engine-store";
import { useSessionStore } from "./session-store";

const KEY = "scheduler.tasks";
const CHECK_MS = 20_000;
const MAX_RUNS = 30;

export interface TaskRun {
  id: string;
  at: number;
  chatId: string | null;
  trigger: "schedule" | "manual" | "missed";
  error?: string;
}

export interface ScheduledTask {
  id: string;
  name: string;
  prompt: string;
  /** The folder the chat works in; `null`: this computer. */
  folder: string | null;
  schedule: Schedule;
  enabled: boolean;
  createdAt: number;
  updatedAt: number;
  /** Who made it: you, or an agent (with your approval). */
  createdBy: "you" | "agent";
  nextRunAt: number | null;
  runs: TaskRun[];
}

export type TaskInput = Pick<ScheduledTask, "name" | "prompt" | "folder" | "schedule"> & { enabled?: boolean };

interface SchedulerStore {
  tasks: ScheduledTask[];
  loaded: boolean;
  /** The task shown on the Scheduler page. */
  selectedId: string | null;
  select(id: string | null): void;
  load(): Promise<void>;
  create(input: TaskInput, createdBy?: ScheduledTask["createdBy"]): Promise<ScheduledTask>;
  update(id: string, patch: Partial<TaskInput>): Promise<ScheduledTask | null>;
  remove(id: string): Promise<void>;
  /** Start a run now; the new chat's id. */
  run(id: string, trigger?: TaskRun["trigger"]): Promise<string | null>;
}

const newId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;

const withNext = (task: ScheduledTask, after = Date.now()): ScheduledTask => ({
  ...task,
  nextRunAt: task.enabled ? nextRun(task.schedule, after) : null,
});

export const useSchedulerStore = create<SchedulerStore>()((set, get) => {
  const save = async (tasks: ScheduledTask[]) => {
    // Never write before the saved tasks were read: that would drop them.
    if (!get().loaded) throw new Error("Scheduled tasks are not loaded yet.");
    set({ tasks });
    await db.setSetting(KEY, tasks).catch((error) =>
      notify({ title: "Could not save scheduled tasks", body: String(error), level: "error", source: "scheduler" }),
    );
  };
  const replace = (task: ScheduledTask) => get().tasks.map((t) => (t.id === task.id ? task : t));

  return {
    tasks: [],
    loaded: false,
    selectedId: null,
    select: (selectedId) => set({ selectedId }),

    async load() {
      // A failed read leaves the store unloaded (and throws): saving after it
      // would replace the saved tasks with an empty list.
      const settings = await db.settings();
      const saved = Array.isArray(settings[KEY]) ? (settings[KEY] as ScheduledTask[]) : [];
      set({ tasks: saved, loaded: true });
    },

    async create(input, createdBy = "you") {
      const now = Date.now();
      const task = withNext({
        id: newId("task"),
        name: input.name.trim() || "Untitled task",
        prompt: input.prompt.trim(),
        folder: input.folder,
        schedule: input.schedule,
        enabled: input.enabled ?? true,
        createdAt: now,
        updatedAt: now,
        createdBy,
        nextRunAt: null,
        runs: [],
      });
      await save([...get().tasks, task]);
      return task;
    },

    async update(id, patch) {
      const current = get().tasks.find((t) => t.id === id);
      if (!current) return null;
      const task = withNext({
        ...current,
        ...patch,
        name: (patch.name ?? current.name).trim() || current.name,
        prompt: (patch.prompt ?? current.prompt).trim(),
        updatedAt: Date.now(),
      });
      await save(replace(task));
      return task;
    },

    async remove(id) {
      await save(get().tasks.filter((t) => t.id !== id));
      if (get().selectedId === id) set({ selectedId: null });
    },

    async run(id, trigger = "manual") {
      const task = get().tasks.find((t) => t.id === id);
      if (!task) return null;
      const record: TaskRun = { id: newId("run"), at: Date.now(), chatId: null, trigger };
      try {
        const workspace = task.folder ? await useSessionStore.getState().ensureWorkspace(task.folder) : null;
        record.chatId = await useEngineStore
          .getState()
          .startTaskChat({ workspaceId: workspace?.id ?? null, title: task.name, prompt: task.prompt });
        if (!record.chatId) record.error = "The chat could not be started.";
      } catch (error) {
        record.error = error instanceof Error ? error.message : String(error);
      }
      // A one-time task is done once it ran on schedule.
      const finished = task.schedule.kind === "once" && trigger !== "manual";
      const latest = get().tasks.find((t) => t.id === id) ?? task;
      await save(
        replace(
          withNext({
            ...latest,
            enabled: finished ? false : latest.enabled,
            runs: [record, ...latest.runs].slice(0, MAX_RUNS),
          }),
        ),
      );
      notify({
        title: record.error ? `“${task.name}” could not run` : `Running “${task.name}”`,
        body: record.error ?? (trigger === "missed" ? "Missed while evo was closed; running now." : describeSchedule(task.schedule)),
        level: record.error ? "error" : "info",
        source: "scheduler",
        key: `scheduler:${task.id}`,
        target: record.chatId ? { type: "session", id: record.chatId } : undefined,
      });
      return record.chatId;
    },
  };
});

/** Whether the task's last run is still working (so a new one waits). */
function lastRunBusy(task: ScheduledTask): boolean {
  const chatId = task.runs[0]?.chatId;
  if (!chatId) return false;
  const engine = useEngineStore.getState();
  return Boolean(engine.runtimes[chatId]?.transcript.busy || engine.busyElsewhere[chatId]);
}

let timer: ReturnType<typeof setInterval> | undefined;

/** Run due tasks from now on (main window only). */
export async function startScheduler() {
  if (timer) return;
  const store = useSchedulerStore.getState();
  try {
    await store.load();
  } catch {
    // The app database was not ready: try again shortly.
    setTimeout(() => void startScheduler(), 10_000);
    return;
  }
  const now = Date.now();
  // Missed while closed: run once to catch up, then go on from now.
  for (const task of useSchedulerStore.getState().tasks) {
    if (task.enabled && task.nextRunAt !== null && task.nextRunAt < now) void store.run(task.id, "missed");
  }
  timer = setInterval(() => {
    const at = Date.now();
    for (const task of useSchedulerStore.getState().tasks) {
      if (!task.enabled || task.nextRunAt === null || task.nextRunAt > at) continue;
      if (lastRunBusy(task)) {
        // Still working on the last run: skip this one.
        void useSchedulerStore.getState().update(task.id, {});
        continue;
      }
      void useSchedulerStore.getState().run(task.id, "schedule");
    }
  }, CHECK_MS);
}
