/**
 * useMonacoTheme — defines and applies an EvoFlux Monaco theme that reads
 * the app's CSS custom properties so the editor blends with the current
 * light/dark mode without any hardcoded colours.
 */
import { useEffect, useRef } from 'react'
import type { Monaco } from '@monaco-editor/react'

const DARK_THEME = 'evoflux-dark'
const LIGHT_THEME = 'evoflux-light'

/** Read a CSS custom property from :root. */
function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function resolveMonacoTokenHex(value: string): string | null {
  const color = value.trim()
  const hex = color.replace(/^#/, '')
  if (/^[0-9a-f]{3}$/i.test(hex)) {
    return [...hex].map((digit) => digit.repeat(2)).join('').toUpperCase()
  }
  if (/^[0-9a-f]{6}$/i.test(hex)) return hex.toUpperCase()

  if (typeof document === 'undefined') return null
  const context = document.createElement('canvas').getContext('2d')
  if (!context) return null

  // Invalid assignments leave fillStyle unchanged. Two different sentinels
  // distinguish that case without relying on a browser-specific color parser.
  context.fillStyle = '#010203'
  context.fillStyle = color
  const first = context.fillStyle
  context.fillStyle = '#040506'
  context.fillStyle = color
  if (context.fillStyle !== first) return null

  context.clearRect(0, 0, 1, 1)
  context.fillStyle = color
  context.fillRect(0, 0, 1, 1)
  const [red, green, blue] = context.getImageData(0, 0, 1, 1).data
  return [red, green, blue]
    .map((channel) => channel.toString(16).padStart(2, '0'))
    .join('')
    .toUpperCase()
}

export function toMonacoTokenHex(value: string, fallback: string): string {
  return resolveMonacoTokenHex(value) ?? resolveMonacoTokenHex(fallback) ?? 'FFFFFF'
}

function tokenColor(cssVariable: string, fallback: string): string {
  return toMonacoTokenHex(cssVar(cssVariable), fallback)
}

function defineDarkTheme(monaco: Monaco) {
  monaco.editor.defineTheme(DARK_THEME, {
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
      'editor.background': cssVar('--bg-card'),
      'editor.foreground': cssVar('--color-text-2'),
      'editorLineNumber.foreground': cssVar('--color-text-subtle'),
      'editorLineNumber.activeForeground': cssVar('--color-text-muted'),
      'editor.selectionBackground': cssVar('--color-accent') + '26',
      'editor.lineHighlightBackground': cssVar('--bg-key') + '80',
      'editorCursor.foreground': cssVar('--color-text'),
      'editorWidget.background': cssVar('--bg-card'),
      'editorWidget.border': cssVar('--color-border'),
      'input.background': cssVar('--bg-input'),
      'input.border': cssVar('--color-border'),
      'input.foreground': cssVar('--color-text'),
      'scrollbarSlider.background': cssVar('--color-border') + '40',
      'scrollbarSlider.hoverBackground': cssVar('--color-border') + '80',
      'scrollbarSlider.activeBackground': cssVar('--color-border') + 'AA',
      'editorGutter.background': cssVar('--bg-card'),
      'minimap.background': cssVar('--bg-card'),
    },
  })
}

function defineLightTheme(monaco: Monaco) {
  monaco.editor.defineTheme(LIGHT_THEME, {
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
      'editor.background': cssVar('--bg-card'),
      'editor.foreground': cssVar('--color-text-2'),
      'editorLineNumber.foreground': cssVar('--color-text-subtle'),
      'editorLineNumber.activeForeground': cssVar('--color-text-muted'),
      'editor.selectionBackground': cssVar('--color-accent') + '26',
      'editor.lineHighlightBackground': cssVar('--bg-key') + '80',
      'editorCursor.foreground': cssVar('--color-text'),
      'editorWidget.background': cssVar('--bg-card'),
      'editorWidget.border': cssVar('--color-border'),
      'input.background': cssVar('--bg-input'),
      'input.border': cssVar('--color-border'),
      'input.foreground': cssVar('--color-text'),
      'scrollbarSlider.background': cssVar('--color-border') + '40',
      'scrollbarSlider.hoverBackground': cssVar('--color-border') + '80',
      'scrollbarSlider.activeBackground': cssVar('--color-border') + 'AA',
      'editorGutter.background': cssVar('--bg-card'),
      'minimap.background': cssVar('--bg-card'),
    },
  })
}

export function useMonacoTheme(monaco: Monaco | null) {
  const defined = useRef(false)

  useEffect(() => {
    if (!monaco) return
    const isDark = document.documentElement.classList.contains('dark')

    // (Re)define both themes whenever the resolved theme changes
    defineDarkTheme(monaco)
    defineLightTheme(monaco)
    defined.current = true

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
    ts: 'typescript', tsx: 'typescript', mts: 'typescript',
    js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript',
    py: 'python', pyi: 'python',
    rs: 'rust',
    go: 'go',
    java: 'java',
    kt: 'kotlin', kts: 'kotlin',
    c: 'c', h: 'c',
    cpp: 'cpp', cxx: 'cpp', cc: 'cpp', hpp: 'cpp',
    rb: 'ruby',
    php: 'php',
    swift: 'swift',
    cs: 'csharp',
    json: 'json', jsonl: 'json',
    yaml: 'yaml', yml: 'yaml',
    toml: 'ini', ini: 'ini',
    html: 'html', htm: 'html',
    css: 'css', scss: 'scss', sass: 'scss', less: 'less',
    md: 'markdown', markdown: 'markdown',
    xml: 'xml', svg: 'xml',
    sql: 'sql',
    sh: 'shell', bash: 'shell', zsh: 'shell', fish: 'shell',
    dockerfile: 'dockerfile',
    graphql: 'graphql', gql: 'graphql',
    lua: 'lua',
    r: 'r',
    dart: 'dart',
    vue: 'html',
    makefile: 'shell',
    env: 'ini',
    gitignore: 'ini',
    txt: 'plaintext', log: 'plaintext', csv: 'plaintext', tsv: 'plaintext', rst: 'plaintext',
  }
  return map[ext.toLowerCase()] ?? 'plaintext'
}
