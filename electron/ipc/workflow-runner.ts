import { ipcMain, BrowserWindow } from 'electron'
import { GraphEngine } from '../../src/engine/graph-engine'
import { VariablePool } from '../../src/engine/variable-pool'
import { UILayer } from '../../src/engine/layers'
import { deserializeGraph } from '../../src/engine/dsl'
import '../../src/engine/nodes/index'
import OpenAI from 'openai'
import { getSettingsJson } from '../../src/engine/db/repos'

let mainWindow: BrowserWindow | null = null

export function setMainWindow(win: BrowserWindow): void {
  mainWindow = win
}

function sendEvent(event: unknown): void {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('workflow:event', event)
  }
}

type ProviderType = 'openai' | 'ollama' | 'anthropic' | 'claude-cli' | 'copilot-cli' | 'openai-compatible'

function getProviderConfig(provider: ProviderType) {
  switch (provider) {
    case 'openai':
      return { apiKey: (getSettingsJson('openaiApiKey') as string) || '', defaultModel: 'gpt-4o-mini' }
    case 'ollama':
      return { baseUrl: (getSettingsJson('ollamaUrl') as string) || 'http://localhost:11434', defaultModel: 'llama3.2' }
    case 'anthropic':
      return {
        apiKey: (getSettingsJson('anthropicApiKey') as string) || '',
        baseUrl: (getSettingsJson('anthropicBaseUrl') as string) || 'https://api.anthropic.com',
        defaultModel: 'claude-sonnet-4-20250514'
      }
    case 'openai-compatible':
      return { apiKey: '', baseUrl: '', defaultModel: '' }
    default:
      return { defaultModel: '' }
  }
}

async function aiChat(messages: Array<{ role: string; content: string }>, options?: { model?: string; provider?: string }): Promise<string> {
  const provider = (options?.provider || getSettingsJson('aiProvider') || 'openai') as ProviderType
  const model = options?.model || ''
  const config = getProviderConfig(provider)

  switch (provider) {
    case 'openai':
    case 'openai-compatible': {
      if (!config.apiKey) throw new Error(`${provider} API key not configured`)
      const client = new OpenAI({ apiKey: config.apiKey, baseURL: (config as any).baseUrl })
      const response = await client.chat.completions.create({
        model: model || config.defaultModel,
        messages: messages as OpenAI.ChatCompletionMessageParam[]
      })
      return response.choices[0]?.message?.content || ''
    }
    case 'anthropic': {
      if (!config.apiKey) throw new Error('Anthropic API key not configured')
      const systemMsg = messages.find(m => m.role === 'system')
      const nonSystemMsgs = messages.filter(m => m.role !== 'system')
      const response = await fetch(`${(config as any).baseUrl}/v1/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-api-key': config.apiKey, 'anthropic-version': '2023-06-01' },
        body: JSON.stringify({
          model: model || config.defaultModel, max_tokens: 4096,
          system: systemMsg?.content || undefined,
          messages: nonSystemMsgs.map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.content }))
        })
      })
      if (!response.ok) throw new Error(`Anthropic error (${response.status}): ${await response.text()}`)
      const data = await response.json() as { content?: Array<{ text?: string }> }
      return data.content?.[0]?.text || ''
    }
    case 'ollama': {
      const response = await fetch(`${(config as any).baseUrl}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: model || config.defaultModel, messages, stream: false })
      })
      if (!response.ok) throw new Error(`Ollama error: ${response.statusText}`)
      const data = await response.json() as { message?: { content?: string } }
      return data.message?.content || ''
    }
    default:
      throw new Error(`Unsupported provider: ${provider}`)
  }
}

export function registerWorkflowRunnerHandlers(): void {
  ipcMain.handle('workflow:run', async (_event, dsl, options) => {
    try {
      (globalThis as any).__evolux_ai_chat = aiChat

      const graph = deserializeGraph(dsl)
      const pool = new VariablePool()

      if (options?.inputs) {
        for (const [key, value] of Object.entries(options.inputs)) {
          pool.set(['start', key], value)
        }
      }

      const uiLayer = new UILayer((event) => sendEvent(event))
      const engine = new GraphEngine({
        graph,
        variablePool: pool,
        layers: [uiLayer],
        maxSteps: options?.maxSteps || 1000,
        maxTimeMs: options?.maxTimeMs || 600000,
        maxNodeIterations: options?.maxNodeIterations || 100
      })

      const results: unknown[] = []

      if (engine.shouldUseRouting()) {
        for await (const event of engine.runWithRouting()) {
          results.push(event)
        }
      } else {
        for await (const event of engine.runSequential()) {
          results.push(event)
        }
      }

      return { success: true, results }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error'
      sendEvent({ type: 'graph:error', error: message, timestamp: Date.now() })
      return { success: false, error: message }
    }
  })

  ipcMain.handle('workflow:stop', async (_event, runId) => {
    sendEvent({ type: 'graph:aborted', runId, timestamp: Date.now() })
    return true
  })

  ipcMain.handle('workflow:run:status', async (_event, runId) => {
    return { runId, status: 'unknown' }
  })
}
