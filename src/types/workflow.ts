import type { Node, Edge } from 'reactflow'

export interface WorkflowData {
  id: string
  name: string
  description: string
  nodes: Node[]
  edges: Edge[]
  createdAt: string
  updatedAt: string
}

export interface NodeData {
  label: string
  type: string
  icon?: string
  category?: string
  config?: Record<string, unknown>
  status?: NodeStatus
  error?: string
  text?: string
}

export type NodeStatus = 'idle' | 'running' | 'completed' | 'error'

export interface AITaskConfig {
  prompt: string
  model: string
  provider: 'openai' | 'ollama'
  temperature: number
  maxTokens: number
  systemPrompt: string
}

export interface ConditionConfig {
  condition: string
  trueLabel: string
  falseLabel: string
}
