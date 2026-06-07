export interface AIMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

export interface ChatOptions {
  model?: string
  provider?: 'openai' | 'ollama'
  temperature?: number
  maxTokens?: number
}

export interface AIProviderConfig {
  provider: 'openai' | 'ollama'
  openaiApiKey: string
  ollamaUrl: string
  selectedModel: string
}
