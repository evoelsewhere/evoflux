/**
 * useMonacoTheme — defines and applies an EvoFlux Monaco theme that reads
 * the app's CSS custom properties so the editor blends with the current
 * light/dark mode without any hardcoded colours.
 */
import { useEffect } from 'react'
import type { Monaco } from '@monaco-editor/react'
import type { editor as MonacoEditor } from 'monaco-editor'

const DARK_THEME = 'evoflux-dark'
const LIGHT_THEME = 'evoflux-light'
type MonacoThemeData = MonacoEditor.IStandaloneThemeData

/** Read a CSS custom property from :root. */
function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/**
 * Monaco token rules only accept 6/8-digit hex values. CSS accepts shorter
 * forms such as #fff, so normalize at the editor boundary instead of relying
 * on the browser's color parser (which differs between WebKit and Chromium).
 */
function normalizeHex(value: string): string | null {
  const hex = value.trim().replace(/^#/, '')
  if (/^[0-9a-f]{3,4}$/i.test(hex)) {
    return [...hex].map((digit) => digit.repeat(2)).join('').toUpperCase()
  }
  if (/^[0-9a-f]{6}([0-9a-f]{2})?$/i.test(hex)) return hex.toUpperCase()
  return null
}

export function toMonacoTokenHex(value: string, fallback: string): string {
  return (normalizeHex(value) ?? normalizeHex(fallback) ?? 'FFFFFF').slice(0, 6)
}

export function toMonacoThemeColor(
  value: string,
  fallback: string,
  alpha?: string,
): string {
  const resolved = normalizeHex(value) ?? normalizeHex(fallback) ?? 'FFFFFF'
  const opacity = alpha && /^[0-9a-f]{2}$/i.test(alpha)
    ? alpha.toUpperCase()
    : resolved.slice(6, 8)
  return `#${resolved.slice(0, 6)}${opacity ?? ''}`
}

function tokenColor(cssVariable: string, fallback: string): string {
  return toMonacoTokenHex(cssVar(cssVariable), fallback)
}

function themeColor(cssVariable: string, fallback: string, alpha?: string): string {
  return toMonacoThemeColor(cssVar(cssVariable), fallback, alpha)
}

/**
 * Final defensive boundary before Monaco sees the theme. This also protects
 * against future rules being added with CSS-valid but Monaco-invalid #rgb
 * colors, which otherwise throw and take down the entire React surface.
 */
export function sanitizeMonacoTheme(theme: MonacoThemeData): MonacoThemeData {
  const tokenFallback = theme.base === 'vs-dark' ? 'FFFFFF' : '000000'
  const uiFallback = theme.base === 'vs-dark' ? '#1E1E1E' : '#FFFFFF'

  return {
    ...theme,
    rules: theme.rules.map((rule) => ({
      ...rule,
      ...(rule.foreground
        ? { foreground: toMonacoTokenHex(rule.foreground, tokenFallback) }
        : {}),
      ...(rule.background
        ? { background: toMonacoTokenHex(rule.background, tokenFallback) }
        : {}),
    })),
    colors: Object.fromEntries(
      Object.entries(theme.colors).map(([name, color]) => [
        name,
        toMonacoThemeColor(color, uiFallback),
      ]),
    ),
  }
}

function defineThemeSafely(monaco: Monaco, name: string, theme: MonacoThemeData) {
  try {
    monaco.editor.defineTheme(name, sanitizeMonacoTheme(theme))
  } catch (error) {
    // A malformed custom theme must never crash the desktop app. Keep the
    // custom name defined with Monaco's built-in palette as a safe fallback.
    console.error(`[Monaco] Failed to define ${name}; using built-in colors`, error)
    monaco.editor.defineTheme(name, {
      base: theme.base,
      inherit: true,
      rules: [],
      colors: {},
    })
  }
}

function defineDarkTheme(monaco: Monaco) {
  defineThemeSafely(monaco, DARK_THEME, {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: tokenColor('--color-syn-comment', '7B828A') },
      { token: 'keyword', foreground: tokenColor('--color-syn-keyword', 'FF7B72') },
      { token: 'string', foreground: tokenColor('--color-syn-string', 'A5D6FF') },
      { token: 'number', foreground: tokenColor('--color-syn-number', '79C0FF') },
      { token: 'type', foreground: tokenColor('--color-syn-type', '7EE787') },
      { token: 'variable', foreground: tokenColor('--color-syn-variable', 'FFA657') },
      { token: 'function', foreground: tokenColor('--color-syn-function', 'D2A8FF') },
      { token: 'operator', foreground: tokenColor('--color-syn-operator', '8B949E') },
    ],
    colors: {
      'editor.background': themeColor('--bg-card', '#242423'),
      'editor.foreground': themeColor('--color-text-2', '#DDDCD8'),
      'editorLineNumber.foreground': themeColor('--color-text-subtle', '#85827F'),
      'editorLineNumber.activeForeground': themeColor('--color-text-muted', '#AAA8A2'),
      'editor.selectionBackground': themeColor('--color-accent', '#9AA0BF', '26'),
      'editor.lineHighlightBackground': themeColor('--bg-key', '#2C2C2A', '80'),
      'editorCursor.foreground': themeColor('--color-text', '#F3F2EF'),
      'editorWidget.background': themeColor('--bg-card', '#242423'),
      'editorWidget.border': themeColor('--color-border', '#3C3C39'),
      'input.background': themeColor('--bg-input', '#20201F'),
      'input.border': themeColor('--color-border', '#3C3C39'),
      'input.foreground': themeColor('--color-text', '#F3F2EF'),
      'scrollbarSlider.background': themeColor('--color-border', '#3C3C39', '40'),
      'scrollbarSlider.hoverBackground': themeColor('--color-border', '#3C3C39', '80'),
      'scrollbarSlider.activeBackground': themeColor('--color-border', '#3C3C39', 'AA'),
      'editorGutter.background': themeColor('--bg-card', '#242423'),
      'minimap.background': themeColor('--bg-card', '#242423'),
    },
  })
}

function defineLightTheme(monaco: Monaco) {
  defineThemeSafely(monaco, LIGHT_THEME, {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'comment', foreground: tokenColor('--color-syn-comment', '6B7280') },
      { token: 'keyword', foreground: tokenColor('--color-syn-keyword', 'CF222E') },
      { token: 'string', foreground: tokenColor('--color-syn-string', '0A3069') },
      { token: 'number', foreground: tokenColor('--color-syn-number', '0550AE') },
      { token: 'type', foreground: tokenColor('--color-syn-type', '116329') },
      { token: 'variable', foreground: tokenColor('--color-syn-variable', '953800') },
      { token: 'function', foreground: tokenColor('--color-syn-function', '8250DF') },
      { token: 'operator', foreground: tokenColor('--color-syn-operator', '737373') },
    ],
    colors: {
      'editor.background': themeColor('--bg-card', '#FFFFFF'),
      'editor.foreground': themeColor('--color-text-2', '#343A46'),
      'editorLineNumber.foreground': themeColor('--color-text-subtle', '#697381'),
      'editorLineNumber.activeForeground': themeColor('--color-text-muted', '#5C6675'),
      'editor.selectionBackground': themeColor('--color-accent', '#4C66D6', '26'),
      'editor.lineHighlightBackground': themeColor('--bg-key', '#ECEFF5', '80'),
      'editorCursor.foreground': themeColor('--color-text', '#171A21'),
      'editorWidget.background': themeColor('--bg-card', '#FFFFFF'),
      'editorWidget.border': themeColor('--color-border', '#D8DDE6'),
      'input.background': themeColor('--bg-input', '#FFFFFF'),
      'input.border': themeColor('--color-border', '#D8DDE6'),
      'input.foreground': themeColor('--color-text', '#171A21'),
      'scrollbarSlider.background': themeColor('--color-border', '#D8DDE6', '40'),
      'scrollbarSlider.hoverBackground': themeColor('--color-border', '#D8DDE6', '80'),
      'scrollbarSlider.activeBackground': themeColor('--color-border', '#D8DDE6', 'AA'),
      'editorGutter.background': themeColor('--bg-card', '#FFFFFF'),
      'minimap.background': themeColor('--bg-card', '#FFFFFF'),
    },
  })
}

export function useMonacoTheme(monaco: Monaco | null) {
  useEffect(() => {
    if (!monaco) return
    const isDark = document.documentElement.classList.contains('dark')

    // (Re)define both themes whenever the resolved theme changes
    defineDarkTheme(monaco)
    defineLightTheme(monaco)

    monaco.editor.setTheme(isDark ? DARK_THEME : LIGHT_THEME)

    // Watch for theme class changes on <html>
    const observer = new MutationObserver(() => {
      const dark = document.documentElement.classList.contains('dark')
      // Re-read CSS vars after theme toggle
      defineDarkTheme(monaco)
      defineLightTheme(monaco)
      monaco.editor.setTheme(dark ? DARK_THEME : LIGHT_THEME)
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })

    return () => observer.disconnect()
  }, [monaco])

  return document.documentElement.classList.contains('dark') ? DARK_THEME : LIGHT_THEME
}

/** Map file extension to a Monaco language identifier. */
export function languageForExt(ext: string): string {
  const map: Record<string, string> = {
    ts: 'typescript', tsx: 'typescript', mts: 'typescript', cts: 'typescript',
    js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript',
    py: 'python', pyi: 'python', pyw: 'python',
    rs: 'rust',
    go: 'go',
    java: 'java',
    kt: 'kotlin', kts: 'kotlin',
    c: 'c', h: 'c', m: 'c',
    cpp: 'cpp', cxx: 'cpp', cc: 'cpp', hpp: 'cpp', hh: 'cpp', hxx: 'cpp', mm: 'cpp',
    rb: 'ruby',
    php: 'php',
    swift: 'swift',
    cs: 'csharp',
    json: 'json', jsonc: 'json', jsonl: 'json',
    yaml: 'yaml', yml: 'yaml',
    toml: 'ini', ini: 'ini',
    html: 'html', htm: 'html',
    css: 'css', scss: 'scss', sass: 'scss', less: 'less',
    md: 'markdown', markdown: 'markdown', mdx: 'markdown',
    xml: 'xml', svg: 'xml',
    sql: 'sql',
    sh: 'shell', bash: 'shell', zsh: 'shell', fish: 'shell',
    dockerfile: 'dockerfile',
    graphql: 'graphql', gql: 'graphql',
    lua: 'lua',
    r: 'r',
    dart: 'dart',
    vue: 'html', svelte: 'svelte',
    makefile: 'shell',
    env: 'ini',
    gitignore: 'ini',
    txt: 'plaintext', log: 'plaintext', csv: 'plaintext', tsv: 'plaintext', rst: 'plaintext',
  }
  return map[ext.toLowerCase()] ?? 'plaintext'
}
