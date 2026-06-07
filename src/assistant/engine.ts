import { buildAssistantSystemPrompt } from './prompt'
import { createWorkflowTools, type WorkflowToolContext } from './tools'
import { parseAgentOutput, buildToolResultPrompt } from '../engine/agent/parser'
import { getProviderFromStore } from './provider-helper'
import { useAssistantStore } from '../stores/assistantStore'
import type { NodeData } from '../types/workflow'
import type { Node, Edge } from 'reactflow'

export interface RunAssistantOptions {
  userMessage: string
  nodes: Node<NodeData>[]
  edges: Edge[]
  context: WorkflowToolContext
  onThought?: (thought: string) => void
  onToolCall?: (name: string, args: Record<string, unknown>) => void
  onToolResult?: (name: string, result: string) => void
  onFinish?: (answer: string) => void
  onError?: (error: string) => void
}

export async function runAssistant(options: RunAssistantOptions): Promise<string> {
  const { userMessage, context, onThought, onToolCall, onToolResult, onFinish, onError } = options
  const store = useAssistantStore.getState()
  const { selectedProviderId, selectedModel, maxIterations } = store

  const provider = getProviderFromStore(selectedProviderId)
  if (!provider) {
    const err = 'No AI provider configured. Please add a provider in Settings.'
    onError?.(err)
    return err
  }

  const model = selectedModel || provider.defaultModel
  const tools = createWorkflowTools(context)
  const systemPrompt = buildAssistantSystemPrompt()

  const toolDescs = tools.map(t => {
    const params = t.parameters.map(p => `  - ${p.name} (${p.type}${p.required ? ', required' : ''}): ${p.description}`).join('\n')
    return `### ${t.name}\n${t.description}\nParameters:\n${params}`
  }).join('\n\n')

  const fullSystemPrompt = `${systemPrompt}\n\n## Available Tools\n${toolDescs}`

  const messages: Array<{ role: string; content: string }> = [
    { role: 'system', content: fullSystemPrompt },
    { role: 'user', content: userMessage }
  ]

  let finalAnswer = ''

  for (let i = 0; i < maxIterations; i++) {
    useAssistantStore.getState().setThinking(true)
    useAssistantStore.getState().setCurrentStep(`Step ${i + 1}/${maxIterations}`)

    let llmOutput: string
    try {
      llmOutput = await window.api.ai.chat(messages, {
        model,
        provider: provider.type,
        providerConfig: { apiKey: provider.apiKey, baseUrl: provider.baseUrl }
      })
    } catch (error) {
      const err = `AI request failed: ${error instanceof Error ? error.message : 'Unknown error'}`
      onError?.(err)
      useAssistantStore.getState().setThinking(false)
      return err
    }

    const parsed = parseAgentOutput(llmOutput)

    if (parsed.thought) {
      onThought?.(parsed.thought)
    }

    if (parsed.type === 'finish') {
      finalAnswer = parsed.finalAnswer || parsed.thought || 'Done.'
      break
    }

    if (parsed.type === 'tool_call' && parsed.toolName) {
      const toolArgs = parsed.toolArgs || {}
      onToolCall?.(parsed.toolName, toolArgs)

      const tool = tools.find(t => t.name === parsed.toolName)
      let toolResult: string

      if (tool?.handlerFn) {
        try {
          toolResult = await tool.handlerFn(toolArgs, {} as never)
        } catch (e) {
          toolResult = `Error: ${e instanceof Error ? e.message : 'Tool execution failed'}`
        }
      } else {
        toolResult = `Error: Tool '${parsed.toolName}' not found. Available: ${tools.map(t => t.name).join(', ')}`
      }

      onToolResult?.(parsed.toolName, toolResult)

      messages.push({ role: 'assistant', content: llmOutput })
      messages.push({ role: 'user', content: buildToolResultPrompt(parsed.toolName, toolResult) })
      continue
    }

    messages.push({ role: 'assistant', content: llmOutput })
    messages.push({ role: 'user', content: 'Please use a tool or respond with FINISH.' })
  }

  if (!finalAnswer) {
    finalAnswer = `Reached maximum iterations (${maxIterations}). Stopping.`
  }

  useAssistantStore.getState().setThinking(false)
  useAssistantStore.getState().setCurrentStep('')
  onFinish?.(finalAnswer)
  return finalAnswer
}
