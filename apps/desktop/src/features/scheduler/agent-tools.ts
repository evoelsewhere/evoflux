// Tools a chat's agent gets for scheduled tasks (external tools, answered
// here). Creating, changing and deleting a task ask the person first — a task
// keeps running prompts on its own — listing does not.

import { describeSchedule, formatWhen, scheduleFrom, scheduleProblem } from "@/lib/schedule";
import { useSchedulerStore, type ScheduledTask } from "@/stores/scheduler-store";

const SCHEDULE_SCHEMA = {
  type: "object",
  description:
    'When it runs. kind: "manual" (only on demand), "once" (at: ISO date-time), "hourly" (minute), "daily" / "weekdays" (time "HH:MM"), "weekly" (time, days: 0=Sun…6=Sat), or "cron" (expression, 5 fields). Local time.',
  properties: {
    kind: { type: "string", enum: ["manual", "once", "hourly", "daily", "weekdays", "weekly", "cron"] },
    at: { type: "string" },
    minute: { type: "number" },
    time: { type: "string" },
    days: { type: "array", items: { type: "number" } },
    expression: { type: "string" },
  },
  required: ["kind"],
};

export const SCHEDULER_TOOLS = [
  {
    name: "create_scheduled_task",
    description:
      "Schedule a prompt to run later or repeatedly, each time as a new chat in this folder (or another). Write the prompt so it stands on its own: the new chat has no memory of this one. The person approves it first.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Short name, e.g. Morning PR summary." },
        prompt: { type: "string", description: "What the scheduled chat should do, complete on its own." },
        schedule: SCHEDULE_SCHEMA,
        folder: { type: "string", description: "Folder the chat works in. Default: this chat's folder." },
      },
      required: ["name", "prompt", "schedule"],
      additionalProperties: false,
    },
  },
  {
    name: "list_scheduled_tasks",
    description: "List the scheduled tasks: id, name, schedule, next run, whether on, last runs.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "update_scheduled_task",
    description: "Change a scheduled task (name, prompt, schedule, folder) or switch it on or off. The person approves it first.",
    inputSchema: {
      type: "object",
      properties: {
        id: { type: "string" },
        name: { type: "string" },
        prompt: { type: "string" },
        schedule: SCHEDULE_SCHEMA,
        folder: { type: "string" },
        enabled: { type: "boolean" },
      },
      required: ["id"],
      additionalProperties: false,
    },
  },
  {
    name: "delete_scheduled_task",
    description: "Delete a scheduled task. The person approves it first.",
    inputSchema: { type: "object", properties: { id: { type: "string" } }, required: ["id"], additionalProperties: false },
  },
];

export const isSchedulerTool = (name: string) => SCHEDULER_TOOLS.some((t) => t.name === name);

type Ask = (title: string, description: string, options: string[]) => Promise<number>;
type Result = { text: string; structured?: Record<string, unknown>; isError?: boolean };

const summary = (t: ScheduledTask) => ({
  id: t.id,
  name: t.name,
  schedule: describeSchedule(t.schedule),
  enabled: t.enabled,
  nextRun: t.nextRunAt ? new Date(t.nextRunAt).toISOString() : null,
  folder: t.folder,
  prompt: t.prompt,
  lastRuns: t.runs.slice(0, 3).map((r) => ({ at: new Date(r.at).toISOString(), chatId: r.chatId, error: r.error })),
});

export async function runSchedulerTool(name: string, args: Record<string, any>, ctx: { cwd: string; ask: Ask }): Promise<Result> {
  const store = useSchedulerStore.getState();
  if (!store.loaded) await store.load();
  if (name === "list_scheduled_tasks") {
    const tasks = useSchedulerStore.getState().tasks.map(summary);
    return { text: tasks.length ? JSON.stringify(tasks, null, 2) : "No scheduled tasks.", structured: { tasks } };
  }
  if (name === "create_scheduled_task") {
    const schedule = scheduleFrom(args.schedule ?? {});
    const problem = scheduleProblem(schedule);
    if (problem) return { text: `Schedule: ${problem}`, isError: true };
    const taskName = String(args.name ?? "").trim();
    const prompt = String(args.prompt ?? "").trim();
    if (!taskName || !prompt) return { text: "create_scheduled_task needs a name and a prompt.", isError: true };
    const folder = String(args.folder ?? "").trim() || ctx.cwd || null;
    const answer = await ctx.ask(
      `Schedule “${taskName}”?`,
      `${describeSchedule(schedule)}${folder ? ` · in ${folder}` : ""}\n\n${prompt.length > 500 ? `${prompt.slice(0, 500)}…` : prompt}`,
      ["Schedule it", "Don't schedule"],
    );
    if (answer === -1) return { text: "Cancelled.", isError: true };
    if (answer !== 0) return { text: "The person declined to schedule this task.", isError: true };
    const task = await store.create({ name: taskName, prompt, folder, schedule }, "agent");
    return {
      text: `Scheduled “${task.name}” (${task.id}): ${describeSchedule(task.schedule)}${
        task.nextRunAt ? `, next ${formatWhen(task.nextRunAt)}` : ""
      }. It appears on the Scheduler page.`,
      structured: summary(task),
    };
  }
  const task = useSchedulerStore.getState().tasks.find((t) => t.id === String(args.id ?? ""));
  if (!task) return { text: `No scheduled task ${String(args.id ?? "")}; list_scheduled_tasks shows them.`, isError: true };
  if (name === "update_scheduled_task") {
    const schedule = args.schedule ? scheduleFrom(args.schedule) : undefined;
    const problem = schedule ? scheduleProblem(schedule) : null;
    if (problem) return { text: `Schedule: ${problem}`, isError: true };
    const changes = [
      args.name !== undefined && `name → ${args.name}`,
      args.prompt !== undefined && "new prompt",
      schedule && `schedule → ${describeSchedule(schedule)}`,
      args.folder !== undefined && `folder → ${args.folder}`,
      args.enabled !== undefined && (args.enabled ? "switch on" : "pause"),
    ].filter(Boolean);
    if (!changes.length) return { text: "Nothing to change.", isError: true };
    const answer = await ctx.ask(`Change “${task.name}”?`, changes.join("\n"), ["Change it", "Keep it as it is"]);
    if (answer !== 0) return { text: "The person kept the task as it was.", isError: true };
    const next = await store.update(task.id, {
      ...(args.name !== undefined ? { name: String(args.name) } : {}),
      ...(args.prompt !== undefined ? { prompt: String(args.prompt) } : {}),
      ...(schedule ? { schedule } : {}),
      ...(args.folder !== undefined ? { folder: String(args.folder) || null } : {}),
      ...(args.enabled !== undefined ? { enabled: Boolean(args.enabled) } : {}),
    });
    return { text: `Updated “${next?.name ?? task.name}”.`, structured: next ? summary(next) : undefined };
  }
  if (name === "delete_scheduled_task") {
    const answer = await ctx.ask(`Delete “${task.name}”?`, describeSchedule(task.schedule), ["Delete it", "Keep it"]);
    if (answer !== 0) return { text: "The person kept the task.", isError: true };
    await store.remove(task.id);
    return { text: `Deleted “${task.name}”.` };
  }
  return { text: `Unknown tool ${name}.`, isError: true };
}
