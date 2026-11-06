import * as React from "react";
import { emit } from "@tauri-apps/api/event";
import { PlusIcon, ShieldCheckIcon, Trash2Icon, TriangleAlertIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { db, log } from "@/lib/db";
import { inTauri } from "@/lib/platform";
import { SANDBOX_CHANGED } from "@/stores/engine-store";
import { useUiStore } from "@/stores/ui-store";
import { useEngineStore } from "@/stores/engine-store";
import { worktrees as worktreeApi, type WorktreeInfo } from "@/lib/worktrees";
import { WorktreeReview } from "@/components/ai-elements/worktree-review";
import { Segmented, SettingsGroup, SettingsHeader, SettingsRow } from "../settings-controls";

// Process security for the agent's shell and file tools. Saved in the app
// settings; every chat's engine starts with it (`--sandbox-config`, see
// src-tauri/src/engine.rs and crates/evo-tools/src/sandbox.rs).

interface SandboxConfig {
  inheritEnv: boolean;
  loadProfile: boolean;
  maxTimeoutSecs: number;
  maxOutputKib: number;
  deniedPatterns: string[];
  /** Where delegated agents' worktrees go (crates/evo-engine/src/worktrees.rs). */
  worktreeLocation: "repository" | "userData";
}

const KEY = "sandbox";

/** Same as `sandbox_defaults` in src-tauri/src/engine.rs. */
const DEFAULTS: SandboxConfig = {
  inheritEnv: true,
  loadProfile: false,
  maxTimeoutSecs: 600,
  maxOutputKib: 50,
  deniedPatterns: ["**/.env", "**/.env.*"],
  worktreeLocation: "userData",
};

/** A whole number in `[min, max]`, committed on Enter or when the field loses focus. */
function NumberField({
  value,
  min,
  max,
  unit,
  label,
  disabled,
  onCommit,
}: {
  value: number;
  min: number;
  max: number;
  unit: string;
  label: string;
  disabled?: boolean;
  onCommit(value: number): void;
}) {
  const [text, setText] = React.useState(String(value));
  React.useEffect(() => setText(String(value)), [value]);
  const commit = () => {
    const parsed = Math.round(Number(text));
    const next = Number.isFinite(parsed) && text.trim() !== "" ? Math.min(max, Math.max(min, parsed)) : value;
    setText(String(next));
    if (next !== value) onCommit(next);
  };
  return (
    <span className="flex items-center gap-2">
      <Input
        type="number"
        inputMode="numeric"
        aria-label={label}
        min={min}
        max={max}
        value={text}
        disabled={disabled}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") setText(String(value));
        }}
        className="h-8 w-24 rounded-lg bg-background text-right font-mono shadow-hairline [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none"
      />
      <span className="w-12 text-[13px] text-muted-foreground">{unit}</span>
    </span>
  );
}

/** Brackets and braces must pair up for a glob to be valid. */
function looksValid(pattern: string): boolean {
  let square = 0;
  let curly = 0;
  for (const ch of pattern) {
    if (ch === "[") square++;
    else if (ch === "]") square--;
    else if (ch === "{") curly++;
    else if (ch === "}") curly--;
    if (square < 0 || curly < 0) return false;
  }
  return square === 0 && curly === 0;
}

function DeniedPatterns({
  patterns,
  disabled,
  onChange,
}: {
  patterns: string[];
  disabled?: boolean;
  onChange(patterns: string[]): void;
}) {
  const [adding, setAdding] = React.useState(false);
  const [draft, setDraft] = React.useState("");
  const value = draft.trim();
  const invalid = value !== "" && !looksValid(value);
  const duplicate = patterns.includes(value);

  const add = () => {
    if (!value || invalid) return;
    if (!duplicate) onChange([...patterns, value]);
    setDraft("");
    setAdding(false);
  };

  return (
    <section>
      <div className="flex items-end justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold">Denied patterns</h2>
          <p className="mt-1 max-w-lg text-[13px] text-muted-foreground">
            Files the agent's read, write and edit tools refuse. Glob syntax: <code className="font-mono">*</code> stays
            in one folder, <code className="font-mono">**</code> crosses folders; patterns match full paths or paths inside
            the workspace.{" "}
            {patterns.length === 0
              ? "No patterns: every file is allowed."
              : `${patterns.length} ${patterns.length === 1 ? "pattern is" : "patterns are"} matched with logical OR. One match blocks access.`}
          </p>
        </div>
        <Button variant="outline" size="sm" disabled={disabled || adding} onClick={() => setAdding(true)}>
          <PlusIcon />
          Add
        </Button>
      </div>
      {(patterns.length > 0 || adding) && (
        <div className="mt-3 divide-y overflow-hidden rounded-xl bg-card shadow-hairline">
          {patterns.map((pattern) => (
            <div key={pattern} className="flex items-center justify-between gap-4 py-2 pr-2 pl-5">
              <code className="truncate font-mono text-[13px]">{pattern}</code>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Remove ${pattern}`}
                disabled={disabled}
                className="text-muted-foreground hover:text-destructive"
                onClick={() => onChange(patterns.filter((p) => p !== pattern))}
              >
                <Trash2Icon />
              </Button>
            </div>
          ))}
          {adding && (
            <div className="flex items-center gap-2 px-3 py-2">
              <Input
                autoFocus
                value={draft}
                aria-label="New denied pattern"
                aria-invalid={invalid || undefined}
                placeholder="**/secrets/**"
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") add();
                  if (event.key === "Escape") {
                    setDraft("");
                    setAdding(false);
                  }
                }}
                className="h-8 flex-1 rounded-lg bg-background font-mono shadow-hairline"
              />
              <Button size="sm" disabled={!value || invalid} onClick={add}>
                Add
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setDraft("");
                  setAdding(false);
                }}
              >
                Cancel
              </Button>
            </div>
          )}
        </div>
      )}
      {adding && (invalid || duplicate) && (
        <p className="mt-2 text-[13px] text-destructive">
          {invalid ? "Brackets [ ] and braces { } must come in pairs." : "That pattern is already in the list."}
        </p>
      )}
    </section>
  );
}

/** The open chat's repository's managed worktrees, each reviewable. */
function ExistingWorktrees() {
  const cwd = useEngineStore((s) => s.cwd);
  const [list, setList] = React.useState<WorktreeInfo[]>([]);
  const [reviewing, setReviewing] = React.useState<WorktreeInfo | null>(null);
  const load = React.useCallback(() => {
    if (!cwd || !inTauri) return;
    worktreeApi.list(cwd).then(setList).catch(() => setList([]));
  }, [cwd]);
  React.useEffect(load, [load]);
  if (!cwd || list.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5 px-5 py-4">
      <p className="text-[13px] font-medium">Worktrees of this repository</p>
      {list.map((worktree) => (
        <div key={worktree.path} className="flex items-center gap-2 text-[13px]">
          <code className="min-w-0 truncate font-mono text-xs" title={worktree.path}>
            {worktree.branch}
          </code>
          <span className="shrink-0 text-xs text-muted-foreground">
            {worktree.location === "repository" ? "in repository" : "user data"}
            {worktree.changed ? " · changed" : ""}
          </span>
          <Button variant="outline" size="sm" className="ml-auto h-6 px-2 text-xs" onClick={() => setReviewing(worktree)}>
            Review
          </Button>
        </div>
      ))}
      {reviewing && (
        <WorktreeReview
          open
          onOpenChange={(open) => {
            if (!open) {
              setReviewing(null);
              load();
            }
          }}
          repo={cwd}
          path={reviewing.path}
          branch={reviewing.branch}
        />
      )}
    </div>
  );
}

/** Whether an agent's start_session starts the session or only proposes it. */
function NestedSessionsGroup() {
  const autoStart = useUiStore((s) => s.autoStartSessions);
  const setAutoStart = useUiStore((s) => s.setAutoStartSessions);
  return (
    <SettingsGroup
      title="Nested sessions"
      description="An agent can start a separate chat for a task of its own; it appears under its chat in the sidebar and reports back when it finishes a turn."
    >
      <SettingsRow
        labelId="sandbox-auto-sessions"
        label="Start sessions without asking"
        description="Off, an agent only proposes a session and you start it from the card in the chat. On, it starts at once. Each session runs and spends on its own."
        control={
          <Switch aria-labelledby="sandbox-auto-sessions" checked={autoStart} onCheckedChange={setAutoStart} />
        }
      />
    </SettingsGroup>
  );
}

export function SandboxSettings() {
  const [config, setConfig] = React.useState<SandboxConfig | null>(inTauri ? null : DEFAULTS);
  const announce = React.useRef<number | undefined>(undefined);

  React.useEffect(() => {
    if (!inTauri) return;
    db.settings()
      .then((settings) => setConfig({ ...DEFAULTS, ...((settings[KEY] as Partial<SandboxConfig> | undefined) ?? {}) }))
      .catch(() => setConfig(DEFAULTS));
  }, []);

  function save(patch: Partial<SandboxConfig>) {
    if (!config) return;
    const next = { ...config, ...patch };
    setConfig(next);
    if (!inTauri) return;
    db.setSetting(KEY, next)
      .then(() => {
        // Restart idle engines once the person stops changing things.
        window.clearTimeout(announce.current);
        announce.current = window.setTimeout(() => void emit(SANDBOX_CHANGED).catch(() => undefined), 600);
      })
      .catch((error) => log("error", "settings", `saving the sandbox settings failed: ${String(error)}`));
  }

  const disabled = !config;
  const value = config ?? DEFAULTS;

  return (
    <div className="flex flex-col gap-8">
      <SettingsHeader
        icon={ShieldCheckIcon}
        title="Sandbox"
        description="What the agent's shell commands and file tools may reach. Changes apply to idle chats right away; a chat in the middle of a reply picks them up when its engine next starts."
      />
      <SettingsGroup
        title="Process security"
        description="Limits and environment for the agent's shell commands (bash and PowerShell)."
      >
        <SettingsRow
          labelId="sandbox-inherit"
          label="Inherit host environment"
          description="Pass this computer's environment variables to shell commands. Off, they get only PATH, home and user, locale, terminal, temporary-directory and system-folder values: no tokens or API keys."
          control={
            <Switch
              aria-labelledby="sandbox-inherit"
              checked={value.inheritEnv}
              disabled={disabled}
              onCheckedChange={(inheritEnv) => save({ inheritEnv })}
            />
          }
        />
        <SettingsRow
          labelId="sandbox-profile"
          label="Load shell profile"
          description={
            <>
              Run bash as a login shell, which reads <code className="font-mono">~/.bash_profile</code> or{" "}
              <code className="font-mono">~/.profile</code>, and let PowerShell load <code className="font-mono">$PROFILE</code>.
              Turn on only for aliases, functions and other exports commands need; profiles often export credentials.
            </>
          }
          control={
            <Switch
              aria-labelledby="sandbox-profile"
              checked={value.loadProfile}
              disabled={disabled}
              onCheckedChange={(loadProfile) => save({ loadProfile })}
            />
          }
        />
        <SettingsRow
          label="Maximum execution time"
          description="Hard cap for a shell command, including a longer timeout the agent asks for. The command is stopped when it runs out."
          control={
            <NumberField
              label="Maximum execution time in seconds"
              value={value.maxTimeoutSecs}
              min={1}
              max={86_400}
              unit="seconds"
              disabled={disabled}
              onCommit={(maxTimeoutSecs) => save({ maxTimeoutSecs })}
            />
          }
        />
        <SettingsRow
          label="Maximum inline output"
          description="Output beyond this (or 2,000 lines) is cut: the agent sees the end of it and the path of a file holding more."
          control={
            <NumberField
              label="Maximum inline output in KiB"
              value={value.maxOutputKib}
              min={1}
              max={10_240}
              unit="KiB"
              disabled={disabled}
              onCommit={(maxOutputKib) => save({ maxOutputKib })}
            />
          }
        />
        <div className="px-5 py-4">
          <p className="flex gap-2.5 rounded-lg bg-status-warn/10 px-3.5 py-3 text-[13px] text-foreground ring-1 ring-status-warn/25 ring-inset">
            <TriangleAlertIcon className="mt-0.5 size-4 shrink-0 text-status-warn" />
            Commands run directly on this computer and can reach files or the network through the programs they start.
            Denied patterns guard the file tools; they are not OS-level containment.
          </p>
        </div>
      </SettingsGroup>
      <SettingsGroup
        title="Managed worktrees"
        description="Where evo creates isolated Git worktrees for delegated agents. Existing worktrees in either location stay recognised and removable."
      >
        <SettingsRow
          label={
            <Segmented
              value={value.worktreeLocation}
              onValueChange={(worktreeLocation) => save({ worktreeLocation })}
              options={[
                { value: "userData", label: "User data directory" },
                { value: "repository", label: "Inside repository" },
              ]}
            />
          }
          description={
            value.worktreeLocation === "repository" ? (
              <>
                New worktrees are stored at <code className="font-mono">{"<repository>/.evo/worktrees"}</code>. evo adds
                this folder to the repository-local Git exclude file, without changing{" "}
                <code className="font-mono">.gitignore</code>.
              </>
            ) : (
              <>
                New worktrees are stored under <code className="font-mono">~/.evo/agent/worktrees</code>, one folder per
                repository, so nothing is added to the repository.
              </>
            )
          }
        />
        <ExistingWorktrees />
      </SettingsGroup>
      <NestedSessionsGroup />
      <DeniedPatterns
        patterns={value.deniedPatterns}
        disabled={disabled}
        onChange={(deniedPatterns) => save({ deniedPatterns })}
      />
    </div>
  );
}
