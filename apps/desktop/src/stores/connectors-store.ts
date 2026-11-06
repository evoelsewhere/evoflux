// Connectors as the shell's MCP pool reports them, kept fresh by its
// `mcp://changed` event. Read by Customize → Connectors, the composer's `/`
// menu (MCP prompts) and the engine store (tools for chats).

import { listen } from "@tauri-apps/api/event";
import { create } from "zustand";
import { mcp, MCP_CHANGED, type Connector } from "@/lib/mcp";

interface ConnectorsStore {
  servers: Connector[];
  /** Where the connectors file lives. */
  path: string;
  loaded: boolean;
  error: string | null;
  load(): Promise<void>;
}

/** Listeners told after each refresh (the engine store reconfigures chats). */
export const connectorsChanged = new Set<() => void>();

let listening = false;
let timer: ReturnType<typeof setTimeout> | undefined;

export const useConnectorsStore = create<ConnectorsStore>()((set, get) => ({
  servers: [],
  path: "",
  loaded: false,
  error: null,

  async load() {
    if (!listening) {
      listening = true;
      // Many changes come in bursts (a server connecting); refresh once per burst.
      void listen(MCP_CHANGED, () => {
        clearTimeout(timer);
        timer = setTimeout(() => void get().load(), 150);
      }).catch(() => (listening = false));
    }
    try {
      const state = await mcp.state();
      set({ servers: state.servers, path: state.path, loaded: true, error: null });
    } catch (error) {
      set({ loaded: true, error: String(error) });
    }
    for (const listener of connectorsChanged) listener();
  },
}));
