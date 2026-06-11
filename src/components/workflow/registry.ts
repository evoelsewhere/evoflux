import type { ComponentType } from 'react'
import type { NodeProps } from 'reactflow'
import BaseNode from './nodes/_base/BaseNode'

export interface NodeCategory {
  name: string
  icon: string
  nodes: NodeDefinition[]
}

export interface NodeDefinition {
  type: string
  label: string
  icon: string
  category: string
  description: string
}

export const NODE_CATEGORIES: NodeCategory[] = [
  {
    name: 'Triggers',
    icon: 'play-circle',
    nodes: [
      { type: 'manual-trigger', label: 'Manual Trigger', icon: 'play-circle', category: 'trigger', description: 'User-initiated execution' },
      { type: 'webhook-trigger', label: 'Webhook', icon: 'global', category: 'trigger', description: 'HTTP webhook endpoint' },
      { type: 'schedule-trigger', label: 'Schedule', icon: 'clock-circle', category: 'trigger', description: 'Cron-based scheduling' }
    ]
  },
  {
    name: 'AI & LLM',
    icon: 'robot',
    nodes: [
      { type: 'llm', label: 'LLM', icon: 'robot', category: 'ai', description: 'AI model invocation' },
      { type: 'parameter-extractor', label: 'Parameter Extractor', icon: 'scan', category: 'ai', description: 'Structured extraction' },
      { type: 'question-classifier', label: 'Question Classifier', icon: 'tags', category: 'ai', description: 'N-way classification' },
      { type: 'knowledge-retrieval', label: 'Knowledge Retrieval', icon: 'database', category: 'ai', description: 'Query memory graph' }
    ]
  },
  {
    name: 'Logic',
    icon: 'branches',
    nodes: [
      { type: 'condition', label: 'Condition', icon: 'branches', category: 'logic', description: 'IF/ELSE branching' },
      { type: 'router', label: 'Router', icon: 'apartment', category: 'logic', description: 'Multi-way conditional routing (switch/case)' },
      { type: 'iteration', label: 'Iteration', icon: 'reload', category: 'logic', description: 'For-each loop' },
      { type: 'loop', label: 'Loop', icon: 'sync', category: 'logic', description: 'While loop' },
      { type: 'retry', label: 'Retry', icon: 'redo', category: 'logic', description: 'Retry on failure with exponential backoff' },
      { type: 'variable-aggregator', label: 'Variable Aggregator', icon: 'merge-cells', category: 'logic', description: 'Merge outputs from parallel branches' },
      { type: 'variable-assigner', label: 'Variable Assigner', icon: 'edit', category: 'logic', description: 'Set a named variable' },
      { type: 'template', label: 'Template', icon: 'file-text', category: 'logic', description: 'String template with variables' },
      { type: 'text-transform', label: 'Text Transform', icon: 'font-size', category: 'logic', description: 'String operations (trim, replace, case...)' },
      { type: 'data-transform', label: 'Data Transform', icon: 'swap', category: 'logic', description: 'JSON extract/map/filter/merge' },
      { type: 'delay', label: 'Delay', icon: 'clock-circle', category: 'logic', description: 'Pause execution' }
    ]
  },
  {
    name: 'Tools',
    icon: 'code',
    nodes: [
      { type: 'code', label: 'Code', icon: 'code-sandbox', category: 'tools', description: 'Python/JS execution' },
      { type: 'shell', label: 'Shell', icon: 'code', category: 'tools', description: 'Shell command' },
      { type: 'http-request', label: 'HTTP Request', icon: 'global', category: 'tools', description: 'External API call' },
      { type: 'file-explorer', label: 'File Explorer', icon: 'folder-open', category: 'tools', description: 'Browse local files' },
      { type: 'file-reader', label: 'File Reader', icon: 'file-text', category: 'tools', description: 'Read file content' },
      { type: 'context-loader', label: 'Context Loader', icon: 'database', category: 'tools', description: 'Load directory as context' },
      { type: 'file-write', label: 'File Write', icon: 'file-text', category: 'tools', description: 'Write content to file' },
      { type: 'web-search', label: 'Web Search', icon: 'search', category: 'tools', description: 'Search the web (DuckDuckGo)' },
      { type: 'text-splitter', label: 'Text Splitter', icon: 'scissor', category: 'tools', description: 'Chunk text for RAG' },
      { type: 'git-operations', label: 'Git Operations', icon: 'branches', category: 'tools', description: 'Git add, commit, push, and create pull request' }
    ]
  },
  {
    name: 'Agent',
    icon: 'robot',
    nodes: [
      { type: 'ai-agent', label: 'AI Agent', icon: 'robot', category: 'agent', description: 'Autonomous agent with tools for code, docs, APIs, and multi-step reasoning' },
      { type: 'agent-orchestrator', label: 'Orchestrator', icon: 'team', category: 'agent', description: 'Team of agents' },
      { type: 'sub-workflow', label: 'Sub-Workflow', icon: 'apartment', category: 'agent', description: 'Embed another workflow' }
    ]
  },
  {
    name: 'Other',
    icon: 'more',
    nodes: [
      { type: 'comment', label: 'Comment', icon: 'edit', category: 'other', description: 'Sticky note for documentation' }
    ]
  }
]

const nodeComponentMap: Record<string, ComponentType<NodeProps>> = {}
const nodeDefinitionMap = new Map<string, NodeDefinition>()

for (const category of NODE_CATEGORIES) {
  for (const node of category.nodes) {
    nodeDefinitionMap.set(node.type, node)
  }
}

export function getNodeComponent(type: string): ComponentType<NodeProps> {
  return nodeComponentMap[type] || BaseNode
}

export function getNodeDefinition(type: string): NodeDefinition | undefined {
  return nodeDefinitionMap.get(type)
}

export function getAllNodeTypes(): string[] {
  return Array.from(nodeDefinitionMap.keys())
}

export function searchNodes(query: string): NodeDefinition[] {
  const q = query.toLowerCase()
  const results: NodeDefinition[] = []
  for (const node of nodeDefinitionMap.values()) {
    if (node.label.toLowerCase().includes(q) || node.description.toLowerCase().includes(q) || node.type.includes(q)) {
      results.push(node)
    }
  }
  return results
}
