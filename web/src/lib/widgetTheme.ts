const WIDGET_THEME_PROPERTIES = [
  '--bg-page',
  '--bg-card',
  '--bg-key',
  '--bg-muted',
  '--color-text',
  '--color-text-2',
  '--color-text-muted',
  '--color-text-subtle',
  '--color-text-on-accent',
  '--color-border',
  '--color-border-strong',
  '--color-accent',
  '--color-accent-soft',
  '--accent-blue',
  '--accent-blue-soft',
  '--accent-blue-text',
  '--accent-green',
  '--accent-green-soft',
  '--accent-green-text',
  '--accent-amber',
  '--accent-amber-soft',
  '--accent-red',
  '--accent-red-soft',
  '--font-sans',
] as const

export type WidgetTheme = Partial<Record<(typeof WIDGET_THEME_PROPERTIES)[number], string>>

export function readWidgetTheme(style: Pick<CSSStyleDeclaration, 'getPropertyValue'>): WidgetTheme {
  const theme: WidgetTheme = {}
  for (const property of WIDGET_THEME_PROPERTIES) {
    const value = style.getPropertyValue(property).trim()
    if (value) theme[property] = value
  }
  return theme
}

export function buildWidgetThemeCss(theme: WidgetTheme): string {
  const declarations = Object.entries(theme)
    .filter(([, value]) => Boolean(value))
    .map(([property, value]) => `${property}: ${value}`)
  return declarations.length ? `:root { ${declarations.join('; ')}; }` : ''
}

export function applyWidgetTheme(element: HTMLElement, theme: WidgetTheme): void {
  for (const [property, value] of Object.entries(theme)) {
    if (value) element.style.setProperty(property, value)
  }
}
