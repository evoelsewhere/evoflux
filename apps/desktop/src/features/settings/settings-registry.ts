import type * as React from "react";
import { CpuIcon, FileTextIcon, InfoIcon, KeyRoundIcon, PaletteIcon, ScrollTextIcon, ShieldCheckIcon, SlidersHorizontalIcon, type LucideIcon } from "lucide-react";
import type { SettingsSection } from "@/stores/ui-store";
import { AppearanceSettings } from "./sections/appearance-settings";
import { GeneralSettings } from "./sections/general-settings";
import { OfficeSettings } from "./sections/office-settings";
import { ProviderSettings } from "./sections/provider-settings";
import { LogsSettings } from "./sections/logs-settings";
import { SandboxSettings } from "./sections/sandbox-settings";
import { AboutSettings, EngineSettings } from "./sections/system-settings";

export interface SettingsPage {
  id: SettingsSection;
  title: string;
  icon: LucideIcon;
  group: "Application" | "System";
  /** Extra words the settings search matches. */
  keywords: string[];
  component: React.ComponentType;
}

export const settingsPages: SettingsPage[] = [
  {
    id: "general",
    title: "General",
    icon: SlidersHorizontalIcon,
    group: "Application",
    keywords: ["startup", "start", "login", "sign in", "boot", "launch", "tray", "menu bar", "notification area", "background", "close", "quit", "sleep", "awake", "power"],
    component: GeneralSettings,
  },
  {
    id: "appearance",
    title: "Appearance",
    icon: PaletteIcon,
    group: "Application",
    keywords: ["theme", "dark", "light", "color", "accent", "font", "typography", "size", "zoom", "motion", "animation", "width"],
    component: AppearanceSettings,
  },
  {
    id: "providers",
    title: "Providers",
    icon: KeyRoundIcon,
    group: "Application",
    keywords: ["provider", "api key", "key", "model", "models", "connect", "openai", "anthropic", "claude", "gemini", "openrouter", "deepseek", "ollama", "base url"],
    component: ProviderSettings,
  },
  {
    id: "office",
    title: "Office",
    icon: FileTextIcon,
    group: "Application",
    keywords: ["word", "docx", "powerpoint", "pptx", "excel", "xlsx", "document", "libreoffice", "preview", "render", "pdf", "install"],
    component: OfficeSettings,
  },
  {
    id: "engine",
    title: "Engine",
    icon: CpuIcon,
    group: "System",
    keywords: ["restart", "log", "status", "models", "diagnostics"],
    component: EngineSettings,
  },
  {
    id: "sandbox",
    title: "Sandbox",
    icon: ShieldCheckIcon,
    group: "System",
    keywords: ["security", "process", "environment", "env", "variables", "profile", "bashrc", "shell", "timeout", "output", "limit", "deny", "denied", "patterns", ".env", "secrets", "permissions"],
    component: SandboxSettings,
  },
  {
    id: "logs",
    title: "Data & logs",
    icon: ScrollTextIcon,
    group: "System",
    keywords: ["log", "logs", "debug", "database", "sqlite", "data", "export", "storage", "folder", "errors"],
    component: LogsSettings,
  },
  {
    id: "about",
    title: "About",
    icon: InfoIcon,
    group: "System",
    keywords: ["version", "help", "docs", "issue", "github", "license"],
    component: AboutSettings,
  },
];

export const settingsGroups = ["Application", "System"] as const;

export function matchesQuery(page: SettingsPage, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [page.title, ...page.keywords].some((word) => word.toLowerCase().includes(q));
}
