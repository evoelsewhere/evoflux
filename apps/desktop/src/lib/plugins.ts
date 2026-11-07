// Plugins and marketplaces (src-tauri/src/plugins.rs, crates/evo-plugins).

import { invoke } from "@tauri-apps/api/core";

export interface UserConfigOption {
  type?: "string" | "number" | "boolean" | "directory" | "file";
  title?: string;
  description?: string;
  required?: boolean;
  default?: unknown;
  sensitive?: boolean;
}

export interface InstalledPlugin {
  id: string;
  name: string;
  marketplace: string;
  version: string;
  enabled: boolean;
  path: string;
  installedAt: number;
  config: Record<string, unknown>;
  description?: string | null;
  author?: string | null;
  homepage?: string | null;
  repository?: string | null;
  license?: string | null;
  keywords: string[];
  userConfig: Record<string, UserConfigOption>;
  skills: string[];
  commands: number;
  agents: string[];
  hooks: { event: string; count: number }[];
  connectors: string[];
  bin: boolean;
  problems: string[];
}

export interface MarketplaceInfo {
  name: string;
  /** `owner/repo#ref`, a git URL, or a folder. */
  source: string;
  kind: "git" | "folder";
  location: string;
  description?: string | null;
  owner?: string | null;
  updatedAt: number;
  plugins: number;
  error?: string | null;
}

export interface CatalogEntry {
  id: string;
  name: string;
  marketplace: string;
  description?: string;
  version?: string;
  category?: string;
  keywords?: string[];
  author?: string | { name?: string };
  homepage?: string;
  /** The installed version, if installed. */
  installed?: string | null;
  error?: string;
}

export interface PluginsState {
  installed: InstalledPlugin[];
  marketplaces: MarketplaceInfo[];
  catalog: CatalogEntry[];
  root: string;
}

export const PLUGINS_CHANGED = "plugins://changed";

export const plugins = {
  state: () => invoke<PluginsState>("plugins_state"),
  addMarketplace: (source: string) => invoke<{ name: string }>("plugin_marketplace_add", { source }),
  updateMarketplace: (name: string) => invoke<void>("plugin_marketplace_update", { name }),
  removeMarketplace: (name: string) => invoke<void>("plugin_marketplace_remove", { name }),
  install: (marketplace: string, name: string) => invoke<{ id: string; version: string }>("plugin_install", { marketplace, name }),
  installFolder: (path: string) => invoke<{ id: string }>("plugin_install_folder", { path }),
  uninstall: (id: string) => invoke<void>("plugin_uninstall", { id }),
  update: (id: string) => invoke<{ id: string; version: string }>("plugin_update", { id }),
  setEnabled: (id: string, on: boolean) => invoke<void>("plugin_set_enabled", { id, on }),
  setConfig: (id: string, config: Record<string, unknown>) => invoke<void>("plugin_set_config", { id, config }),
};
