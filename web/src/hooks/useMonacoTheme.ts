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

function defineDarkTheme(monaco: Monaco) {
  monaco.editor.defineTheme(DARK_THEME, {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: cssVar('--color-syn-comment').replace('#', '') },
      { token: 'keyword', foreground: cssVar('--color-syn-keyword').replace('#', '') },
      { token: 'string', foreground: cssVar('--color-syn-string').replace('#', '') },
      { token: 'number', foreground: cssVar('--color-syn-number').replace('#', '') },
      { token: 'type', foreground: cssVar('--color-syn-type').replace('#', '') },
      { token: 'variable', foreground: cssVar('--color-syn-variable').replace('#', '') },
      { token: 'function', foreground: cssVar('--color-syn-function').replace('#', '') },
      { token: 'operator', foreground: cssVar('--color-syn-operator').replace('#', '') },
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
      { token: 'comment', foreground: cssVar('--color-syn-comment').replace('#', '') },
      { token: 'keyword', foreground: cssVar('--color-syn-keyword').replace('#', '') },
      { token: 'string', foreground: cssVar('--color-syn-string').replace('#', '') },
      { token: 'number', foreground: cssVar('--color-syn-number').replace('#', '') },
      { token: 'type', foreground: cssVar('--color-syn-type').replace('#', '') },
      { token: 'variable', foreground: cssVar('--color-syn-variable').replace('#', '') },
      { token: 'function', foreground: cssVar('--color-syn-function').replace('#', '') },
      { token: 'operator', foreground: cssVar('--color-syn-operator').replace('#', '') },
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
