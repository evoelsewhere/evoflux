import type * as React from "react";
import {
  BrowserIcon,
  FilesIcon,
  MemoryIcon,
  SideChatIcon,
  TerminalIcon,
} from "@/components/icons/tool-icons";
import type { PanelId } from "@/stores/ui-store";

export interface PanelDefinition {
  id: PanelId;
  title: string;
  description: string;
  icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  /** Key pressed with the primary modifier. */
  shortcut: string;
}

/** Tools that open in the side panel. Add a panel by adding an entry here. */
export const panels: PanelDefinition[] = [
  { id: "terminal", title: "Terminal", description: "Run commands in the active workspace", icon: TerminalIcon, shortcut: "`" },
  { id: "browser", title: "Browser", description: "View and interact with the agent browser", icon: BrowserIcon, shortcut: "T" },
  { id: "files", title: "Files", description: "Browse workspace files and generated artifacts", icon: FilesIcon, shortcut: "F" },
  { id: "side-chat", title: "Side chat", description: "Ask a focused question without interrupting the run", icon: SideChatIcon, shortcut: ";" },
  { id: "memory", title: "Memory", description: "What the agent remembers across chats", icon: MemoryIcon, shortcut: "M" },
];

export const panelById = (id: PanelId | null) => panels.find((panel) => panel.id === id);
