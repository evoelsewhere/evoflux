/* Apply the last validated appearance before Side Chat's first paint. */
(() => {
  const STORAGE_KEY = "webbridgePrepaintAppearanceV1";
  const choices = {
    theme: new Set(["system", "light", "dark"]),
    accent: new Set(["default", "blue", "green", "orange", "pink", "purple", "red"]),
    font: new Set(["system", "inter", "mono", "geist", "anthropic-sans"]),
    motion: new Set(["reduced", "subtle", "standard", "expressive", "cinematic"]),
  };
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (!value || value.schema_version !== 1) return;
    if (!Object.entries(choices).every(([key, allowed]) => allowed.has(value[key]))) return;
    if (!Number.isFinite(value.font_scale) || value.font_scale < 0.9 || value.font_scale > 1.2) return;
    if (!Number.isFinite(value.motion_scale) || value.motion_scale < 0 || value.motion_scale > 2) return;

    const root = document.documentElement;
    if (value.theme === "system") delete root.dataset.theme;
    else root.dataset.theme = value.theme;
    if (value.accent === "default") delete root.dataset.accent;
    else root.dataset.accent = value.accent;
    if (value.font === "system") delete root.dataset.font;
    else root.dataset.font = value.font;
    root.dataset.motion = value.motion;
    root.style.setProperty("--ui-font-size", `${13 * value.font_scale}px`);
    root.style.setProperty("--motion-scale", String(value.motion_scale));
  } catch {
    // Invalid or unavailable local storage falls back to the CSS system theme.
  }
})();
