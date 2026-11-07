// Skills, commands and agent types, as the active chat's engine sees them
// (RPC `list_customizations`, crates/evo-engine/src/customize.rs). Read by the
// Customize view and the composer's `/` menu.

import { create } from "zustand";
import { useEngineStore } from "./engine-store";

export type SkillState = "on" | "off" | "name-only" | "user-invocable-only";

export interface SkillInfo {
  name: string;
  /** `command`: a command file (`.evo/commands/x.md`); `skill`: a SKILL.md folder. */
  kind: "skill" | "command";
  description: string;
  whenToUse?: string | null;
  argumentHint?: string | null;
  userInvocable: boolean;
  modelInvocable: boolean;
  allowedTools?: string | null;
  model?: string | null;
  license?: string | null;
  compatibility?: string | null;
  /** The spec's free-form map (author, version, …). */
  metadata?: Record<string, unknown> | null;
  /** Files in the skill folder besides SKILL.md, relative with `/`. */
  files?: string[];
  path: string;
  scope: "project" | "user";
  /** Which folder family it came from. */
  origin: "evo" | "agents" | "package" | "plugin";
  /** The plugin it comes with. */
  plugin?: string | null;
  state: SkillState;
  /** Runs counted (the `skill` tool and `/name`), and the last one (ms). */
  uses?: number;
  lastUsed?: number | null;
  /** Listed to the model by name only, to fit the listing budget. */
  nameOnlyForBudget?: boolean;
  content: string;
}

export interface SkillSettings {
  /** Characters of names and descriptions the model's skill listing may take. */
  listingBudget: number;
  /** `!`command`` lines in skills do not run. */
  shellDisabled: boolean;
}

export interface TemplateInfo {
  name: string;
  kind: "template";
  description: string;
}

export interface AgentInfo {
  name: string;
  description: string;
  tools?: string[] | null;
  model?: string | null;
  worktree: boolean;
  path?: string | null;
  scope: "project" | "user" | "builtin";
  origin: "evo" | "agents" | "package" | "plugin";
  plugin?: string | null;
  content: string;
}

export interface Customizations {
  skills: SkillInfo[];
  templates: TemplateInfo[];
  agents: AgentInfo[];
  settings?: SkillSettings;
}

interface CustomizeStore {
  data: Customizations | null;
  /** The chat the data was read from. */
  chat: string | null;
  loading: boolean;
  error: string | null;
  /** Read again from the active chat's engine (skipped when fresh, unless `force`). */
  load(force?: boolean): Promise<void>;
  /** Switch a skill on or off (or limit it) for every chat. */
  setSkillState(name: string, state: SkillState): Promise<void>;
  /** Change the skill settings for every chat (a budget of 0 restores the default). */
  setSkillSettings(change: Partial<SkillSettings>): Promise<void>;
}

/** Reads younger than this are reused. */
const FRESH_MS = 5000;
let loadedAt = 0;

export const useCustomizeStore = create<CustomizeStore>()((set, get) => ({
  data: null,
  chat: null,
  loading: false,
  error: null,

  async load(force = false) {
    const engine = useEngineStore.getState();
    const chat = engine.activeId;
    if (!chat || engine.runtimes[chat]?.status !== "ready") return;
    if (!force && get().chat === chat && get().data && Date.now() - loadedAt < FRESH_MS) return;
    set({ loading: true });
    try {
      const data = await engine.request<Customizations>("list_customizations");
      loadedAt = Date.now();
      set({ data, chat, loading: false, error: null });
    } catch (error) {
      set({ loading: false, error: String(error) });
    }
  },

  async setSkillState(name, state) {
    const engine = useEngineStore.getState();
    // Show it at once; the engine's answer replaces it.
    set((s) =>
      s.data ? { data: { ...s.data, skills: s.data.skills.map((x) => (x.name === name ? { ...x, state } : x)) } } : s,
    );
    try {
      await engine.request("set_skill_override", { name, state });
    } catch (error) {
      set({ error: String(error) });
    }
    // Other chats' engines read the change on reload (not while they run).
    await engine.reloadIdleResources().catch(() => undefined);
    await get().load(true);
  },

  async setSkillSettings(change) {
    const engine = useEngineStore.getState();
    set((s) =>
      s.data?.settings ? { data: { ...s.data, settings: { ...s.data.settings, ...change } } } : s,
    );
    try {
      await engine.request("set_skill_settings", change);
    } catch (error) {
      set({ error: String(error) });
    }
    await engine.reloadIdleResources().catch(() => undefined);
    await get().load(true);
  },
}));
