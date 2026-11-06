// Model providers: the catalog the engine knows, which ones are connected,
// and the actions that connect, sign in, refresh and disconnect them.
//
// The engine owns every credential. This store only ever sends a secret once,
// on save; rows coming back say whether one is saved, never what it is.
// Changes take effect immediately: the engine hot-swaps its provider runtimes,
// so the chat keeps its session and the model list refreshes.

import { create } from "zustand";
import type { LoginState, ModelsDevStatus, ProviderMutation, ProviderRow, ProvidersList, ProviderUsage } from "@/engine/protocol";
import { notify } from "@/features/notifications/notify";
import { useEngineStore } from "@/stores/engine-store";

/** Field values from a provider form; `""` clears a field. */
export type ProviderValues = Record<string, string>;

interface ProviderStore {
  providers: ProviderRow[];
  recommended: string[];
  connected: number;
  modelsDev?: ModelsDevStatus;
  loading: boolean;
  error?: string;
  /** Provider ids with a save, refresh, sign-in or removal in flight. */
  busy: Record<string, "saving" | "refreshing" | "removing" | "signing-in" | undefined>;

  load(): Promise<void>;
  save(id: string, values: ProviderValues): Promise<ProviderMutation>;
  refreshModels(id: string): Promise<ProviderMutation>;
  remove(id: string): Promise<ProviderMutation>;
  /** Start a sign-in; the engine reports the outcome with `providers_changed`. */
  login(id: string): Promise<LoginState>;
  /** Plan usage and quota of a subscription provider. */
  usage(id: string): Promise<ProviderUsage>;
  cancelLogin(id: string): Promise<void>;
  refreshCatalog(): Promise<void>;
}

const engine = () => useEngineStore.getState();

export const useProviderStore = create<ProviderStore>((set, get) => {
  const replaceRow = (row: ProviderRow | null | undefined) => {
    if (!row) return;
    set((store) => {
      const providers = store.providers.map((p) => (p.id === row.id ? row : p));
      return { providers, connected: providers.filter((p) => p.connected).length };
    });
  };

  /** Replace one row and recount, then let the chat pick up new models. */
  const applyMutation = (result: ProviderMutation) => {
    replaceRow(result.provider);
    if (result.reload?.modelChanged && !result.reload.unconfigured && result.reload.modelId) {
      notify({
        source: "engine",
        level: "success",
        title: "Model switched",
        body: `Now using ${result.reload.provider}/${result.reload.modelId}.`,
        key: "providers:model",
      });
    }
    void engine().refreshState();
    return result;
  };

  const run = async (
    id: string,
    kind: "saving" | "refreshing" | "removing",
    command: () => Promise<ProviderMutation>,
  ) => {
    set((store) => ({ busy: { ...store.busy, [id]: kind } }));
    try {
      return applyMutation(await command());
    } finally {
      set((store) => ({ busy: { ...store.busy, [id]: undefined } }));
    }
  };

  // Sign-ins finish in the background; the engine announces them.
  if (typeof window !== "undefined") {
    window.addEventListener("evo:providers-changed", (event) => {
      const detail = (event as CustomEvent).detail as { provider?: string; reason?: string } | undefined;
      if (detail?.provider) set((store) => ({ busy: { ...store.busy, [detail.provider!]: undefined } }));
      void get().load();
      if (detail?.reason === "login" && detail.provider) {
        const label = get().providers.find((p) => p.id === detail.provider)?.label ?? detail.provider;
        notify({ source: "engine", level: "success", title: "Signed in", body: `${label} is connected.`, key: `providers:${detail.provider}` });
      }
    });
  }

  return {
    providers: [],
    recommended: [],
    connected: 0,
    loading: false,
    busy: {},

    async load() {
      set({ loading: get().providers.length === 0, error: undefined });
      try {
        const list = await engine().request<ProvidersList>("get_providers");
        set({
          providers: list.providers,
          recommended: list.recommended,
          connected: list.connected,
          modelsDev: list.modelsDev,
          loading: false,
        });
      } catch (error) {
        set({ loading: false, error: error instanceof Error ? error.message : String(error) });
      }
    },

    save(id, values) {
      return run(id, "saving", () => engine().request<ProviderMutation>("set_provider", { provider: id, values }));
    },

    refreshModels(id) {
      return run(id, "refreshing", () => engine().request<ProviderMutation>("refresh_provider_models", { provider: id }));
    },

    remove(id) {
      return run(id, "removing", () => engine().request<ProviderMutation>("remove_provider", { provider: id }));
    },

    async login(id) {
      set((store) => ({ busy: { ...store.busy, [id]: "signing-in" } }));
      try {
        const result = await engine().request<{ provider: string; login: LoginState }>("provider_login", { provider: id });
        set((store) => ({
          providers: store.providers.map((p) => (p.id === id ? { ...p, loginState: result.login } : p)),
        }));
        return result.login;
      } catch (error) {
        set((store) => ({ busy: { ...store.busy, [id]: undefined } }));
        throw error;
      }
    },

    usage(id) {
      return engine().request<ProviderUsage>("get_provider_usage", { provider: id });
    },

    async cancelLogin(id) {
      await engine().request("provider_login_cancel", { provider: id }).catch(() => undefined);
      set((store) => ({
        busy: { ...store.busy, [id]: undefined },
        providers: store.providers.map((p) => (p.id === id ? { ...p, loginState: null } : p)),
      }));
    },

    async refreshCatalog() {
      await engine().request("refresh_models_catalog");
      await get().load();
    },
  };
});

/** Rows in the order the page shows them within a section. */
export function byRank(a: ProviderRow, b: ProviderRow): number {
  return a.rank - b.rank || a.label.localeCompare(b.label);
}

export function matchesProvider(row: ProviderRow, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [row.label, row.id, row.description, row.api].some((text) => text.toLowerCase().includes(q));
}
