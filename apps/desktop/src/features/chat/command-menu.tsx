import * as React from "react";
import { FileTextIcon, PlugIcon, ScrollTextIcon, SlashIcon, SquareTerminalIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Connector } from "@/lib/mcp";
import type { Customizations } from "@/stores/customize-store";

// The composer's `/` menu: built-in commands, skills, command
// files and prompt templates. Typing filters by the start of a word in the
// name, ignoring `:`, `_` and `-` (`/adddir` finds `add-dir`, `/deploy` finds
// `tools:deploy`). ↑↓ move, Tab completes, Enter runs, Esc closes.

export type CommandKind = "builtin" | "skill" | "command" | "template" | "mcp";

export interface CommandItem {
  name: string;
  kind: CommandKind;
  description: string;
  argumentHint?: string | null;
  /** Where it comes from, shown on the right. */
  source?: string;
  /** A connector's prompt: which server, which prompt, its argument names. */
  mcp?: { server: string; prompt: string; args: string[] };
}

/** Commands the app runs itself (the engine never sees them). */
export const BUILTIN_COMMANDS: CommandItem[] = [
  { name: "clear", kind: "builtin", description: "Start a new chat", source: "Built-in" },
  { name: "compact", kind: "builtin", description: "Summarise older turns to free up context", source: "Built-in" },
  { name: "fork", kind: "builtin", description: "Copy this chat into a new one", source: "Built-in" },
  { name: "customize", kind: "builtin", description: "Manage skills, commands and agents", source: "Built-in" },
];

const sourceLabel = (scope: string, origin: string) =>
  origin === "package" ? "Package" : `${scope === "project" ? "Project" : "Personal"}${origin === "agents" ? " · .agents" : ""}`;

/** Every item the menu can show, built-ins first, connectors' prompts last. */
export function commandItems(data: Customizations | null, connectors: Connector[] = []): CommandItem[] {
  const items = [...BUILTIN_COMMANDS];
  for (const skill of data?.skills ?? []) {
    if (skill.state === "off" || !skill.userInvocable) continue;
    items.push({
      name: skill.name,
      kind: skill.kind,
      description: skill.description,
      argumentHint: skill.argumentHint,
      source: sourceLabel(skill.scope, skill.origin),
    });
  }
  for (const template of data?.templates ?? []) {
    if (items.some((item) => item.name === template.name)) continue;
    items.push({ name: template.name, kind: "template", description: template.description, source: "Template" });
  }
  for (const connector of connectors) {
    if (connector.status !== "connected") continue;
    for (const prompt of connector.prompts) {
      const args = prompt.arguments ?? [];
      items.push({
        name: `${connector.name}:${prompt.name}`,
        kind: "mcp",
        description: prompt.description ?? prompt.title ?? "",
        argumentHint: args.length ? args.map((a) => (a.required ? `<${a.name}>` : `[${a.name}]`)).join(" ") : null,
        source: `Connector · ${connector.name}`,
        mcp: { server: connector.name, prompt: prompt.name, args: args.map((a) => a.name) },
      });
    }
  }
  return items;
}

const fold = (text: string) => text.toLowerCase().replace(/[:_-]/g, "");

function score(item: CommandItem, query: string): number {
  if (!query) return 1;
  const q = query.toLowerCase();
  const name = item.name.toLowerCase();
  if (name === q) return 1000;
  if (name.startsWith(q)) return 500 - name.length;
  if (fold(name).startsWith(fold(q))) return 400 - name.length;
  if (name.split(/[:_-]/).some((word) => word.startsWith(q))) return 300 - name.length;
  if (name.includes(q)) return 100;
  if (item.description.toLowerCase().includes(q)) return 10;
  return 0;
}

/** The items matching what follows `/`, best first. */
export function matchCommands(items: CommandItem[], query: string): CommandItem[] {
  return items
    .map((item, index) => ({ item, index, score: score(item, query) }))
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((entry) => entry.item);
}

/** The known command a message starts with (`/name args`), if any. */
export function leadingCommand(text: string, items: CommandItem[]): CommandItem | undefined {
  const match = /^\/([A-Za-z0-9_:.-]+)(?=\s|$)/.exec(text);
  if (!match) return undefined;
  const name = match[1];
  return (
    items.find((item) => item.name === name) ??
    // A bare name finds a namespaced one when it is the only match.
    (() => {
      const found = items.filter((item) => item.name.split(":").pop() === name);
      return found.length === 1 ? found[0] : undefined;
    })()
  );
}

const icons: Record<CommandKind, React.ComponentType<{ className?: string }>> = {
  builtin: SquareTerminalIcon,
  skill: ScrollTextIcon,
  command: SlashIcon,
  template: FileTextIcon,
  mcp: PlugIcon,
};

const groupTitle: Record<CommandKind, string> = {
  builtin: "Commands",
  skill: "Skills",
  command: "Your commands",
  template: "Prompt templates",
  mcp: "From connectors",
};

export function CommandMenu({
  items,
  query,
  active,
  onActiveChange,
  onPick,
}: {
  items: CommandItem[];
  query: string;
  active: number;
  onActiveChange(index: number): void;
  onPick(item: CommandItem): void;
}) {
  const listRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (items.length === 0) {
    return (
      <div className="rounded-xl bg-popover px-3 py-2.5 text-[13px] text-muted-foreground shadow-lg ring-1 ring-foreground/10">
        No commands match “/{query}”
      </div>
    );
  }

  // Grouped by kind when browsing; one ranked list while filtering.
  const grouped = !query;
  const order: CommandKind[] = ["builtin", "skill", "command", "template", "mcp"];
  const sections = grouped
    ? order
        .map((kind) => ({ kind, entries: items.map((item, index) => ({ item, index })).filter((e) => e.item.kind === kind) }))
        .filter((section) => section.entries.length > 0)
    : [{ kind: null, entries: items.map((item, index) => ({ item, index })) }];

  return (
    <div
      ref={listRef}
      role="listbox"
      aria-label="Commands"
      className="scrollbar-slim max-h-80 overflow-y-auto rounded-xl bg-popover p-1 shadow-lg ring-1 ring-foreground/10"
    >
      {sections.map((section) => (
        <div key={section.kind ?? "all"} role="group" aria-label={section.kind ? groupTitle[section.kind] : "Matches"}>
          {section.kind && (
            <div className="px-2 pt-1.5 pb-1 text-[11px] font-medium text-muted-foreground">{groupTitle[section.kind]}</div>
          )}
          {section.entries.map(({ item, index }) => {
            const Icon = icons[item.kind];
            const selected = index === active;
            return (
              <button
                key={`${item.kind}:${item.name}`}
                type="button"
                role="option"
                aria-selected={selected}
                data-index={index}
                onMouseMove={() => onActiveChange(index)}
                // Keep the focus in the input.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => onPick(item)}
                className={cn(
                  "flex w-full min-w-0 items-center gap-2.5 rounded-lg px-2 py-1.5 text-left outline-none",
                  selected && "bg-brand/12",
                )}
              >
                <Icon className={cn("size-4 shrink-0", selected ? "text-brand" : "text-muted-foreground")} />
                <span className="shrink-0 text-[13px] font-medium">/{item.name}</span>
                {item.argumentHint && (
                  <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{item.argumentHint}</span>
                )}
                <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{item.description}</span>
                {item.source && <span className="shrink-0 text-[11px] text-muted-foreground/80">{item.source}</span>}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
