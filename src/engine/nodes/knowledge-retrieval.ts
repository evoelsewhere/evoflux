import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'
import { embed } from '../memory/embedding'
import {
  saveSemantic,
  searchSemanticByVector,
  searchEpisodicByVector,
  searchProceduralByVector,
  incrementSemanticAccess
} from '../db/memory-repo'
import { hybridSearch } from '../kb/hybrid-search'
import { executeUsecase } from '../usecase/executor'

interface KnowledgeRetrievalConfig {
  query?: string
  top_k?: number
  layer?: 'semantic' | 'episodic' | 'procedural' | 'all'
  workflow_id?: string
  mode?: 'search' | 'ingest' | 'kb_search' | 'usecase'
  content?: string
  content_type?: 'fact' | 'document' | 'code_snippet' | 'api_doc' | 'error_pattern'
  knowledge_base_id?: string
  min_similarity?: number
  project_path?: string
  usecase_name?: string
}

export class KnowledgeRetrievalNode extends BaseNode<KnowledgeRetrievalConfig> {
  readonly type = 'knowledge-retrieval'

  getMetadata(): NodeMetadata {
    return {
      type: 'knowledge-retrieval',
      label: 'Knowledge Retrieval',
      icon: 'database',
      category: 'ai',
      description: 'RAG from workflow memory, Knowledge Base, or Use Cases.',
      inputs: [
        { name: 'query', label: 'Query', type: 'string', required: false },
        { name: 'content', label: 'Content to Ingest', type: 'string', required: false },
        { name: 'workflow_id', label: 'Workflow ID', type: 'string', required: false },
        { name: 'input', label: 'Input (for usecase)', type: 'string', required: false }
      ],
      outputs: [
        { name: 'results', label: 'Results', type: 'array', required: false },
        { name: 'formatted', label: 'Formatted Text', type: 'string', required: false },
        { name: 'count', label: 'Result Count', type: 'number', required: false }
      ],
      defaultConfig: { top_k: 5, layer: 'all', mode: 'search' }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as KnowledgeRetrievalConfig
    const mode = cfg.mode || 'search'
    const workflowId = String(inputs.workflow_id || cfg.workflow_id || 'default')

    if (mode === 'ingest') return this.ingest(inputs, cfg, workflowId, context)
    if (mode === 'kb_search') return this.kbSearch(inputs, cfg, context)
    if (mode === 'usecase') return this.usecase(inputs, cfg, context)
    return this.search(inputs, cfg, workflowId, context)
  }

  private async ingest(
    inputs: Record<string, unknown>,
    cfg: KnowledgeRetrievalConfig,
    workflowId: string,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const content = String(inputs.content || cfg.content || '')
    if (!content) throw new NodeExecutionError(context.nodeId, this.type, 'Content is required for ingest mode')

    const contentType = cfg.content_type || 'document'
    const embedding = await embed(content, 'passage')
    const id = `mem-${Date.now()}`
    saveSemantic(workflowId, id, contentType, content, embedding)

    return {
      id,
      results: [{ id, type: contentType, content, score: 1.0 }],
      formatted: `[${contentType}] ${content}`,
      count: 1
    }
  }

  private async search(
    inputs: Record<string, unknown>,
    cfg: KnowledgeRetrievalConfig,
    workflowId: string,
    _context: NodeRunContext
  ): Promise<NodeOutput> {
    const query = String(inputs.query || cfg.query || '')
    if (!query) return { results: [], formatted: '', count: 0 }

    const topK = cfg.top_k || 5
    const layer = cfg.layer || 'all'
    const queryEmbedding = await embed(query, 'query')

    const allResults: Array<{ layer: string; id: string; content: string; score: number; metadata?: Record<string, unknown> }> = []

    if (layer === 'all' || layer === 'semantic') {
      const semanticResults = searchSemanticByVector(workflowId, queryEmbedding, topK)
      for (const r of semanticResults) {
        allResults.push({ layer: 'semantic', id: r.id, content: r.content, score: r.score })
        incrementSemanticAccess(r.id)
      }
    }

    if (layer === 'all' || layer === 'episodic') {
      const episodicResults = searchEpisodicByVector(workflowId, queryEmbedding, topK)
      for (const r of episodicResults) {
        allResults.push({ layer: 'episodic', id: r.id, content: `[${r.outcome}] ${r.task_description}`, score: r.score, metadata: { outcome: r.outcome } })
      }
    }

    if (layer === 'all' || layer === 'procedural') {
      const proceduralResults = searchProceduralByVector(workflowId, queryEmbedding, topK)
      for (const r of proceduralResults) {
        allResults.push({ layer: 'procedural', id: r.id, content: `${r.name}: ${r.pattern}`, score: r.score, metadata: { name: r.name } })
      }
    }

    allResults.sort((a, b) => b.score - a.score)
    const topResults = allResults.slice(0, topK)

    const parts: string[] = []
    if (topResults.length > 0) {
      parts.push(`## Memory Search Results (query: "${query}")`)
      for (const r of topResults) parts.push(`- [${r.layer}] ${r.content} (score: ${r.score.toFixed(3)})`)
    }

    return { results: topResults, formatted: parts.join('\n'), count: topResults.length }
  }

  private async kbSearch(
    inputs: Record<string, unknown>,
    cfg: KnowledgeRetrievalConfig,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const query = String(inputs.query || cfg.query || '')
    if (!query) return { results: [], formatted: '', count: 0 }

    const kbId = cfg.knowledge_base_id
    if (!kbId) throw new NodeExecutionError(context.nodeId, this.type, 'knowledge_base_id is required for kb_search mode')

    const topK = cfg.top_k || 5
    const minSimilarity = cfg.min_similarity || 0

    const searchResults = await hybridSearch(kbId, query, { limit: topK, minScore: minSimilarity })

    const results = searchResults.map(r => ({
      id: r.chunk_id,
      content: r.content,
      score: r.hybrid_score,
      doc_name: r.doc_name,
      doc_path: r.doc_path,
      metadata: r.metadata_json ? JSON.parse(r.metadata_json) : undefined
    }))

    const parts: string[] = []
    if (results.length > 0) {
      parts.push(`## Knowledge Base Search Results (query: "${query}")`)
      for (const r of results) {
        const meta = r.metadata
        const heading = meta?.heading ? ` [${meta.heading}]` : ''
        parts.push(`### ${r.doc_name}${heading} (score: ${r.score.toFixed(3)})`)
        parts.push(r.content.substring(0, 500))
        parts.push('')
      }
    }

    return { results, formatted: parts.join('\n'), count: results.length }
  }

  private async usecase(
    inputs: Record<string, unknown>,
    cfg: KnowledgeRetrievalConfig,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const projectPath = cfg.project_path
    if (!projectPath) throw new NodeExecutionError(context.nodeId, this.type, 'project_path is required for usecase mode')

    const usecaseName = cfg.usecase_name
    if (!usecaseName) throw new NodeExecutionError(context.nodeId, this.type, 'usecase_name is required for usecase mode')

    const kbId = cfg.knowledge_base_id
    if (!kbId) throw new NodeExecutionError(context.nodeId, this.type, 'knowledge_base_id is required for usecase mode')

    const input = String(inputs.input || inputs.query || '')

    const globalChat = (globalThis as any).__evolux_ai_chat as
      | ((messages: Array<{ role: string; content: string }>, opts?: { model?: string; provider?: string }) => Promise<string>)
      | undefined

    const result = await executeUsecase(projectPath, usecaseName, kbId, input, {
      aiChat: globalChat || undefined,
      maxResults: cfg.top_k || 5
    })

    return {
      results: result.kb_results,
      formatted: result.context,
      count: Object.values(result.kb_results).flat().length
    }
  }
}
