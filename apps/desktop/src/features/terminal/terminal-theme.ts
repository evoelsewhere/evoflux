// xterm.js colours and font from the app's theme and appearance settings.

import type { ITerminalOptions, ITheme } from "@xterm/xterm";

/** ANSI colours tuned to the Geist palette (DESIGN.md), per scheme. */
const ANSI_DARK: ITheme = {
  black: "#1f1f1f",
  red: "#ff6369",
  green: "#62c073",
  yellow: "#ffb224",
  blue: "#52a8ff",
  magenta: "#bf7af0",
  cyan: "#3ec5e0",
  white: "#a1a1a1",
  brightBlack: "#707070",
  brightRed: "#ff8589",
  brightGreen: "#86e094",
  brightYellow: "#ffcd5c",
  brightBlue: "#7cbcff",
  brightMagenta: "#d3a1f7",
  brightCyan: "#6fd8eb",
  brightWhite: "#ededed",
};

const ANSI_LIGHT: ITheme = {
  black: "#171717",
  red: "#d93036",
  green: "#297a3a",
  yellow: "#a35200",
  blue: "#0068d6",
  magenta: "#7d00cc",
  cyan: "#0b7f9e",
  white: "#8f8f8f",
  brightBlack: "#666666",
  brightRed: "#e5484d",
  brightGreen: "#398e4a",
  brightYellow: "#c27803",
  brightBlue: "#0072f5",
  brightMagenta: "#8e4ec6",
  brightCyan: "#0e9bbf",
  brightWhite: "#a8a8a8",
};

export const isDark = () => document.documentElement.classList.contains("dark");

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** `#rgb` / `#rrggbb` with an alpha byte; other formats pass through unchanged. */
function withAlpha(color: string, alpha: number): string {
  const hex = color.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)?.[1];
  if (!hex) return color;
  const full = hex.length === 3 ? [...hex].map((c) => c + c).join("") : hex;
  return `#${full}${Math.round(alpha * 255)
    .toString(16)
    .padStart(2, "0")}`;
}

export function terminalTheme(): ITheme {
  const dark = isDark();
  const foreground = cssVar("--foreground", dark ? "#ededed" : "#171717");
  const accent = cssVar(dark ? "--brand-dark" : "--brand-light", dark ? "#3291ff" : "#0072f5");
  return {
    ...(dark ? ANSI_DARK : ANSI_LIGHT),
    // The panel's own colour, opaque: `minimumContrastRatio` measures text
    // against this, and a transparent background counts as black there, so
    // dark text on the light theme was lightened to grey.
    background: cssVar("--background", dark ? "#191919" : "#fafafa"),
    foreground,
    cursor: foreground,
    cursorAccent: dark ? "#191919" : "#ffffff",
    selectionBackground: withAlpha(accent, dark ? 0.35 : 0.25),
    selectionInactiveBackground: withAlpha(dark ? "#ffffff" : "#000000", 0.12),
    scrollbarSliderBackground: withAlpha(dark ? "#ffffff" : "#000000", 0.12),
    scrollbarSliderHoverBackground: withAlpha(dark ? "#ffffff" : "#000000", 0.22),
    scrollbarSliderActiveBackground: withAlpha(dark ? "#ffffff" : "#000000", 0.34),
  };
}

/** The code font chosen in Settings → Appearance. */
export const terminalFont = () =>
  cssVar("--app-font-mono", '"Geist Mono Variable", ui-monospace, "Cascadia Mono", Menlo, Consolas, monospace');

/** Options that follow the theme and appearance; applied again when they change. */
export function themedOptions(): Pick<ITerminalOptions, "theme" | "fontFamily" | "minimumContrastRatio"> {
  return {
    theme: terminalTheme(),
    fontFamily: terminalFont(),
    // Light backgrounds make some ANSI colours (white, yellow) hard to read.
    minimumContrastRatio: isDark() ? 1 : 4.5,
  };
}

/** Wait for the code font so xterm measures its cells with it. */
export async function loadTerminalFont(): Promise<void> {
  const family = terminalFont().split(",")[0]?.trim();
  if (!family || !document.fonts) return;
  await Promise.race([
    document.fonts.load(`13px ${family}`).catch(() => undefined),
    new Promise((resolve) => setTimeout(resolve, 1500)),
  ]);
}
