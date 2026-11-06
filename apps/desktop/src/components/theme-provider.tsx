import * as React from "react";
import { invoke } from "@tauri-apps/api/core";

export type Theme = "light" | "dark" | "system";

interface ThemeContextValue {
  theme: Theme;
  resolved: "light" | "dark";
  setTheme(theme: Theme): void;
}

const ThemeContext = React.createContext<ThemeContextValue | null>(null);
const STORAGE_KEY = "evo.theme";

function readStored(): Theme {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === "light" || value === "dark" || value === "system") return value;
  } catch {
    // Storage can be unavailable; fall back to the system theme.
  }
  return "system";
}

function systemDark() {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = React.useState<Theme>(readStored);
  const [dark, setDark] = React.useState(() => (theme === "system" ? systemDark() : theme === "dark"));

  React.useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setDark(theme === "system" ? media.matches : theme === "dark");
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [theme]);

  React.useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
    // Keep the Mica tint in step with the app theme (no-op elsewhere).
    invoke("window_set_theme", { dark }).catch(() => undefined);
  }, [dark]);

  const setTheme = React.useCallback((next: Theme) => {
    setThemeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Ignore: the choice still applies for this run.
    }
  }, []);

  const value = React.useMemo(
    () => ({ theme, resolved: dark ? ("dark" as const) : ("light" as const), setTheme }),
    [theme, dark, setTheme],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = React.useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside ThemeProvider");
  return context;
}
