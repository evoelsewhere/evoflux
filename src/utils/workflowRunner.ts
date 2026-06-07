import type { Node, Edge } from 'reactflow'
import type { NodeData } from '../types/workflow'

interface ExecutionResult {
  nodeId: string
  output: string
  status: 'completed' | 'error'
}

interface WorkflowRunnerCallbacks {
  onNodeStart: (nodeId: string) => void
  onNodeComplete: (nodeId: string, output: string) => void
  onNodeError: (nodeId: string, error: string) => void
  onComplete: (results: ExecutionResult[]) => void
  onError: (error: string) => void
}

function topologicalSort(nodes: Node<NodeData>[], edges: Edge[]): string[] {
  const inDegree = new Map<string, number>()
  const adjacency = new Map<string, string[]>()

  for (const node of nodes) {
    inDegree.set(node.id, 0)
    adjacency.set(node.id, [])
  }

  for (const edge of edges) {
    adjacency.get(edge.source)?.push(edge.target)
    inDegree.set(edge.target, (inDegree.get(edge.target) || 0) + 1)
  }

  const queue: string[] = []
  for (const [id, degree] of inDegree) {
    if (degree === 0) queue.push(id)
  }

  const sorted: string[] = []
  while (queue.length > 0) {
    const current = queue.shift()!
    sorted.push(current)

    for (const neighbor of adjacency.get(current) || []) {
      const newDegree = (inDegree.get(neighbor) || 1) - 1
      inDegree.set(neighbor, newDegree)
      if (newDegree === 0) queue.push(neighbor)
    }
  }

  return sorted
}

export async function runWorkflow(
  nodes: Node<NodeData>[],
  edges: Edge[],
  callbacks: WorkflowRunnerCallbacks
): Promise<void> {
  const results = new Map<string, string>()
  const nodeMap = new Map(nodes.map((n) => [n.id, n]))

  const sortedIds = topologicalSort(nodes, edges)

  if (sortedIds.length !== nodes.length) {
    callbacks.onError('Workflow contains cycles')
    return
  }

  for (const nodeId of sortedIds) {
    const node = nodeMap.get(nodeId)
    if (!node) continue

    callbacks.onNodeStart(nodeId)

    try {
      if (node.type === 'start' || node.type === 'end') {
        results.set(nodeId, '')
        callbacks.onNodeComplete(nodeId, '')
        continue
      }

      if (node.type === 'ai-task') {
        const config = (node.data.config || {}) as Record<string, unknown>
        const prompt = String(config.prompt || '')
        const systemPrompt = String(config.systemPrompt || '')
        const model = String(config.model || '')
        const provider = String(config.provider || 'openai') as 'openai' | 'ollama'

        const contextParts: string[] = []
        for (const edge of edges) {
          if (edge.target === nodeId) {
            const sourceOutput = results.get(edge.source)
            if (sourceOutput) {
              contextParts.push(`Previous output: ${sourceOutput}`)
            }
          }
        }

        const messages = []
        if (systemPrompt) {
          messages.push({ role: 'system', content: systemPrompt })
        }

        let finalPrompt = prompt
        if (contextParts.length > 0) {
          finalPrompt = `${contextParts.join('\n')}\n\n${prompt}`
        }
        messages.push({ role: 'user', content: finalPrompt })

        const output = await window.api.ai.chat(messages, {
          model,
          provider
        })

        results.set(nodeId, output)
        callbacks.onNodeComplete(nodeId, output)
        continue
      }

      if (node.type === 'condition') {
        const sourceOutputs: string[] = []
        for (const edge of edges) {
          if (edge.target === nodeId) {
            const output = results.get(edge.source)
            if (output) sourceOutputs.push(output)
          }
        }

        const combinedInput = sourceOutputs.join('\n')
        results.set(nodeId, combinedInput)
        callbacks.onNodeComplete(nodeId, combinedInput)
        continue
      }

      results.set(nodeId, '')
      callbacks.onNodeComplete(nodeId, '')
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error'
      callbacks.onNodeError(nodeId, message)
      results.set(nodeId, `Error: ${message}`)
    }
  }

  const executionResults: ExecutionResult[] = []
  for (const [nodeId, output] of results) {
    executionResults.push({
      nodeId,
      output,
      status: output.startsWith('Error:') ? 'error' : 'completed'
    })
  }

  callbacks.onComplete(executionResults)
}
