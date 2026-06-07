import { createContext, useContext, useEffect, type ReactNode } from 'react'
import { ConfigProvider, theme as antTheme } from 'antd'
import { useSettingsStore, ACCENT_PRESETS, FONT_SIZE_MAP, FONT_FAMILY_MAP, type AppearanceSettings } from '../../stores/settingsStore'

type ThemeMode = 'dark' | 'light'

interface ThemeContextType {
  mode: ThemeMode
  toggleTheme: () => void
  setTheme: (mode: ThemeMode) => void
}

const ThemeContext = createContext<ThemeContextType>({
  mode: 'dark',
  toggleTheme: () => {},
  setTheme: () => {}
})

export function useTheme() {
  return useContext(ThemeContext)
}

function hexToRgb(hex: string): string {
  const h = hex.replace('#', '')
  const r = parseInt(h.substring(0, 2), 16)
  const g = parseInt(h.substring(2, 4), 16)
  const b = parseInt(h.substring(4, 6), 16)
  return `${r}, ${g}, ${b}`
}

function applyAppearance(appearance: AppearanceSettings) {
  const root = document.documentElement
  const accent = appearance.accentColor || '#0070f3'
  const accentRgb = hexToRgb(accent)
  const fontSizeBase = FONT_SIZE_MAP[appearance.fontSize]?.base || 13
  const fontFamily = FONT_FAMILY_MAP[appearance.fontFamily]?.css || FONT_FAMILY_MAP.inter.css

  root.style.setProperty('--accent', accent)
  root.style.setProperty('--accent-hover', accent + 'dd')
  root.style.setProperty('--accent-muted', `rgba(${accentRgb}, 0.15)`)
  root.style.setProperty('--border-focus', accent)
  root.style.setProperty('--font-size-base', `${fontSizeBase}px`)
  root.style.setProperty('--font-size-sm', `${fontSizeBase - 2}px`)
  root.style.setProperty('--font-size-lg', `${fontSizeBase + 2}px`)
  root.style.setProperty('--font-family', fontFamily)
  root.style.setProperty('--node-radius', `${appearance.nodeBorderRadius}px`)
  root.style.setProperty('--sidebar-width', `${appearance.sidebarWidth}px`)
  root.style.setProperty('--compact-padding', appearance.compactMode ? '4px' : '8px')
  root.style.setProperty('--compact-gap', appearance.compactMode ? '4px' : '8px')

  const dotColor = appearance.canvasDotColor || (appearance.theme === 'dark' ? '#222222' : '#eaeaea')
  root.style.setProperty('--canvas-dot-color', dotColor)
  root.style.setProperty('--canvas-dot-size', `${appearance.canvasDotSize}`)
}

function buildAntTheme(appearance: AppearanceSettings, mode: ThemeMode) {
  const accent = appearance.accentColor || '#0070f3'
  const fontFamily = FONT_FAMILY_MAP[appearance.fontFamily]?.css || FONT_FAMILY_MAP.inter.css
  const fontSizeBase = FONT_SIZE_MAP[appearance.fontSize]?.base || 13
  const radius = appearance.nodeBorderRadius

  const baseTokens = {
    colorPrimary: accent,
    borderRadius: radius,
    fontFamily,
    fontSize: fontSizeBase
  }

  if (mode === 'dark') {
    return {
      ...baseTokens,
      colorBgContainer: '#111111',
      colorBgElevated: '#171717',
      colorBgLayout: '#000000',
      colorBorder: '#222222',
      colorBorderSecondary: '#1a1a1a',
      colorText: '#ededed',
      colorTextSecondary: '#888888',
      colorTextTertiary: '#666666'
    }
  }

  return {
    ...baseTokens,
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBgLayout: '#fafafa',
    colorBorder: '#eaeaea',
    colorBorderSecondary: '#f0f0f0',
    colorText: '#171717',
    colorTextSecondary: '#666666',
    colorTextTertiary: '#999999'
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const { appearance, updateAppearance } = useSettingsStore()
  const mode = appearance.theme

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', mode)
    applyAppearance(appearance)
  }, [mode, appearance])

  const toggleTheme = () => updateAppearance({ theme: mode === 'dark' ? 'light' : 'dark' })
  const setTheme = (m: ThemeMode) => updateAppearance({ theme: m })

  return (
    <ThemeContext.Provider value={{ mode, toggleTheme, setTheme }}>
      <ConfigProvider
        theme={{
          algorithm: mode === 'dark' ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
          token: buildAntTheme(appearance, mode)
        }}
      >
        {children}
      </ConfigProvider>
    </ThemeContext.Provider>
  )
}
