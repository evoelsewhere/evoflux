// Widgets: the document a `show_widget` widget runs in
// (docs/features/office-v3-parity/spec.md, FR-13). Run with `bun test` in apps/desktop.

import { describe, expect, test } from "bun:test";
import {
  buildWidgetCsp,
  buildWidgetThemeCss,
  clampWidgetHeight,
  readWidgetTheme,
  wrapWidgetHtml,
} from "../src/lib/widget-document";

const tokens: Record<string, string> = {
  "--brand": "#0072f5",
  "--background": "#fafafa",
  "--card": "#ffffff",
  "--foreground": "#171717",
  "--border": "#00000014",
};
const style = { getPropertyValue: (name: string) => tokens[name] ?? "" };

describe("widget document", () => {
  test("keeps the v3 policy: CDN allowlist only, no network", () => {
    const csp = buildWidgetCsp();
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain("script-src 'self' blob: data: cdnjs.cloudflare.com cdn.jsdelivr.net unpkg.com esm.sh 'unsafe-inline' 'unsafe-eval'");
    expect(csp).toContain("connect-src 'self'");
    expect(csp).toContain("object-src 'none'");
  });

  test("maps the app's tokens to the v3 widget variables", () => {
    const theme = readWidgetTheme(style);
    expect(theme["--color-accent"]).toBe("#0072f5");
    expect(theme["--bg-card"]).toBe("#ffffff");
    expect(theme["--color-text"]).toBe("#171717");
    expect(theme["--accent-green"]).toBe("#45a557");
    // Missing tokens are left out rather than written empty.
    expect("--bg-muted" in theme).toBe(false);
    expect(buildWidgetThemeCss({ "--color-text": "#111" })).toBe(":root { --color-text: #111; }");
    expect(buildWidgetThemeCss({})).toBe("");
  });

  test("wraps a fragment and injects into an existing head first", () => {
    const fragment = wrapWidgetHtml("<div id=x></div>", readWidgetTheme(style), "dark");
    expect(fragment.startsWith("<!doctype html><html><head><meta charset=\"utf-8\"><meta http-equiv=\"Content-Security-Policy\"")).toBe(true);
    expect(fragment).toContain("color-scheme: dark");
    expect(fragment).toContain("window.sendPrompt");
    expect(fragment).toContain("widget_resize");
    expect(fragment).toContain("<body><div id=x></div></body>");

    const full = wrapWidgetHtml('<html><head lang="en"><script>alert(1)</script></head><body></body></html>', {});
    const head = full.indexOf('<head lang="en">') + '<head lang="en">'.length;
    expect(full.slice(head).startsWith("<meta http-equiv=\"Content-Security-Policy\"")).toBe(true);
    expect(full.indexOf("Content-Security-Policy")).toBeLessThan(full.indexOf("alert(1)"));
  });

  test("a theme value cannot close the style element", () => {
    const html = wrapWidgetHtml("", { "--font-sans": "x</style><script>bad()</script>" });
    expect(html).not.toContain("</style><script>bad()");
  });

  test("heights stay within 120–2400 px", () => {
    expect(clampWidgetHeight(10)).toBe(120);
    expect(clampWidgetHeight(500)).toBe(500);
    expect(clampWidgetHeight(99999)).toBe(2400);
  });
});
