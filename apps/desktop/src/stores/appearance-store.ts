// Appearance preferences: accent, fonts, chat width and motion. The colour
// scheme lives in ThemeProvider and the interface size is the window zoom
// (ui-store); everything here is applied as attributes and CSS variables on
// <html>, so no component has to subscribe to it.

import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface Accent {
  id: string;
  label: string;
  /** On light surfaces. */
  light: string;
  /** On dark surfaces: a lighter step of the same hue. */
  dark: string;
}

/** Blue is the design language's one interactive colour (DESIGN.md §2); the rest are opt-in. */
export const ACCENTS: Accent[] = [
  { id: "blue", label: "Blue", light: "#0072f5", dark: "#3291ff" },
  { id: "cyan", label: "Cyan", light: "#0b8fb3", dark: "#3ec5e0" },
  { id: "teal", label: "Teal", light: "#067a6e", dark: "#45dec5" },
  { id: "green", label: "Green", light: "#398e4a", dark: "#6cda75" },
  { id: "amber", label: "Amber", light: "#c27803", dark: "#ffb224" },
  { id: "clay", label: "Clay", light: "#c96442", dark: "#e08a6d" },
  { id: "red", label: "Red", light: "#d93036", dark: "#ff6369" },
  { id: "pink", label: "Pink", light: "#d6246e", dark: "#f472b6" },
  { id: "purple", label: "Purple", light: "#7820bc", dark: "#bf89ec" },
  { id: "graphite", label: "Graphite", light: "#171717", dark: "#ededed" },
];

export const CUSTOM_ACCENT = "custom";

export interface FontOption {
  id: string;
  label: string;
  description: string;
  stack: string;
}

export const INTERFACE_FONTS: FontOption[] = [
  {
    id: "geist",
    label: "Geist",
    description: "Compact, made for developer tools",
    stack: '"Geist Variable", ui-sans-serif, system-ui, sans-serif',
  },
  {
    id: "system",
    label: "System UI",
    description: "Native to your operating system",
    stack: 'system-ui, -apple-system, "Segoe UI Variable Text", "Segoe UI", Roboto, sans-serif',
  },
  {
    id: "mono",
    label: "Geist Mono",
    description: "Monospaced across the interface",
    stack: '"Geist Mono Variable", ui-monospace, SFMono-Regular, monospace',
  },
];

export const CODE_FONTS: FontOption[] = [
  {
    id: "geist-mono",
    label: "Geist Mono",
    description: "Pairs with the interface",
    stack: '"Geist Mono Variable", ui-monospace, SFMono-Regular, "Roboto Mono", monospace',
  },
  {
    id: "system-mono",
    label: "System mono",
    description: "Cascadia, SF Mono or Menlo",
    stack: 'ui-monospace, "Cascadia Code", "Cascadia Mono", SFMono-Regular, Menlo, Consolas, monospace',
  },
];

export type ChatWidth = "narrow" | "default" | "wide" | "full";
export const CHAT_WIDTHS: { id: ChatWidth; label: string; value: string }[] = [
  { id: "narrow", label: "Narrow", value: "40rem" },
  { id: "default", label: "Default", value: "50rem" },
  { id: "wide", label: "Wide", value: "64rem" },
  { id: "full", label: "Full", value: "100%" },
];

/** The chat column's width in px for a setting, inside `available` px. */
export function chatColumnPx(width: ChatWidth, available: number): number {
  const value = (CHAT_WIDTHS.find((w) => w.id === width) ?? CHAT_WIDTHS[1]).value;
  if (!value.endsWith("rem")) return available;
  const rootPx = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  return Math.min(parseFloat(value) * rootPx, available);
}

export type MotionPreference = "system" | "reduced" | "full";

interface AppearanceStore {
  /** An `ACCENTS` id or `CUSTOM_ACCENT`. */
  accent: string;
  /** Hex colour used when `accent` is custom. */
  customAccent: string;
  interfaceFont: string;
  codeFont: string;
  chatWidth: ChatWidth;
  motion: MotionPreference;
  setAccent(id: string): void;
  setCustomAccent(hex: string): void;
  setInterfaceFont(id: string): void;
  setCodeFont(id: string): void;
  setChatWidth(width: ChatWidth): void;
  setMotion(motion: MotionPreference): void;
  reset(): void;
}

export const APPEARANCE_DEFAULTS = {
  accent: "blue",
  customAccent: "#8b5cf6",
  interfaceFont: "geist",
  codeFont: "geist-mono",
  chatWidth: "default" as ChatWidth,
  motion: "system" as MotionPreference,
};

export const useAppearanceStore = create<AppearanceStore>()(
  persist(
    (set) => ({
      ...APPEARANCE_DEFAULTS,
      setAccent: (accent) => set({ accent }),
      setCustomAccent: (customAccent) => set({ customAccent, accent: CUSTOM_ACCENT }),
      setInterfaceFont: (interfaceFont) => set({ interfaceFont }),
      setCodeFont: (codeFont) => set({ codeFont }),
      setChatWidth: (chatWidth) => set({ chatWidth }),
      setMotion: (motion) => set({ motion }),
      reset: () => set(APPEARANCE_DEFAULTS),
    }),
    {
      name: "evo.appearance",
      partialize: ({ accent, customAccent, interfaceFont, codeFont, chatWidth, motion }) => ({
        accent,
        customAccent,
        interfaceFont,
        codeFont,
        chatWidth,
        motion,
      }),
    },
  ),
);

/** Black or white, whichever reads better on `hex`. */
function contrastOn(hex: string): string {
  const value = hex.replace("#", "");
  const full = value.length === 3 ? [...value].map((c) => c + c).join("") : value;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return luminance > 0.4 ? "#0a0a0a" : "#ffffff";
}

export function accentColors(state: Pick<AppearanceStore, "accent" | "customAccent">): { light: string; dark: string } {
  if (state.accent === CUSTOM_ACCENT) return { light: state.customAccent, dark: state.customAccent };
  const accent = ACCENTS.find((a) => a.id === state.accent) ?? ACCENTS[0];
  return { light: accent.light, dark: accent.dark };
}

function apply(state: AppearanceStore) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  const { light, dark } = accentColors(state);
  root.style.setProperty("--brand-light", light);
  root.style.setProperty("--brand-dark", dark);
  root.style.setProperty("--brand-light-foreground", contrastOn(light));
  root.style.setProperty("--brand-dark-foreground", contrastOn(dark));
  const sans = INTERFACE_FONTS.find((f) => f.id === state.interfaceFont) ?? INTERFACE_FONTS[0];
  const mono = CODE_FONTS.find((f) => f.id === state.codeFont) ?? CODE_FONTS[0];
  root.style.setProperty("--app-font-sans", sans.stack);
  root.style.setProperty("--app-font-mono", mono.stack);
  const width = CHAT_WIDTHS.find((w) => w.id === state.chatWidth) ?? CHAT_WIDTHS[1];
  root.style.setProperty("--chat-width", width.value);
  root.setAttribute("data-motion", state.motion);
}

// Apply the stored choice before the first paint, then on every change.
apply(useAppearanceStore.getState());
useAppearanceStore.subscribe(apply);
