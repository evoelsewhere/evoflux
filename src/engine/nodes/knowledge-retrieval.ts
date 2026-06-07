import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { WorkflowMemory } from '../memory/api'

interface KnowledgeRetrievalConfig {
  query?: string
  top_k?: number
  layer?: 'semantic' | 'episodic' | 'procedural' | 'all'
}

const memoryInstances = new Map<string, WorkflowMemory>()

export function getOrCreateMemory(workflowId: string): WorkflowMemory {
  if (!memoryInstances.has(workflowId)) {
    memoryInstances.set(workflowId, new WorkflowMemory(workflowId))
  }
  return memoryInstances.get(workflowId)!
}

export class KnowledgeRetrievalNode extends BaseNode<KnowledgeRetrievalConfig> {
  readonly type = 'knowledge-retrieval'

  getMetadata(): NodeMetadata {
    return {
      type: 'knowledge-retrieval',
      label: 'Knowledge Retrieval',
      icon: 'database',
      category: 'ai',
      description: 'Query workflow memory graph (FluxMem) for relevant context.',
      inputs: [
        { name: 'query', label: 'Query', type: 'string', required: true }
      ],
      outputs: [
        { name: 'results', label: 'Results', type: 'string', required: false },
        { name: 'count', label: 'Result Count', type: 'number', required: false }
      ],
      defaultConfig: { top_k: 5, layer: 'all' }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    _context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as KnowledgeRetrievalConfig
    const query = String(inputs.query || cfg.query || '')
    const topK = cfg.top_k || 5
    const layer = cfg.layer || 'all'

    if (!query) {
      return { results: '', count: 0 }
    }

    const memory = getOrCreateMemory('default')
    const parts: string[] = []

    if (layer === 'all' || layer === 'semantic') {
      const semanticResults = await memory.searchSemantic(query, topK)
      if (semanticResults.length > 0) {
        parts.push('## Relevant Knowledge')
        for (const r of semanticResults) {
          parts.push(`- [${r.unit.type}] ${r.unit.content} (score: ${r.score.toFixed(2)})`)
        }
      }
    }

    if (layer === 'all' || layer === 'episodic') {
      const episodicResults = await memory.searchEpisodic(query, topK)
      if (episodicResults.length > 0) {
        parts.push('## Similar Past Experiences')
        for (const r of episodicResults) {
          const outcome = r.episode.outcome === 'success' ? '✓' : '✗'
          parts.push(`- ${outcome} ${r.episode.taskDescription.substring(0, 200)} (score: ${r.score.toFixed(2)})`)
        }
      }
    }

    if (layer === 'all' || layer === 'procedural') {
      const proceduralResults = await memory.searchProcedural(query, topK)
      if (proceduralResults.length > 0) {
        parts.push('## Known Patterns')
        for (const r of proceduralResults) {
          parts.push(`- ${r.procedure.name}: ${r.procedure.description} (score: ${r.score.toFixed(2)})`)
        }
      }
    }

    const formatted = parts.join('\n')
    return { results: formatted, count: parts.filter(p => p.startsWith('- ')).length }
  }
}
