import { create } from 'zustand'
import { nanoid } from 'nanoid'

export type ProviderType = 'openai' | 'anthropic' | 'ollama' | 'openai-compatible' | 'claude-cli' | 'copilot-cli'

export interface ProviderInstance {
  id: string
  name: string
  type: ProviderType
  apiKey: string
  baseUrl: string
  defaultModel: string
  models: string[]
  isDefault: boolean
}

export const PROVIDER_TEMPLATES: Record<ProviderType, Omit<ProviderInstance, 'id' | 'name'>> = {
  openai: {
    type: 'openai', apiKey: '', baseUrl: 'https://api.openai.com/v1',
    defaultModel: 'gpt-4o-mini', models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'o1-preview', 'o1-mini'],
    isDefault: false
  },
  anthropic: {
    type: 'anthropic', apiKey: '', baseUrl: 'https://api.anthropic.com',
    defaultModel: 'claude-sonnet-4-20250514', models: ['claude-sonnet-4-20250514', 'claude-3-5-haiku-20241022', 'claude-3-opus-20240229'],
    isDefault: false
  },
  ollama: {
    type: 'ollama', apiKey: '', baseUrl: 'http://localhost:11434',
    defaultModel: 'llama3.2', models: ['llama3.2', 'llama3.1', 'mistral', 'codellama', 'qwen2.5'],
    isDefault: false
  },
  'openai-compatible': {
    type: 'openai-compatible', apiKey: '', baseUrl: '',
    defaultModel: '', models: [],
    isDefault: false
  },
  'claude-cli': {
    type: 'claude-cli', apiKey: '', baseUrl: '',
    defaultModel: 'claude', models: ['claude'],
    isDefault: false
  },
  'copilot-cli': {
    type: 'copilot-cli', apiKey: '', baseUrl: '',
    defaultModel: 'copilot', models: ['copilot'],
    isDefault: false
  }
}

export const PROVIDER_LABELS: Record<ProviderType, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  ollama: 'Ollama (Local)',
  'openai-compatible': 'OpenAI-Compatible',
  'claude-cli': 'Claude CLI',
  'copilot-cli': 'GitHub Copilot CLI'
}

interface ProviderStore {
  providers: ProviderInstance[]
  hydrated: boolean
  addProvider: (type: ProviderType, name?: string) => string
  updateProvider: (id: string, patch: Partial<ProviderInstance>) => void
  removeProvider: (id: string) => void
  getProvider: (id: string) => ProviderInstance | undefined
  getDefaultProvider: () => ProviderInstance | undefined
  setDefault: (id: string) => void
  syncAllToMain: () => void
  loadFromMain: () => Promise<void>
}

function syncToMain(providers: ProviderInstance[]) {
  try {
    window.api?.settings?.save({ providers })
  } catch {}
}

export const useProviderStore = create<ProviderStore>()((set, get) => ({
  providers: [],
  hydrated: false,

  addProvider: (type, name) => {
    const tmpl = PROVIDER_TEMPLATES[type]
    const id = `prov-${nanoid(8)}`
    const p: ProviderInstance = {
      ...tmpl,
      id,
      name: name || `${PROVIDER_LABELS[type]} ${get().providers.filter(x => x.type === type).length + 1}`,
      isDefault: get().providers.length === 0
    }
    set((s) => {
      const next = [...s.providers, p]
      syncToMain(next)
      return { providers: next }
    })
    return id
  },

  updateProvider: (id, patch) => {
    set((s) => {
      const next = s.providers.map(p => p.id === id ? { ...p, ...patch } : p)
      syncToMain(next)
      return { providers: next }
    })
  },

  removeProvider: (id) => {
    set((s) => {
      let next = s.providers.filter(p => p.id !== id)
      if (next.length > 0 && !next.some(p => p.isDefault)) {
        next = next.map((p, i) => i === 0 ? { ...p, isDefault: true } : p)
      }
      syncToMain(next)
      return { providers: next }
    })
  },

  getProvider: (id) => get().providers.find(p => p.id === id),

  getDefaultProvider: () => get().providers.find(p => p.isDefault) || get().providers[0],

  setDefault: (id) => {
    set((s) => {
      const next = s.providers.map(p => ({ ...p, isDefault: p.id === id }))
      syncToMain(next)
      return { providers: next }
    })
  },

  syncAllToMain: () => syncToMain(get().providers),

  loadFromMain: async () => {
    try {
      const data = await window.api?.settings?.load() as Record<string, unknown> | null
      if (!data) { set({ hydrated: true }); return }
      const remote = data.providers as ProviderInstance[] | undefined
      if (remote && Array.isArray(remote) && remote.length > 0) {
        const local = get().providers
        if (local.length === 0) {
          set({ providers: remote, hydrated: true })
        } else {
          const localIds = new Set(local.map(p => p.id))
          const merged = [...local]
          for (const rp of remote) {
            if (!localIds.has(rp.id)) merged.push(rp)
          }
          set({ providers: merged, hydrated: true })
          syncToMain(merged)
        }
      } else {
        set({ hydrated: true })
        if (get().providers.length > 0) syncToMain(get().providers)
      }
    } catch {
      set({ hydrated: true })
    }
  }
}))

export async function initProviderStore() {
  await useProviderStore.getState().loadFromMain()
}
