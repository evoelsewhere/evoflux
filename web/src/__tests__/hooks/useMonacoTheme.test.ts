import { describe, expect, it } from 'vitest'

import {
  sanitizeMonacoTheme,
  toMonacoThemeColor,
  toMonacoTokenHex,
} from '@/hooks/useMonacoTheme'

describe('Monaco theme color normalization', () => {
  it.each([
    ['#fff', 'FFFFFF'],
    ['fff', 'FFFFFF'],
    ['#1a2', '11AA22'],
    ['#ffffff', 'FFFFFF'],
    ['#abcdef80', 'ABCDEF'],
  ])('converts CSS color %s to a legal token color', (input, expected) => {
    expect(toMonacoTokenHex(input, '123456')).toBe(expected)
  })

  it('uses a known-good fallback for unsupported token colors', () => {
    expect(toMonacoTokenHex('var(--missing)', '#abc')).toBe('AABBCC')
    expect(toMonacoTokenHex('not-a-color', 'also-invalid')).toBe('FFFFFF')
  })

  it('normalizes UI colors and applies alpha after expanding shorthand', () => {
    expect(toMonacoThemeColor('#fff', '#000000')).toBe('#FFFFFF')
    expect(toMonacoThemeColor('#fff', '#000000', '26')).toBe('#FFFFFF26')
    expect(toMonacoThemeColor('#1234', '#000000')).toBe('#11223344')
  })

  it('sanitizes every color at the final defineTheme boundary', () => {
    const theme = sanitizeMonacoTheme({
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'keyword', foreground: '#fff' },
        { token: 'string', foreground: 'invalid', background: '#0008' },
      ],
      colors: {
        'editor.foreground': '#fff',
        'editor.background': '#0008',
        'editorCursor.foreground': 'invalid',
      },
    })

    expect(theme.rules).toEqual([
      { token: 'keyword', foreground: 'FFFFFF' },
      { token: 'string', foreground: 'FFFFFF', background: '000000' },
    ])
    expect(theme.colors).toEqual({
      'editor.foreground': '#FFFFFF',
      'editor.background': '#00000088',
      'editorCursor.foreground': '#1E1E1E',
    })

    for (const rule of theme.rules) {
      expect(rule.foreground).toMatch(/^[0-9A-F]{6}$/)
      if (rule.background) expect(rule.background).toMatch(/^[0-9A-F]{6}$/)
    }
  })
})
