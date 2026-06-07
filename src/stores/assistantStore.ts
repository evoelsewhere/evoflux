import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool'

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  timestamp: number
  toolName?: string
  toolArgs?: Record<string, unknown>
  thought?: string
  isStreaming?: boolean
}

interface AssistantState {
  messages: ChatMessage[]
  isThinking: boolean
  currentStep: string
  selectedProviderId: string
  selectedModel: string
  maxIterations: number

  addMessage: (msg: Omit<ChatMessage, 'id' | 'timestamp'>) => void
  updateLastAssistant: (patch: Partial<ChatMessage>) => void
  setThinking: (thinking: boolean) => void
  setCurrentStep: (step: string) => void
  setSelectedProvider: (providerId: string) => void
  setSelectedModel: (model: string) => void
  setMaxIterations: (n: number) => void
  clearMessages: () => void
}

let msgCounter = 0

export const useAssistantStore = create<AssistantState>()(
  persist(
    (set) => ({
      messages: [],
      isThinking: false,
      currentStep: '',
      selectedProviderId: '',
      selectedModel: '',
      maxIterations: 20,

      addMessage: (msg) => set((s) => ({
        messages: [...s.messages, {
          ...msg,
          id: `msg-${Date.now()}-${++msgCounter}`,
          timestamp: Date.now()
        }]
      })),

      updateLastAssistant: (patch) => set((s) => {
        const msgs = [...s.messages]
        for (let i = msgs.length - 1; i >= 0; i--) {
          if (msgs[i].role === 'assistant') {
            msgs[i] = { ...msgs[i], ...patch }
            break
          }
        }
        return { messages: msgs }
      }),

      setThinking: (thinking) => set({ isThinking: thinking }),
      setCurrentStep: (step) => set({ currentStep: step }),
      setSelectedProvider: (providerId) => set({ selectedProviderId: providerId }),
      setSelectedModel: (model) => set({ selectedModel: model }),
      setMaxIterations: (n) => set({ maxIterations: n }),
      clearMessages: () => set({ messages: [], isThinking: false, currentStep: '' })
    }),
    {
      name: 'evoflux-assistant',
      partialize: (state) => ({
        selectedProviderId: state.selectedProviderId,
        selectedModel: state.selectedModel,
        maxIterations: state.maxIterations
      })
    }
  )
)
