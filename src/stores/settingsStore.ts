import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type AIProvider = 'openai' | 'ollama' | 'anthropic' | 'claude-cli' | 'copilot-cli'
export type FontSize = 'small' | 'medium' | 'large'
export type FontFamily = 'inter' | 'system' | 'mono'

export interface AppearanceSettings {
  theme: 'dark' | 'light'
  accentColor: string
  fontSize: FontSize
  fontFamily: FontFamily
  compactMode: boolean
  canvasDotSize: number
  canvasDotColor: string
  nodeBorderRadius: number
  sidebarWidth: number
}

export const ACCENT_PRESETS = [
  { name: 'Blue', value: '#0070f3' },
  { name: 'Violet', value: '#7c3aed' },
  { name: 'Rose', value: '#e11d48' },
  { name: 'Orange', value: '#ea580c' },
  { name: 'Amber', value: '#d97706' },
  { name: 'Emerald', value: '#059669' },
  { name: 'Teal', value: '#0d9488' },
  { name: 'Cyan', value: '#0891b2' },
  { name: 'Pink', value: '#db2777' },
  { name: 'Indigo', value: '#4f46e5' }
]

export const FONT_SIZE_MAP: Record<FontSize, { base: number; label: string }> = {
  small: { base: 11, label: 'Small (11px)' },
  medium: { base: 13, label: 'Medium (13px)' },
  large: { base: 15, label: 'Large (15px)' }
}

export const FONT_FAMILY_MAP: Record<FontFamily, { css: string; label: string }> = {
  inter: { css: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", label: 'Inter' },
  system: { css: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", label: 'System' },
  mono: { css: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace", label: 'Monospace' }
}

interface SettingsState {
  aiProvider: AIProvider
  openaiApiKey: string
  ollamaUrl: string
  anthropicApiKey: string
  anthropicBaseUrl: string
  selectedModel: string
  appearance: AppearanceSettings

  setAiProvider: (provider: AIProvider) => void
  setOpenaiApiKey: (key: string) => void
  setOllamaUrl: (url: string) => void
  setAnthropicApiKey: (key: string) => void
  setAnthropicBaseUrl: (url: string) => void
  setSelectedModel: (model: string) => void
  updateAppearance: (patch: Partial<AppearanceSettings>) => void
}

function syncToMain(state: Partial<SettingsState>) {
  try {
    window.api?.settings?.save({
      aiProvider: state.aiProvider,
      openaiApiKey: state.openaiApiKey,
      ollamaUrl: state.ollamaUrl,
      anthropicApiKey: state.anthropicApiKey,
      anthropicBaseUrl: state.anthropicBaseUrl,
      selectedModel: state.selectedModel,
      appearance: state.appearance
    })
  } catch { /* main process not available */ }
}

const DEFAULT_APPEARANCE: AppearanceSettings = {
  theme: 'dark',
  accentColor: '#0070f3',
  fontSize: 'medium',
  fontFamily: 'inter',
  compactMode: false,
  canvasDotSize: 1,
  canvasDotColor: '',
  nodeBorderRadius: 8,
  sidebarWidth: 200
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      aiProvider: 'openai',
      openaiApiKey: '',
      ollamaUrl: 'http://localhost:11434',
      anthropicApiKey: '',
      anthropicBaseUrl: 'https://api.anthropic.com',
      selectedModel: 'gpt-4o-mini',
      appearance: DEFAULT_APPEARANCE,

      setAiProvider: (provider) => { set({ aiProvider: provider }); syncToMain(get()) },
      setOpenaiApiKey: (key) => { set({ openaiApiKey: key }); syncToMain(get()) },
      setOllamaUrl: (url) => { set({ ollamaUrl: url }); syncToMain(get()) },
      setAnthropicApiKey: (key) => { set({ anthropicApiKey: key }); syncToMain(get()) },
      setAnthropicBaseUrl: (url) => { set({ anthropicBaseUrl: url }); syncToMain(get()) },
      setSelectedModel: (model) => { set({ selectedModel: model }); syncToMain(get()) },
      updateAppearance: (patch) => {
        set((s) => ({ appearance: { ...s.appearance, ...patch } }))
        syncToMain(get())
      }
    }),
    {
      name: 'evoflux-settings',
      merge: (persisted, current) => {
        const p = persisted as Partial<SettingsState>
        return {
          ...current,
          ...p,
          appearance: { ...DEFAULT_APPEARANCE, ...p?.appearance }
        }
      }
    }
  )
)

export async function initSettingsStore() {
  try {
    const data = await window.api?.settings?.load()
    if (!data) return
    const s = useSettingsStore.getState()
    const patch: Partial<SettingsState> = {}
    if (data.appearance && typeof data.appearance === 'object') {
      patch.appearance = { ...DEFAULT_APPEARANCE, ...(data.appearance as Partial<AppearanceSettings>) }
    }
    const remote = data as Record<string, unknown>
    if (!s.openaiApiKey && remote.openaiApiKey) patch.openaiApiKey = remote.openaiApiKey as string
    if (!s.anthropicApiKey && remote.anthropicApiKey) patch.anthropicApiKey = remote.anthropicApiKey as string
    if (!s.anthropicBaseUrl && remote.anthropicBaseUrl !== 'https://api.anthropic.com') patch.anthropicBaseUrl = remote.anthropicBaseUrl as string
    if (!s.ollamaUrl && remote.ollamaUrl) patch.ollamaUrl = remote.ollamaUrl as string
    if (Object.keys(patch).length > 0) {
      useSettingsStore.setState(patch)
    }
  } catch {}
}
