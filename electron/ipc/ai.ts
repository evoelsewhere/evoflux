import { ipcMain } from 'electron'
import OpenAI from 'openai'
import Store from 'electron-store'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { getDatabase } from '../../src/engine/db/database'

const execFileAsync = promisify(execFile)
const store = new Store()

// ============ Provider Registry ============

type ProviderType = 'openai' | 'ollama' | 'anthropic' | 'claude-cli' | 'copilot-cli' | 'openai-compatible'

interface ProviderConfig {
  type: ProviderType
  apiKey?: string
  baseUrl?: string
  defaultModel: string
}

function resolveConfig(provider: ProviderType, override?: { apiKey?: string; baseUrl?: string }): ProviderConfig {
  const base = getProviderConfig(provider)
  return {
    ...base,
    apiKey: override?.apiKey || base.apiKey,
    baseUrl: override?.baseUrl || base.baseUrl
  }
}

function getProviderConfig(provider: ProviderType): ProviderConfig {
  switch (provider) {
    case 'openai':
      return {
        type: 'openai',
        apiKey: store.get('settings.openaiApiKey') as string,
        defaultModel: 'gpt-4o-mini'
      }
    case 'ollama':
      return {
        type: 'ollama',
        baseUrl: (store.get('settings.ollamaUrl') as string) || 'http://localhost:11434',
        defaultModel: 'llama3.2'
      }
    case 'anthropic':
      return {
        type: 'anthropic',
        apiKey: store.get('settings.anthropicApiKey') as string,
        baseUrl: (store.get('settings.anthropicBaseUrl') as string) || 'https://api.anthropic.com',
        defaultModel: 'claude-sonnet-4-20250514'
      }
    case 'claude-cli':
      return { type: 'claude-cli', defaultModel: 'claude' }
    case 'copilot-cli':
      return { type: 'copilot-cli', defaultModel: 'copilot' }
    case 'openai-compatible':
      return { type: 'openai-compatible', apiKey: '', baseUrl: '', defaultModel: '' }
  }
}

// ============ OpenAI Provider ============

let openaiClient: OpenAI | null = null

function getOpenAIClient(): OpenAI {
  if (!openaiClient) {
    const config = getProviderConfig('openai')
    if (!config.apiKey) throw new Error('OpenAI API key not configured')
    openaiClient = new OpenAI({ apiKey: config.apiKey })
  }
  return openaiClient
}

async function chatWithOpenAI(messages: Array<{ role: string; content: string }>, model: string): Promise<string> {
  const client = getOpenAIClient()
  const response = await client.chat.completions.create({
    model: model || 'gpt-4o-mini',
    messages: messages as OpenAI.ChatCompletionMessageParam[]
  })
  return response.choices[0]?.message?.content || ''
}

// ============ Anthropic Provider ============

async function chatWithAnthropic(messages: Array<{ role: string; content: string }>, model: string, cfg?: ProviderConfig): Promise<string> {
  const config = cfg || getProviderConfig('anthropic')
  if (!config.apiKey) throw new Error('Anthropic API key not configured')

  const systemMsg = messages.find(m => m.role === 'system')
  const nonSystemMsgs = messages.filter(m => m.role !== 'system')

  const response = await fetch(`${config.baseUrl}/v1/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': config.apiKey,
      'anthropic-version': '2023-06-01'
    },
    body: JSON.stringify({
      model: model || config.defaultModel,
      max_tokens: 4096,
      system: systemMsg?.content || undefined,
      messages: nonSystemMsgs.map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.content }))
    })
  })

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`Anthropic error (${response.status}): ${errorText}`)
  }

  const data = await response.json()
  return data.content?.[0]?.text || ''
}

// ============ Ollama Provider ============

async function chatWithOllama(messages: Array<{ role: string; content: string }>, model: string, cfg?: ProviderConfig): Promise<string> {
  const config = cfg || getProviderConfig('ollama')
  const response = await fetch(`${config.baseUrl}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: model || config.defaultModel, messages, stream: false })
  })

  if (!response.ok) throw new Error(`Ollama error: ${response.statusText}`)
  const data = await response.json()
  return data.message?.content || ''
}

async function listOllamaModels(): Promise<string[]> {
  const config = getProviderConfig('ollama')
  try {
    const response = await fetch(`${config.baseUrl}/api/tags`)
    if (!response.ok) return []
    const data = await response.json()
    return data.models?.map((m: { name: string }) => m.name) || []
  } catch { return [] }
}

// ============ CLI Providers ============

async function chatWithClaudeCLI(messages: Array<{ role: string; content: string }>, _model: string): Promise<string> {
  const prompt = messages.map(m => {
    if (m.role === 'system') return `System: ${m.content}`
    if (m.role === 'user') return `Human: ${m.content}`
    return `Assistant: ${m.content}`
  }).join('\n\n')

  try {
    const { stdout } = await execFileAsync('claude', ['--print', prompt], {
      timeout: 120000,
      maxBuffer: 10 * 1024 * 1024
    })
    return stdout.trim()
  } catch (error) {
    const msg = error instanceof Error ? error.message : 'Claude CLI failed'
    throw new Error(`Claude CLI error: ${msg}`)
  }
}

async function chatWithCopilotCLI(messages: Array<{ role: string; content: string }>, _model: string): Promise<string> {
  const prompt = messages.filter(m => m.role !== 'system').map(m => m.content).join('\n')

  try {
    const { stdout } = await execFileAsync('gh', ['copilot', 'suggest', '-t', 'shell', prompt], {
      timeout: 60000,
      maxBuffer: 10 * 1024 * 1024
    })
    return stdout.trim()
  } catch (error) {
    const msg = error instanceof Error ? error.message : 'Copilot CLI failed'
    throw new Error(`Copilot CLI error: ${msg}`)
  }
}

// ============ Unified Chat Router ============

async function chat(provider: ProviderType, messages: Array<{ role: string; content: string }>, model: string): Promise<string> {
  switch (provider) {
    case 'openai': return chatWithOpenAI(messages, model)
    case 'anthropic': return chatWithAnthropic(messages, model)
    case 'ollama': return chatWithOllama(messages, model)
    case 'claude-cli': return chatWithClaudeCLI(messages, model)
    case 'copilot-cli': return chatWithCopilotCLI(messages, model)
    default: throw new Error(`Unknown provider: ${provider}`)
  }
}

async function listModels(provider: ProviderType): Promise<string[]> {
  switch (provider) {
    case 'openai':
      return ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo', 'o1-preview', 'o1-mini']
    case 'anthropic':
      return ['claude-sonnet-4-20250514', 'claude-3-5-haiku-20241022', 'claude-3-opus-20240229']
    case 'ollama':
      return await listOllamaModels()
    case 'claude-cli':
      return ['claude']
    case 'copilot-cli':
      return ['copilot']
    default:
      return []
  }
}

async function testConnection(provider: ProviderType): Promise<boolean> {
  try {
    switch (provider) {
      case 'openai': {
        const client = getOpenAIClient()
        await client.models.list()
        return true
      }
      case 'anthropic': {
        const config = getProviderConfig('anthropic')
        if (!config.apiKey) return false
        const res = await fetch(`${config.baseUrl}/v1/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'x-api-key': config.apiKey, 'anthropic-version': '2023-06-01' },
          body: JSON.stringify({ model: config.defaultModel, max_tokens: 1, messages: [{ role: 'user', content: 'hi' }] })
        })
        return res.ok || res.status === 400 // 400 means API key is valid but request was minimal
      }
      case 'ollama': {
        const config = getProviderConfig('ollama')
        const res = await fetch(`${config.baseUrl}/api/tags`)
        return res.ok
      }
      case 'claude-cli': {
        const { stdout } = await execFileAsync('claude', ['--version'], { timeout: 5000 })
        return stdout.length > 0
      }
      case 'copilot-cli': {
        const { stdout } = await execFileAsync('gh', ['copilot', '--version'], { timeout: 5000 })
        return stdout.length > 0
      }
      case 'openai-compatible': {
        const config = getProviderConfig('openai-compatible')
        if (!config.apiKey || !config.baseUrl) return false
        const res = await fetch(`${config.baseUrl}/models`, { headers: { 'Authorization': `Bearer ${config.apiKey}` } })
        return res.ok
      }
      default: return false
    }
  } catch { return false }
}

// ============ SQLite Model Config ============

function saveModelConfig(provider: ProviderType, model: string, config: Record<string, unknown>): void {
  try {
    const db = getDatabase()
    db.exec(`CREATE TABLE IF NOT EXISTS model_config (
      id TEXT PRIMARY KEY,
      provider TEXT NOT NULL,
      model TEXT NOT NULL,
      config_json TEXT,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )`)
    const now = Date.now()
    db.prepare('INSERT OR REPLACE INTO model_config (id, provider, model, config_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)')
      .run(`${provider}:${model}`, provider, model, JSON.stringify(config), now, now)
  } catch { /* DB not available */ }
}

function getModelConfig(provider: ProviderType, model: string): Record<string, unknown> | null {
  try {
    const db = getDatabase()
    const row = db.prepare('SELECT config_json FROM model_config WHERE id = ?').get(`${provider}:${model}`) as { config_json: string } | undefined
    return row ? JSON.parse(row.config_json) : null
  } catch { return null }
}

function listModelConfigs(): Array<{ provider: string; model: string; config: Record<string, unknown> }> {
  try {
    const db = getDatabase()
    const rows = db.prepare('SELECT provider, model, config_json FROM model_config ORDER BY updated_at DESC').all() as Array<{ provider: string; model: string; config_json: string }>
    return rows.map(r => ({ provider: r.provider, model: r.model, config: JSON.parse(r.config_json) }))
  } catch { return [] }
}

// ============ IPC Handlers ============

export function registerAIHandlers(): void {
  ipcMain.handle('settings:save', async (_event, settings) => {
    if (settings && typeof settings === 'object') {
      for (const [key, value] of Object.entries(settings)) {
        store.set(`settings.${key}`, value)
      }
    }
    return { success: true }
  })

  ipcMain.handle('settings:load', async () => {
    return {
      providers: store.get('settings.providers') || [],
      appearance: store.get('settings.appearance') || null
    }
  })

  ipcMain.handle('ai:chat', async (_event, messages, options) => {
    const provider = (options?.provider || store.get('settings.aiProvider') || 'openai') as ProviderType
    const model = options?.model || ''
    const config = resolveConfig(provider, options?.providerConfig)
    try {
      switch (provider) {
        case 'openai':
        case 'openai-compatible': {
          if (!config.apiKey) throw new Error(`${provider} API key not configured`)
          const client = new OpenAI({ apiKey: config.apiKey, baseURL: config.baseUrl })
          const response = await client.chat.completions.create({
            model: model || config.defaultModel,
            messages: messages as OpenAI.ChatCompletionMessageParam[]
          })
          return response.choices[0]?.message?.content || ''
        }
        case 'anthropic': return await chatWithAnthropic(messages, model, config)
        case 'ollama': return await chatWithOllama(messages, model, config)
        case 'claude-cli': return await chatWithClaudeCLI(messages, model)
        case 'copilot-cli': return await chatWithCopilotCLI(messages, model)
        default: throw new Error(`Unknown provider: ${provider}`)
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Unknown error'
      throw new Error(`AI chat failed: ${msg}`)
    }
  })

  ipcMain.handle('ai:stream-chat', async (event, messages, options) => {
    const provider = (options?.provider || store.get('settings.aiProvider') || 'openai') as ProviderType
    const model = options?.model || ''

    try {
      if (provider === 'ollama') {
        const config = getProviderConfig('ollama')
        const response = await fetch(`${config.baseUrl}/api/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: model || config.defaultModel, messages, stream: true })
        })
        if (!response.ok) throw new Error(`Ollama error: ${response.statusText}`)
        const reader = response.body?.getReader()
        const decoder = new TextDecoder()
        while (reader) {
          const { done, value } = await reader.read()
          if (done) break
          const chunk = decoder.decode(value)
          for (const line of chunk.split('\n').filter(Boolean)) {
            try {
              const data = JSON.parse(line)
              if (data.message?.content) event.sender.send('ai:stream-chunk', data.message.content)
            } catch { /* skip */ }
          }
        }
        return 'Stream complete'
      }

      if (provider === 'openai') {
        const client = getOpenAIClient()
        const stream = await client.chat.completions.create({
          model: model || 'gpt-4o-mini',
          messages: messages as OpenAI.ChatCompletionMessageParam[],
          stream: true
        })
        for await (const chunk of stream) {
          const content = chunk.choices[0]?.delta?.content
          if (content) event.sender.send('ai:stream-chunk', content)
        }
        return 'Stream complete'
      }

      // Non-streaming fallback for other providers
      const result = await chat(provider, messages, model)
      event.sender.send('ai:stream-chunk', result)
      return 'Stream complete'
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Unknown error'
      throw new Error(`AI stream failed: ${msg}`)
    }
  })

  ipcMain.handle('ai:list-models', async (_event, provider) => {
    const p = (provider || store.get('settings.aiProvider') || 'openai') as ProviderType
    return await listModels(p)
  })

  ipcMain.handle('ai:test-connection', async (_event, provider, providerConfig) => {
    const cfg = resolveConfig(provider, providerConfig)
    try {
      switch (provider) {
        case 'openai':
        case 'openai-compatible': {
          if (!cfg.apiKey) return false
          const client = new OpenAI({ apiKey: cfg.apiKey, baseURL: cfg.baseUrl })
          await client.models.list()
          return true
        }
        case 'anthropic': {
          if (!cfg.apiKey) return false
          const res = await fetch(`${cfg.baseUrl}/v1/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'x-api-key': cfg.apiKey, 'anthropic-version': '2023-06-01' },
            body: JSON.stringify({ model: cfg.defaultModel, max_tokens: 1, messages: [{ role: 'user', content: 'hi' }] })
          })
          return res.ok || res.status === 400
        }
        case 'ollama': {
          const res = await fetch(`${cfg.baseUrl}/api/tags`)
          return res.ok
        }
        case 'claude-cli': {
          const { stdout } = await execFileAsync('claude', ['--version'], { timeout: 5000 })
          return stdout.length > 0
        }
        case 'copilot-cli': {
          const { stdout } = await execFileAsync('gh', ['copilot', '--version'], { timeout: 5000 })
          return stdout.length > 0
        }
        default: return false
      }
    } catch { return false }
  })

  ipcMain.handle('ai:save-model-config', async (_event, provider, model, config) => {
    saveModelConfig(provider, model, config)
    return { success: true }
  })

  ipcMain.handle('ai:get-model-config', async (_event, provider, model) => {
    return getModelConfig(provider, model)
  })

  ipcMain.handle('ai:list-model-configs', async () => {
    return listModelConfigs()
  })
}
