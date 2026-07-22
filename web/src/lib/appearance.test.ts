import { beforeEach, describe, expect, it } from 'vitest'
import {
  APPEARANCE_STORAGE_KEY,
  DEFAULT_APPEARANCE,
  FONT_FAMILIES,
  applyAppearance,
  readStoredAppearance,
  setStoredAppearance,
} from './appearance'

describe('appearance preferences', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-font')
    document.documentElement.style.removeProperty('--font-sans')
    document.documentElement.style.removeProperty('--font-heading')
  })

  it('supports and persists all five font presets', () => {
    expect(FONT_FAMILIES).toEqual(['inter', 'system', 'mono', 'geist', 'source-sans'])

    for (const fontFamily of FONT_FAMILIES) {
      setStoredAppearance({ ...DEFAULT_APPEARANCE, fontFamily })
      expect(readStoredAppearance().fontFamily).toBe(fontFamily)
    }
  })

  it('applies the selected font through the html data attribute', () => {
    applyAppearance({ ...DEFAULT_APPEARANCE, fontFamily: 'geist' })

    expect(document.documentElement).toHaveAttribute('data-font', 'geist')
    expect(document.documentElement.style.getPropertyValue('--font-sans')).toBe('')
    expect(document.documentElement.style.getPropertyValue('--font-heading')).toBe('')
  })

  it('migrates legacy composer preferences away without losing appearance settings', () => {
    localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify({
      accent: 'blue',
      fontFamily: 'system',
      fontScale: 1.1,
      composerControlStyle: 'legacy',
    }))

    expect(readStoredAppearance()).toEqual({
      accent: 'blue',
      fontFamily: 'system',
      fontScale: 1.1,
    })
  })

  it('persists only appearance settings that are still configurable', () => {
    setStoredAppearance({
      ...DEFAULT_APPEARANCE,
      accent: 'purple',
      fontScale: 1.1,
    })

    expect(readStoredAppearance()).toEqual({
      accent: 'purple',
      fontFamily: 'inter',
      fontScale: 1.1,
    })
  })
})
