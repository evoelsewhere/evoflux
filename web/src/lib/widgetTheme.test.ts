import { describe, expect, it } from 'vitest'
import { buildWidgetThemeCss, readWidgetTheme } from '@/lib/widgetTheme'

describe('widget theme bridge', () => {
  it('captures EvoFlux surface, text, border, accent, and semantic colors', () => {
    const values: Record<string, string> = {
      '--bg-page': 'rgb(34, 34, 34)',
      '--bg-card': 'rgb(44, 44, 44)',
      '--bg-key': 'rgb(54, 54, 54)',
      '--bg-muted': 'rgb(48, 48, 48)',
      '--color-text': 'rgb(242, 242, 242)',
      '--color-text-2': 'rgb(214, 214, 214)',
      '--color-text-muted': 'rgb(176, 176, 176)',
      '--color-border': 'rgb(71, 71, 71)',
      '--color-border-strong': 'rgb(102, 102, 102)',
      '--color-accent': 'rgb(217, 119, 87)',
      '--color-accent-soft': 'color(srgb 0.85 0.47 0.34 / 0.14)',
      '--color-text-on-accent': 'rgb(33, 26, 22)',
      '--accent-blue': 'rgb(96, 165, 250)',
      '--accent-green': 'rgb(85, 162, 124)',
      '--font-sans': 'Inter, sans-serif',
    }
    const style = { getPropertyValue: (name: string) => values[name] ?? '' } as CSSStyleDeclaration

    expect(readWidgetTheme(style)).toEqual(values)
    expect(buildWidgetThemeCss(values)).toContain('--color-accent: rgb(217, 119, 87)')
    expect(buildWidgetThemeCss(values)).toContain('--bg-page: rgb(34, 34, 34)')
  })

  it('omits missing tokens instead of writing empty values over widget defaults', () => {
    expect(readWidgetTheme({ getPropertyValue: () => '  ' } as unknown as CSSStyleDeclaration)).toEqual({})
    expect(buildWidgetThemeCss({})).toBe('')
  })
})
