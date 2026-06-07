import { useMutation, useQuery } from '@tanstack/react-query'
import { useSettingsStore } from '../stores/settingsStore'
import type { AIMessage, ChatOptions } from '../types/ai'

export function useAIChat() {
  const { aiProvider, selectedModel } = useSettingsStore()

  return useMutation({
    mutationFn: async ({ messages, options }: { messages: AIMessage[]; options?: ChatOptions }) => {
      return await window.api.ai.chat(messages, {
        model: options?.model || selectedModel,
        provider: options?.provider || aiProvider
      })
    }
  })
}

export function useAIStreamChat() {
  const { aiProvider, selectedModel } = useSettingsStore()

  return useMutation({
    mutationFn: async ({
      messages,
      options,
      onChunk
    }: {
      messages: AIMessage[]
      options?: ChatOptions
      onChunk: (chunk: string) => void
    }) => {
      const unsubscribe = window.api.onStreamChunk(onChunk)

      try {
        const result = await window.api.ai.streamChat(messages, {
          model: options?.model || selectedModel,
          provider: options?.provider || aiProvider
        })
        return result
      } finally {
        unsubscribe()
      }
    }
  })
}

export function useAIModels(provider?: string) {
  const { aiProvider } = useSettingsStore()

  return useQuery({
    queryKey: ['ai-models', provider || aiProvider],
    queryFn: () => window.api.ai.listModels(provider || aiProvider)
  })
}
