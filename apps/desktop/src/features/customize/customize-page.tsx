import * as React from "react";
import {
  BlocksIcon,
  BracesIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  ExternalLinkIcon,
  FileCodeIcon,
  FileIcon,
  FileTextIcon,
  FolderIcon,
  FolderOpenIcon,
  ImageIcon,
  NotebookPenIcon,
  PlugIcon,
  RefreshCwIcon,
  ScrollTextIcon,
  SearchIcon,
  SlashIcon,
  WebhookIcon,
  XIcon,
} from "lucide-react";
import { openPath, revealItemInDir } from "@tauri-apps/plugin-opener";
import { AgentIcon } from "@/components/icons/agent-icon";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { readFile, type FileContent } from "@/features/files/fs";
import { formatBytes, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useCustomizeStore, type AgentInfo, type SkillInfo, type SkillState } from "@/stores/customize-store";
import { useEngineStore } from "@/stores/engine-store";
import { useUiStore, type CustomizeSection } from "@/stores/ui-store";
import { useConnectorsStore } from "@/stores/connectors-store";
import { ConnectorsSection } from "./connectors-section";
import { HooksSection } from "./hooks-section";
import { InstructionsSection } from "./instructions-section";
import { LanguagesSection } from "./languages-section";
import { PluginsSection } from "./plugins-section";
import { Badge, EmptyNote, IconAction, ListRow, Properties, Split } from "./customize-parts";

// Customize: everything that shapes what the agent can do, in one place.
// Skills are folders (SKILL.md plus references/, assets/, scripts/ …) or
// single command files; agent types are markdown files. All are read from the
// active chat's engine (crates/evo-engine/src/customize.rs); connectors,
// plugins and hooks come in later phases
// (docs/design/customize-skills-plugins-connectors.md).

const sections: { id: CustomizeSection; title: string; icon: React.ComponentType<{ className?: string }>; soon?: boolean }[] = [
  { id: "instructions", title: "Instructions", icon: NotebookPenIcon },
  { id: "skills", title: "Skills", icon: ScrollTextIcon },
  { id: "agents", title: "Subagents", icon: AgentIcon },
  { id: "connectors", title: "Connectors", icon: PlugIcon },
  { id: "plugins", title: "Plugins", icon: BlocksIcon },
  { id: "hooks", title: "Hooks", icon: WebhookIcon },
  { id: "languages", title: "Code intelligence", icon: BracesIcon },
];

type Scope = "all" | "user" | "project";

const stateOptions: { id: SkillState; label: string; hint: string }[] = [
  { id: "on", label: "On", hint: "The agent loads it when a task matches; /name runs it" },
  { id: "user-invocable-only", label: "Only /name", hint: "Hidden from the agent; you run it with /name" },
  { id: "name-only", label: "Name only", hint: "Listed to the agent without its description" },
  { id: "off", label: "Off", hint: "Not loaded" },
];

function sourceLabel(item: { scope: string; origin: string; plugin?: string | null }) {
  if (item.scope === "builtin") return "Built-in";
  if (item.plugin) return `Plugin · ${item.plugin}`;
  if (item.origin === "package") return "Package";
  const where = item.scope === "project" ? "Project" : "Personal";
  return item.origin === "agents" ? `${where} · .agents` : where;
}

/** The folder a file is in, with the path's own separator. */
const folderOf = (path: string) => path.replace(/[\\/][^\\/]*$/, "");
const sepOf = (path: string) => (path.includes("\\") ? "\\" : "/");
const joinPath = (dir: string, relative: string) => `${dir}${sepOf(dir)}${relative.split("/").join(sepOf(dir))}`;

/** `a/b/../c.md` relative to `from` (a file inside the skill), as `a/c.md`; `null` when it leaves the skill. */
function resolveRelative(from: string, href: string): string | null {
  const base = from.includes("/") ? from.slice(0, from.lastIndexOf("/")).split("/") : [];
  const parts = [...base];
  for (const part of href.split("#")[0].split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") {
      if (!parts.length) return null;
      parts.pop();
    } else parts.push(decodeURIComponent(part));
  }
  return parts.join("/");
}

const CODE = /\.(py|sh|bash|ps1|js|mjs|ts|tsx|rs|go|rb|lua|json|ya?ml|toml|sql|html|css)$/i;
const IMAGE = /\.(png|jpe?g|gif|webp|svg|ico|bmp|avif)$/i;
const MARKDOWN = /\.(md|mdx|markdown)$/i;

function FileGlyph({ name, className }: { name: string; className?: string }) {
  const Icon = IMAGE.test(name) ? ImageIcon : CODE.test(name) ? FileCodeIcon : MARKDOWN.test(name) || /\.txt$/i.test(name) ? FileTextIcon : FileIcon;
  return <Icon className={className} />;
}

const languageOf = (name: string) => /\.([a-z0-9]+)$/i.exec(name)?.[1]?.toLowerCase() ?? "text";

// ── Bits ────────────────────────────────────────────────────────────────────

function SearchBox({ value, onChange, placeholder }: { value: string; onChange(v: string): void; placeholder: string }) {
  return (
    <label className="flex h-8 w-56 min-w-0 items-center gap-2 rounded-lg border border-border/70 bg-background px-2.5 text-[13px] focus-within:border-brand/60 focus-within:ring-3 focus-within:ring-brand/15">
      <SearchIcon className="size-3.5 shrink-0 text-muted-foreground" />
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => event.key === "Escape" && onChange("")}
        placeholder={placeholder}
        className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground focus-visible:shadow-none"
      />
      {value && (
        <button type="button" aria-label="Clear" onClick={() => onChange("")} className="text-muted-foreground hover:text-foreground">
          <XIcon className="size-3.5" />
        </button>
      )}
    </label>
  );
}

function ScopeTabs({ value, onChange }: { value: Scope; onChange(scope: Scope): void }) {
  const options: { id: Scope; label: string }[] = [
    { id: "all", label: "All" },
    { id: "user", label: "Personal" },
    { id: "project", label: "Project" },
  ];
  return (
    <div role="tablist" aria-label="Scope" className="flex shrink-0 items-center gap-0.5 rounded-lg bg-muted/70 p-0.5 dark:bg-accent/50">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          role="tab"
          aria-selected={value === option.id}
          onClick={() => onChange(option.id)}
          className={cn(
            "h-7 rounded-md px-2.5 text-xs transition-colors",
            value === option.id ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function groupBySource<T extends { scope: string; origin: string }>(items: T[]) {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const plugin = (item as { plugin?: string | null }).plugin;
    const key =
      item.scope === "builtin"
        ? "Built-in"
        : plugin
          ? `Plugin · ${plugin}`
          : item.origin === "package"
            ? "From packages"
            : item.scope === "project"
              ? "This project"
              : "Personal";
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  const order = ["This project", "Personal", "From packages", "Built-in"];
  const rank = (key: string) => (key.startsWith("Plugin · ") ? 2.5 : order.indexOf(key));
  return [...groups.entries()].sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0]));
}

// ── Skill files: a tree and a viewer ────────────────────────────────────────

interface TreeNode {
  name: string;
  /** Relative path with `/`. */
  path: string;
  children?: TreeNode[];
}

/** `files` as a tree; `first` (the skill's SKILL.md) stays on top, then folders, then files. */
function buildTree(files: string[], first?: string): TreeNode[] {
  const root: TreeNode[] = [];
  for (const file of files) {
    let level = root;
    const parts = file.split("/");
    parts.forEach((part, index) => {
      const path = parts.slice(0, index + 1).join("/");
      const leaf = index === parts.length - 1;
      let node = level.find((n) => n.name === part && !!n.children === !leaf);
      if (!node) {
        node = leaf ? { name: part, path } : { name: part, path, children: [] };
        level.push(node);
      }
      if (node.children) level = node.children;
    });
  }
  const sort = (nodes: TreeNode[]) => {
    const rank = (n: TreeNode) => (n.path === first ? 0 : n.children ? 1 : 2);
    nodes.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
    nodes.forEach((n) => n.children && sort(n.children));
  };
  sort(root);
  return root;
}

function FileTree({
  nodes,
  selected,
  onSelect,
  depth = 0,
}: {
  nodes: TreeNode[];
  selected: string;
  onSelect(path: string): void;
  depth?: number;
}) {
  const [closed, setClosed] = React.useState<Set<string>>(new Set());
  return (
    <>
      {nodes.map((node) => {
        const open = node.children && !closed.has(node.path);
        return (
          <React.Fragment key={node.path}>
            <button
              type="button"
              onClick={() =>
                node.children
                  ? setClosed((s) => {
                      const next = new Set(s);
                      if (next.has(node.path)) next.delete(node.path);
                      else next.add(node.path);
                      return next;
                    })
                  : onSelect(node.path)
              }
              style={{ paddingLeft: 8 + depth * 14 }}
              className={cn(
                "flex h-7 w-full min-w-0 items-center gap-1.5 rounded-md pr-2 text-left text-[13px] transition-colors",
                !node.children && node.path === selected ? "bg-brand/12 text-foreground" : "hover:bg-accent/60",
              )}
            >
              {node.children ? (
                <>
                  {open ? <ChevronDownIcon className="size-3.5 shrink-0 text-muted-foreground" /> : <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground" />}
                  {open ? <FolderOpenIcon className="size-3.5 shrink-0 text-muted-foreground" /> : <FolderIcon className="size-3.5 shrink-0 text-muted-foreground" />}
                </>
              ) : (
                <>
                  <span className="w-3.5 shrink-0" />
                  <FileGlyph name={node.name} className={cn("size-3.5 shrink-0", node.path === selected ? "text-brand" : "text-muted-foreground")} />
                </>
              )}
              <span className="truncate">{node.name}</span>
            </button>
            {open && node.children && <FileTree nodes={node.children} selected={selected} onSelect={onSelect} depth={depth + 1} />}
          </React.Fragment>
        );
      })}
    </>
  );
}

/** One file of a skill: markdown rendered, text as code, images shown. */
function FileView({
  absolute,
  relative,
  body,
  onOpenRelative,
}: {
  absolute: string;
  relative: string;
  /** Known text (SKILL.md's body), so it is not read again. */
  body?: string;
  onOpenRelative(href: string): void;
}) {
  const [content, setContent] = React.useState<FileContent | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (body !== undefined) return;
    let live = true;
    setContent(null);
    setError(null);
    readFile(absolute)
      .then((c) => live && setContent(c))
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [absolute, body]);

  if (body !== undefined) {
    return <Markdown onLocalLink={onOpenRelative}>{body || "_Empty_"}</Markdown>;
  }
  if (error) return <p className="text-[13px] text-muted-foreground">Could not read this file: {error}</p>;
  if (!content)
    return (
      <div className="flex justify-center py-8">
        <Spinner className="size-4 text-muted-foreground" />
      </div>
    );
  if (content.kind === "image") return <img src={content.dataUrl} alt={relative} className="max-h-96 max-w-full rounded-md ring-1 ring-border" />;
  if (content.kind !== "text")
    return (
      <div className="flex items-center justify-between gap-3 text-[13px] text-muted-foreground">
        <span>{content.kind === "binary" ? "Binary file" : "Too large to show"} · {formatBytes(content.size)}</span>
        <Button size="xs" variant="outline" onClick={() => void openPath(absolute).catch(() => undefined)}>
          Open
        </Button>
      </div>
    );
  if (MARKDOWN.test(relative)) return <Markdown onLocalLink={onOpenRelative}>{content.text || "_Empty_"}</Markdown>;
  return <Markdown>{`\`\`\`${languageOf(relative)}\n${content.text}\n\`\`\``}</Markdown>;
}

/** A skill's folder: the files on the left, the chosen one on the right. */
function SkillFiles({ skill }: { skill: SkillInfo }) {
  const folder = skill.kind === "skill";
  const main = folder ? "SKILL.md" : skill.path.split(/[\\/]/).pop() ?? skill.name;
  const files = React.useMemo(() => [main, ...(skill.files ?? [])], [main, skill.files]);
  const tree = React.useMemo(() => buildTree(files, main), [files, main]);
  const [selected, setSelected] = React.useState(main);
  React.useEffect(() => setSelected(main), [skill.path, main]);
  const root = folderOf(skill.path);
  const absolute = selected === main ? skill.path : joinPath(root, selected);

  const openRelative = (href: string) => {
    const target = resolveRelative(selected, href);
    if (target && files.includes(target)) setSelected(target);
    else if (target) void openPath(joinPath(root, target)).catch(() => undefined);
  };

  return (
    <div className={cn("flex overflow-hidden rounded-xl border border-border/70", folder && "min-h-80")}>
      {folder && (
        <div className="flex w-52 shrink-0 flex-col border-r border-border/60 bg-muted/30 dark:bg-accent/20">
          <div className="flex h-9 items-center gap-1.5 border-b border-border/60 px-3 text-xs text-muted-foreground">
            <FolderIcon className="size-3.5" />
            <span className="truncate font-medium text-foreground">{root.split(/[\\/]/).pop()}</span>
            <span className="ml-auto tabular-nums">{files.length}</span>
          </div>
          <div className="scrollbar-slim min-h-0 flex-1 overflow-y-auto p-1.5">
            <FileTree nodes={tree} selected={selected} onSelect={setSelected} />
          </div>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-9 shrink-0 items-center gap-2 border-b border-border/60 px-3">
          <FileGlyph name={selected} className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate font-mono text-xs">{selected}</span>
          {selected === main && folder && <Badge>Instructions</Badge>}
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  size="icon-xs"
                  variant="ghost"
                  aria-label="Open in the default app"
                  onClick={() => void openPath(absolute).catch(() => undefined)}
                  className="text-muted-foreground"
                />
              }
            >
              <ExternalLinkIcon />
            </TooltipTrigger>
            <TooltipContent>Open in the default app</TooltipContent>
          </Tooltip>
        </div>
        <div className="scrollbar-slim min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <FileView
            key={absolute}
            absolute={absolute}
            relative={selected}
            body={selected === main ? skill.content : undefined}
            onOpenRelative={openRelative}
          />
        </div>
      </div>
    </div>
  );
}

// ── Skills ──────────────────────────────────────────────────────────────────

function StateMenu({ skill }: { skill: SkillInfo }) {
  const setSkillState = useCustomizeStore((s) => s.setSkillState);
  const current = stateOptions.find((o) => o.id === skill.state) ?? stateOptions[0];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button size="sm" variant="outline" className={cn("gap-1.5", skill.state !== "off" && "border-brand/40 text-brand")} />
        }
      >
        <span className={cn("size-1.5 rounded-full", skill.state === "off" ? "bg-muted-foreground/50" : "bg-brand")} />
        {current.label}
        <ChevronDownIcon className="size-3.5 opacity-70" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Who can use it</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={skill.state} onValueChange={(value) => void setSkillState(skill.name, value as SkillState)}>
            {stateOptions.map((option) => (
              <DropdownMenuRadioItem key={option.id} value={option.id} closeOnClick>
                <div className="flex flex-col">
                  <span>{option.label}</span>
                  <span className="text-xs text-muted-foreground">{option.hint}</span>
                </div>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function metaText(metadata: Record<string, unknown> | null | undefined, key: string): string | undefined {
  const value = metadata?.[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : undefined;
}

function SkillDetail({ skill }: { skill: SkillInfo }) {
  const folder = skill.kind === "skill";
  const otherMeta = Object.entries(skill.metadata ?? {}).filter(([key]) => key !== "author" && key !== "version");
  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand/12 text-brand">
          {folder ? <ScrollTextIcon className="size-5" /> : <SlashIcon className="size-5" />}
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold">{skill.name}</h2>
            <Badge>{folder ? "Skill" : "Command"}</Badge>
            <Badge>{sourceLabel(skill)}</Badge>
            {metaText(skill.metadata, "version") && <Badge>v{metaText(skill.metadata, "version")}</Badge>}
          </div>
          <p className="text-[13px] leading-relaxed text-muted-foreground">{skill.description}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <IconAction label="Show in folder" onClick={() => void revealItemInDir(skill.path).catch(() => undefined)}>
            <FolderOpenIcon />
          </IconAction>
          <StateMenu skill={skill} />
        </div>
      </header>

      <div className="@container rounded-xl bg-muted/40 px-4 py-3 dark:bg-accent/30">
        <Properties
          items={[
            ["Run it", <code className="font-mono text-xs">/{skill.name}{skill.argumentHint ? ` ${skill.argumentHint}` : ""}</code>],
            ["The agent", skill.modelInvocable && skill.state !== "user-invocable-only" && skill.state !== "off" ? "Loads it when a task matches" : "Never loads it on its own"],
            [
              "Used",
              skill.uses
                ? `${skill.uses} ${skill.uses === 1 ? "time" : "times"}${skill.lastUsed ? ` · last ${formatRelative(skill.lastUsed)}` : ""}`
                : "Not yet",
            ],
            ["Listing", skill.nameOnlyForBudget ? "Name only, to fit the listing budget (used less than others)" : undefined],
            ["When to use", skill.whenToUse],
            ["Allowed tools", skill.allowedTools && <code className="font-mono text-xs">{skill.allowedTools}</code>],
            ["Compatibility", skill.compatibility],
            ["License", skill.license],
            ["Author", metaText(skill.metadata, "author")],
            ...otherMeta.map(([key, value]): [string, React.ReactNode] => [key, String(value)]),
          ]}
        />
      </div>

      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-medium text-muted-foreground">{folder ? "Files" : "File"}</h3>
        <SkillFiles skill={skill} />
        <p className="truncate font-mono text-[11px] text-muted-foreground" title={skill.path}>
          {folder ? folderOf(skill.path) : skill.path}
        </p>
      </section>
    </div>
  );
}

function SkillsSection({ query, scope }: { query: string; scope: Scope }) {
  const data = useCustomizeStore((s) => s.data);
  const setSkillState = useCustomizeStore((s) => s.setSkillState);
  const [selected, setSelected] = React.useState<string | null>(null);
  const q = query.trim().toLowerCase();
  const skills = (data?.skills ?? []).filter(
    (skill) =>
      (scope === "all" || skill.scope === scope) &&
      (!q || skill.name.toLowerCase().includes(q) || skill.description.toLowerCase().includes(q)),
  );
  const current = skills.find((skill) => skill.name === selected) ?? skills[0];

  return (
    <Split
      list={
        skills.length === 0 ? (
          <EmptyNote title={q ? "No matching skills" : "No skills yet"}>
            A skill is a folder with a <code>SKILL.md</code> and any files it needs (<code>references/</code>,{" "}
            <code>assets/</code>, <code>scripts/</code>), in <code>.agents/skills</code> or <code>.evo/skills</code> of a
            project, or <code>~/.agents/skills</code> for every project. Single-file commands go in{" "}
            <code>.evo/commands</code>.
          </EmptyNote>
        ) : (
          groupBySource(skills).map(([group, items]) => (
            <div key={group} className="flex flex-col gap-0.5">
              <p className="px-2.5 pt-3 pb-1 text-[11px] font-medium text-muted-foreground">{group}</p>
              {items.map((skill) => (
                <ListRow
                  key={skill.name}
                  selected={current?.name === skill.name}
                  onSelect={() => setSelected(skill.name)}
                  icon={skill.kind === "command" ? <SlashIcon /> : <ScrollTextIcon />}
                  title={skill.name}
                  meta={
                    skill.uses ? (
                      <span className="shrink-0 text-[11px] text-muted-foreground" title="Times used">
                        {skill.uses}×
                      </span>
                    ) : skill.kind === "command" ? (
                      <span className="shrink-0 text-[11px] text-muted-foreground">Command</span>
                    ) : skill.files?.length ? (
                      <span className="shrink-0 text-[11px] text-muted-foreground">{skill.files.length + 1} files</span>
                    ) : null
                  }
                  description={skill.description}
                  dimmed={skill.state === "off"}
                  trailing={
                    <Switch
                      aria-label={`Use ${skill.name}`}
                      checked={skill.state !== "off"}
                      onCheckedChange={(on) => void setSkillState(skill.name, on ? "on" : "off")}
                    />
                  }
                />
              ))}
            </div>
          ))
        )
      }
      footer={data?.settings ? <SkillSettingsCard /> : null}
      detail={current ? <SkillDetail key={current.name} skill={current} /> : null}
    />
  );
}

/** Settings for every skill: the model's listing budget and shell lines. */
function SkillSettingsCard() {
  const settings = useCustomizeStore((s) => s.data?.settings);
  const setSkillSettings = useCustomizeStore((s) => s.setSkillSettings);
  const trimmed = useCustomizeStore((s) => s.data?.skills.filter((x) => x.nameOnlyForBudget).length ?? 0);
  const [budget, setBudget] = React.useState(String(settings?.listingBudget ?? ""));
  React.useEffect(() => setBudget(String(settings?.listingBudget ?? "")), [settings?.listingBudget]);
  if (!settings) return null;
  const commit = () => {
    const value = Math.round(Number(budget));
    if (!Number.isFinite(value) || value === settings.listingBudget) return setBudget(String(settings.listingBudget));
    void setSkillSettings({ listingBudget: Math.max(0, value) });
  };
  return (
    <div className="flex flex-col gap-3 rounded-xl bg-muted/40 px-3 py-3 text-xs dark:bg-accent/30">
      <p className="font-medium">Skill settings</p>
      <label className="flex flex-col gap-1">
        <span className="text-muted-foreground">Listing budget (characters the agent sees)</span>
        <input
          inputMode="numeric"
          value={budget}
          onChange={(e) => setBudget(e.target.value.replace(/[^0-9]/g, ""))}
          onBlur={commit}
          onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
          className="h-7 rounded-md border border-border bg-background px-2 font-mono text-xs outline-none focus-visible:border-brand"
        />
        <span className="text-muted-foreground">
          {trimmed
            ? `${trimmed} least-used ${trimmed === 1 ? "skill is" : "skills are"} listed by name only to fit.`
            : "Every description fits."}
        </span>
      </label>
      <div className="flex items-start justify-between gap-3">
        <span className="flex flex-col gap-0.5">
          <span>Run shell lines in skills</span>
          <span className="text-muted-foreground">
            <code>!`command`</code> runs when a skill loads and is replaced by its output.
          </span>
        </span>
        <Switch
          aria-label="Run shell lines in skills"
          checked={!settings.shellDisabled}
          onCheckedChange={(on) => void setSkillSettings({ shellDisabled: !on })}
        />
      </div>
    </div>
  );
}

// ── Subagents ───────────────────────────────────────────────────────────────

function AgentDetail({ agent }: { agent: AgentInfo }) {
  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand/12 text-brand">
          <AgentIcon agentType={agent.name} className="size-5" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold">{agent.name}</h2>
            <Badge>{sourceLabel(agent)}</Badge>
          </div>
          <p className="text-[13px] leading-relaxed text-muted-foreground">{agent.description}</p>
        </div>
        {agent.path && (
          <IconAction label="Show in folder" onClick={() => void revealItemInDir(agent.path!).catch(() => undefined)}>
            <FolderOpenIcon />
          </IconAction>
        )}
      </header>
      <div className="@container rounded-xl bg-muted/40 px-4 py-3 dark:bg-accent/30">
        <Properties
          items={[
            ["Tools", agent.tools?.length ? <code className="font-mono text-xs">{agent.tools.join(", ")}</code> : "Same as the chat"],
            ["Model", agent.model ?? "Same as the chat"],
            ["Works in", agent.worktree ? "Its own Git worktree" : "The chat's folder"],
          ]}
        />
      </div>
      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-medium text-muted-foreground">Instructions</h3>
        <div className="rounded-xl border border-border/70 px-5 py-4">
          <Markdown>{agent.content || "_No instructions_"}</Markdown>
        </div>
        {agent.path && (
          <p className="truncate font-mono text-[11px] text-muted-foreground" title={agent.path}>
            {agent.path}
          </p>
        )}
      </section>
    </div>
  );
}

function AgentsSection({ query, scope }: { query: string; scope: Scope }) {
  const data = useCustomizeStore((s) => s.data);
  const [selected, setSelected] = React.useState<string | null>(null);
  const q = query.trim().toLowerCase();
  const agents = (data?.agents ?? []).filter(
    (agent) =>
      (scope === "all" || agent.scope === scope || (scope === "user" && agent.scope === "builtin")) &&
      (!q || agent.name.toLowerCase().includes(q) || agent.description.toLowerCase().includes(q)),
  );
  const current = agents.find((agent) => agent.name === selected) ?? agents[0];
  return (
    <Split
      intro="Agent types the chat can hand self-contained tasks to. Add one as a markdown file in .evo/agents (this project) or ~/.evo/agent/agents."
      list={
        agents.length === 0 ? (
          <EmptyNote title="No matching subagents">
            A subagent type is a markdown file with a <code>description</code> in <code>.evo/agents</code> or{" "}
            <code>~/.evo/agent/agents</code>.
          </EmptyNote>
        ) : (
          groupBySource(agents).map(([group, items]) => (
            <div key={group} className="flex flex-col gap-0.5">
              <p className="px-2.5 pt-3 pb-1 text-[11px] font-medium text-muted-foreground">{group}</p>
              {items.map((agent) => (
                <ListRow
                  key={agent.name}
                  selected={current?.name === agent.name}
                  onSelect={() => setSelected(agent.name)}
                  icon={<AgentIcon agentType={agent.name} />}
                  title={agent.name}
                  description={agent.description}
                />
              ))}
            </div>
          ))
        )
      }
      detail={current ? <AgentDetail key={current.name} agent={current} /> : null}
    />
  );
}

// ── Layout ──────────────────────────────────────────────────────────────────

function ComingSoon({ section }: { section: CustomizeSection }) {
  const text: Partial<Record<CustomizeSection, string>> = {
    connectors: "MCP servers the agent can use: add a server by URL or command, sign in, and choose which tools need your approval.",
    plugins: "Bundles of skills, subagents, hooks and connectors, installed from a marketplace or a folder.",
    hooks: "Commands that run on agent events, such as before a tool runs or when a turn ends.",
  };
  const icon = sections.find((s) => s.id === section);
  return (
    <div className="flex flex-1 items-center justify-center px-6">
      <div className="flex max-w-sm flex-col items-center gap-2 text-center">
        {icon && (
          <span className="mb-1 flex size-10 items-center justify-center rounded-xl bg-muted text-muted-foreground dark:bg-accent">
            <icon.icon className="size-5" />
          </span>
        )}
        <p className="text-sm font-medium">Coming soon</p>
        <p className="text-[13px] text-balance text-muted-foreground">{text[section]}</p>
      </div>
    </div>
  );
}

/** Customize: instructions, skills, subagents, connectors, plugins and hooks. */
export function CustomizePage() {
  const section = useUiStore((s) => s.customizeSection);
  const openCustomize = useUiStore((s) => s.openCustomize);
  const activeId = useEngineStore((s) => s.activeId);
  const engineReady = useEngineStore((s) => (s.activeId ? s.runtimes[s.activeId]?.status === "ready" : false));
  const { data, loading, error, load } = useCustomizeStore();
  const [query, setQuery] = React.useState("");
  const [scope, setScope] = React.useState<Scope>("all");

  React.useEffect(() => {
    if (engineReady) void load(true);
  }, [engineReady, activeId, load]);

  const current = sections.find((s) => s.id === section) ?? sections[0];
  const connectedCount = useConnectorsStore((s) => s.servers.filter((c) => c.status === "connected").length);
  const counts: Partial<Record<CustomizeSection, number>> = {
    skills: data?.skills.filter((s) => s.state !== "off").length,
    agents: data?.agents.length,
    connectors: connectedCount || undefined,
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-background min-[900px]:rounded-tl-xl">
      <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-border/60 px-4 py-2.5">
        <h1 className="text-sm font-semibold">Customize</h1>
        <nav aria-label="Customize" role="tablist" className="flex min-w-0 items-center gap-0.5">
          {sections.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={item.id === section}
              onClick={() => openCustomize(item.id)}
              className={cn(
                "flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] transition-colors",
                item.id === section ? "bg-brand/12 text-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
              )}
            >
              <item.icon className={cn("size-4 shrink-0", item.id === section && "text-brand")} />
              {item.title}
              {item.soon ? (
                <span className="text-[10px] text-muted-foreground/80">Soon</span>
              ) : counts[item.id] !== undefined ? (
                <span className="text-[11px] text-muted-foreground tabular-nums">{counts[item.id]}</span>
              ) : null}
            </button>
          ))}
        </nav>
        {!current.soon && section !== "instructions" && (
          <div className="ml-auto flex items-center gap-2">
            <SearchBox value={query} onChange={setQuery} placeholder={`Search ${current.title.toLowerCase()}`} />
            {section !== "connectors" && section !== "hooks" && section !== "plugins" && section !== "languages" && (
              <ScopeTabs value={scope} onChange={setScope} />
            )}
            {section !== "connectors" && section !== "hooks" && section !== "plugins" && section !== "languages" && (
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label="Reload from disk"
                    disabled={!engineReady || loading}
                    onClick={() => {
                      void useEngineStore
                        .getState()
                        .request("reload_resources")
                        .then(() => load(true))
                        .catch(() => load(true));
                    }}
                    className="text-muted-foreground"
                  />
                }
              >
                <RefreshCwIcon className={cn(loading && "animate-spin")} />
              </TooltipTrigger>
              <TooltipContent>Reload from disk</TooltipContent>
            </Tooltip>
            )}
          </div>
        )}
      </header>
      {current.soon ? (
        <ComingSoon section={current.id} />
      ) : section === "instructions" ? (
        <InstructionsSection />
      ) : section === "languages" ? (
        <LanguagesSection query={query} />
      ) : section === "connectors" ? (
        <ConnectorsSection query={query} />
      ) : section === "hooks" ? (
        <HooksSection query={query} />
      ) : section === "plugins" ? (
        <PluginsSection query={query} />
      ) : !data ? (
        <div className="flex flex-1 items-center justify-center">
          {error ? (
            <p className="max-w-sm text-center text-[13px] text-muted-foreground">Could not read customizations: {error}</p>
          ) : (
            <Spinner className="size-4 text-muted-foreground" />
          )}
        </div>
      ) : section === "agents" ? (
        <AgentsSection query={query} scope={scope} />
      ) : (
        <SkillsSection query={query} scope={scope} />
      )}
    </div>
  );
}
