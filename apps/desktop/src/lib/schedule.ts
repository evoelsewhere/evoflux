// When a scheduled task runs: the schedule kinds the Scheduler offers, the
// next run after a moment (local time), and a plain description. Every
// repeating kind is a five-field cron expression underneath
// (minute hour day-of-month month day-of-week; `*`, lists, ranges and `/step`;
// Sunday is 0 or 7).

export type Schedule =
  | { kind: "manual" }
  | { kind: "once"; at: number }
  | { kind: "hourly"; minute: number }
  | { kind: "daily"; time: string }
  | { kind: "weekdays"; time: string }
  | { kind: "weekly"; time: string; days: number[] }
  | { kind: "cron"; expression: string };

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const hm = (time: string) => {
  const [h, m] = time.split(":").map((x) => Number.parseInt(x, 10));
  return { h: Number.isFinite(h) ? Math.min(23, Math.max(0, h)) : 9, m: Number.isFinite(m) ? Math.min(59, Math.max(0, m)) : 0 };
};

/** The cron expression of a repeating schedule. */
export function cronOf(schedule: Schedule): string | null {
  switch (schedule.kind) {
    case "hourly":
      return `${schedule.minute} * * * *`;
    case "daily": {
      const { h, m } = hm(schedule.time);
      return `${m} ${h} * * *`;
    }
    case "weekdays": {
      const { h, m } = hm(schedule.time);
      return `${m} ${h} * * 1-5`;
    }
    case "weekly": {
      const { h, m } = hm(schedule.time);
      const days = [...new Set(schedule.days)].sort().join(",") || "1";
      return `${m} ${h} * * ${days}`;
    }
    case "cron":
      return schedule.expression.trim();
    default:
      return null;
  }
}

function field(text: string, min: number, max: number): Set<number> {
  const out = new Set<number>();
  for (const part of text.split(",")) {
    const [range, stepText] = part.split("/");
    const step = stepText === undefined ? 1 : Number.parseInt(stepText, 10);
    if (!Number.isFinite(step) || step < 1) throw new Error(`bad step in "${part}"`);
    let lo: number;
    let hi: number;
    if (range === "*") [lo, hi] = [min, max];
    else if (range.includes("-")) {
      const [a, b] = range.split("-").map((x) => Number.parseInt(x, 10));
      [lo, hi] = [a, b];
    } else {
      lo = Number.parseInt(range, 10);
      hi = stepText === undefined ? lo : max;
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || lo < min || hi > max || lo > hi) {
      throw new Error(`"${part}" is outside ${min}–${max}`);
    }
    for (let v = lo; v <= hi; v += step) out.add(v);
  }
  return out;
}

interface Cron {
  minutes: Set<number>;
  hours: Set<number>;
  days: Set<number>;
  months: Set<number>;
  weekdays: Set<number>;
  anyDay: boolean;
  anyWeekday: boolean;
}

export function parseCron(expression: string): Cron {
  const parts = expression.trim().split(/\s+/);
  if (parts.length !== 5) throw new Error("use five fields: minute hour day month weekday");
  const weekdays = field(parts[4], 0, 7);
  if (weekdays.has(7)) weekdays.add(0);
  return {
    minutes: field(parts[0], 0, 59),
    hours: field(parts[1], 0, 23),
    days: field(parts[2], 1, 31),
    months: field(parts[3], 1, 12),
    weekdays,
    anyDay: parts[2] === "*",
    anyWeekday: parts[4] === "*",
  };
}

/** The first minute after `after` that `cron` matches (local time), within about a year. */
function nextCron(cron: Cron, after: number): number | null {
  const t = new Date(after);
  t.setSeconds(0, 0);
  t.setMinutes(t.getMinutes() + 1);
  const limit = after + 400 * 24 * 3600 * 1000;
  while (t.getTime() < limit) {
    if (!cron.months.has(t.getMonth() + 1)) {
      t.setMonth(t.getMonth() + 1, 1);
      t.setHours(0, 0, 0, 0);
      continue;
    }
    // Both day fields restricted: either matches (the usual cron rule).
    const dom = cron.days.has(t.getDate());
    const dow = cron.weekdays.has(t.getDay());
    const dayOk = cron.anyDay && cron.anyWeekday ? true : cron.anyDay ? dow : cron.anyWeekday ? dom : dom || dow;
    if (!dayOk) {
      t.setDate(t.getDate() + 1);
      t.setHours(0, 0, 0, 0);
      continue;
    }
    if (!cron.hours.has(t.getHours())) {
      t.setHours(t.getHours() + 1, 0, 0, 0);
      continue;
    }
    if (!cron.minutes.has(t.getMinutes())) {
      t.setMinutes(t.getMinutes() + 1, 0, 0);
      continue;
    }
    return t.getTime();
  }
  return null;
}

/** When the task runs next after `after`, or null (manual, past, or never). */
export function nextRun(schedule: Schedule, after = Date.now()): number | null {
  if (schedule.kind === "manual") return null;
  if (schedule.kind === "once") return schedule.at > after ? schedule.at : null;
  const expression = cronOf(schedule);
  if (!expression) return null;
  try {
    return nextCron(parseCron(expression), after);
  } catch {
    return null;
  }
}

/** Why a schedule cannot run, or null. */
export function scheduleProblem(schedule: Schedule): string | null {
  if (schedule.kind === "once") return Number.isFinite(schedule.at) ? null : "pick a date and time";
  if (schedule.kind === "weekly" && schedule.days.length === 0) return "pick at least one day";
  const expression = cronOf(schedule);
  if (!expression) return null;
  try {
    parseCron(expression);
    return null;
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
}

const clock = (time: string) => {
  const { h, m } = hm(time);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
};

/** "Every weekday at 09:00", "Once, Fri 7 Nov 14:30", … */
export function describeSchedule(schedule: Schedule): string {
  switch (schedule.kind) {
    case "manual":
      return "Only when you run it";
    case "once":
      return `Once, ${formatWhen(schedule.at)}`;
    case "hourly":
      return schedule.minute === 0 ? "Every hour" : `Every hour at :${String(schedule.minute).padStart(2, "0")}`;
    case "daily":
      return `Every day at ${clock(schedule.time)}`;
    case "weekdays":
      return `Every weekday at ${clock(schedule.time)}`;
    case "weekly": {
      const days = [...new Set(schedule.days)].sort().map((d) => DAY_NAMES[d % 7]);
      return `Every ${days.join(", ") || "Mon"} at ${clock(schedule.time)}`;
    }
    case "cron":
      return `Cron ${schedule.expression.trim()}`;
  }
}

/** "Today 09:00", "Tomorrow 09:00", "Fri 7 Nov 09:00". */
export function formatWhen(at: number, now = Date.now()): string {
  const d = new Date(at);
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(d) - day(new Date(now))) / 86_400_000);
  if (diff === 0) return `Today ${time}`;
  if (diff === 1) return `Tomorrow ${time}`;
  if (diff === -1) return `Yesterday ${time}`;
  return `${d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })} ${time}`;
}

/** A schedule from loose input (the agent's tools): kind plus fields. */
export function scheduleFrom(input: Record<string, unknown>): Schedule {
  const kind = String(input.kind ?? input.type ?? "manual");
  const time = typeof input.time === "string" ? input.time : "09:00";
  switch (kind) {
    case "once": {
      const at = typeof input.at === "number" ? input.at : Date.parse(String(input.at ?? ""));
      if (!Number.isFinite(at)) throw new Error('a "once" schedule needs `at` (ISO date and time)');
      return { kind, at };
    }
    case "hourly":
      return { kind, minute: Math.min(59, Math.max(0, Number(input.minute ?? 0) || 0)) };
    case "daily":
    case "weekdays":
      return { kind, time };
    case "weekly": {
      const days = Array.isArray(input.days) ? input.days.map(Number).filter((d) => d >= 0 && d <= 7) : [1];
      return { kind, time, days: days.length ? days.map((d) => d % 7) : [1] };
    }
    case "cron": {
      const expression = String(input.expression ?? input.cron ?? "");
      parseCron(expression);
      return { kind, expression };
    }
    case "manual":
      return { kind };
    default:
      throw new Error(`unknown schedule kind "${kind}"`);
  }
}
