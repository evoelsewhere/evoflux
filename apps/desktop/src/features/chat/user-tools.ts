// Tools every chat's agent gets for reaching the person (external tools,
// answered here): `send_file` puts files in the chat as cards to open, and
// `notify` sends a notification when a long run needs them.

import { notify } from "@/features/notifications/notify";
import { resolvePath, statFile } from "@/features/files/fs";

export const USER_TOOLS = [
  {
    name: "send_file",
    description:
      "Give the person files you made or found — a report, an image, a build, an export — as cards in the chat they can open, show in their folder, or view in the app. Use it for deliverables, not for every file you touch.",
    inputSchema: {
      type: "object",
      properties: {
        paths: { type: "array", items: { type: "string" }, description: "Files, absolute or relative to the working folder (1–10)." },
        caption: { type: "string", description: "One line about them, e.g. \"The report, with the chart on page 2\"." },
      },
      required: ["paths"],
      additionalProperties: false,
    },
  },
  {
    name: "notify",
    description:
      "Send the person a notification (on their desktop when the app is in the background). Use it when a long run finishes or needs their decision while they may be away — not for every step.",
    inputSchema: {
      type: "object",
      properties: {
        title: { type: "string", description: "Short: what happened or what you need." },
        body: { type: "string", description: "One or two sentences." },
      },
      required: ["title"],
      additionalProperties: false,
    },
  },
];

export const isUserTool = (name: string) => USER_TOOLS.some((t) => t.name === name);

type Result = { text: string; structured?: Record<string, unknown>; isError?: boolean };

/** At most one `notify` per chat this often. */
const NOTIFY_EVERY_MS = 30_000;
const lastNotified = new Map<string, number>();

export async function runUserTool(name: string, args: Record<string, any>, ctx: { chat: string; cwd: string }): Promise<Result> {
  if (name === "send_file") {
    const paths: string[] = (Array.isArray(args.paths) ? args.paths : [args.paths]).filter((p: unknown) => typeof p === "string" && p.trim());
    if (!paths.length) return { text: "send_file needs at least one path.", isError: true };
    if (paths.length > 10) return { text: "Send at most 10 files at once.", isError: true };
    const files: { path: string; name: string; size: number }[] = [];
    const problems: string[] = [];
    for (const raw of paths) {
      const path = ctx.cwd ? resolvePath(ctx.cwd, raw) : raw;
      const stat = await statFile(path).catch(() => null);
      if (!stat?.exists) problems.push(`${raw}: not found`);
      else if (stat.dir) problems.push(`${raw}: a folder (send files)`);
      else files.push({ path, name: path.split(/[\\/]/).pop() ?? path, size: stat.size });
    }
    if (!files.length) return { text: problems.join("\n"), isError: true };
    return {
      text: `Sent ${files.length} file${files.length === 1 ? "" : "s"} to the chat: ${files.map((f) => f.name).join(", ")}.${
        problems.length ? `\nNot sent:\n${problems.join("\n")}` : ""
      }`,
      structured: { files, caption: typeof args.caption === "string" ? args.caption : undefined },
    };
  }
  if (name === "notify") {
    const title = String(args.title ?? "").trim().slice(0, 120);
    if (!title) return { text: "notify needs a title.", isError: true };
    const last = lastNotified.get(ctx.chat) ?? 0;
    if (Date.now() - last < NOTIFY_EVERY_MS) {
      return { text: "A notification went out moments ago; not sending another yet.", isError: true };
    }
    lastNotified.set(ctx.chat, Date.now());
    notify({
      title,
      body: typeof args.body === "string" ? args.body.slice(0, 400) : undefined,
      source: "agent",
      key: `agent:${ctx.chat}`,
      target: { type: "session", id: ctx.chat },
    });
    return { text: "Notified." };
  }
  return { text: `Unknown tool ${name}.`, isError: true };
}
