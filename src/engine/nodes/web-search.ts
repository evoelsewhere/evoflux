import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'
import { searchWeb, fetchPages } from '../web'

interface WebSearchConfig {
  query?: string
  max_results?: number
  language?: string
  region?: string
  fetch_content?: boolean
  max_content_pages?: number
}

export class WebSearchNode extends BaseNode<WebSearchConfig> {
  readonly type = 'web-search'

  getMetadata(): NodeMetadata {
    return {
      type: 'web-search',
      label: 'Web Search',
      icon: 'search',
      category: 'tools',
      description: 'Search the web and optionally fetch page content. Built-in DuckDuckGo engine, no API key required.',
      inputs: [
        { name: 'query', label: 'Search Query', type: 'string', required: true },
        { name: 'language', label: 'Language', type: 'string', required: false }
      ],
      outputs: [
        { name: 'results', label: 'Search Results', type: 'array', required: false },
        { name: 'formatted', label: 'Formatted Results', type: 'string', required: false },
        { name: 'count', label: 'Result Count', type: 'number', required: false }
      ],
      defaultConfig: {
        max_results: 10,
        language: 'en',
        fetch_content: false,
        max_content_pages: 3
      }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as WebSearchConfig
    const query = String(inputs.query || cfg.query || '')
    const language = String(inputs.language || cfg.language || 'en')
    const maxResults = cfg.max_results || 10
    const fetchContent = cfg.fetch_content || false
    const maxContentPages = cfg.max_content_pages || 3

    if (!query) {
      throw new NodeExecutionError(context.nodeId, this.type, 'Search query is required')
    }

    try {
      const searchResults = await searchWeb(query, {
        maxResults,
        language,
        region: cfg.region
      })

      if (fetchContent && searchResults.length > 0) {
        const urls = searchResults.map(r => r.url)
        const pages = await fetchPages(urls, {
          maxPages: maxContentPages,
          timeoutMs: 10000,
          concurrency: 3
        })

        const pageMap = new Map(pages.map(p => [p.url, p]))

        const enriched = searchResults.map(r => {
          const page = pageMap.get(r.url)
          return {
            ...r,
            content: page?.content.mainContent || '',
            fullText: page?.content.text || ''
          }
        })

        return this.formatOutput(enriched)
      }

      return this.formatOutput(searchResults)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Web search failed'
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error })
    }
  }

  private formatOutput(results: Array<{ title: string; url: string; snippet: string; content?: string; fullText?: string }>): NodeOutput {
    const parts: string[] = [`Found ${results.length} results:\n`]

    for (let i = 0; i < results.length; i++) {
      const r = results[i]
      parts.push(`### ${i + 1}. ${r.title}`)
      parts.push(`URL: ${r.url}`)
      if (r.snippet) parts.push(`Snippet: ${r.snippet}`)
      if (r.content) {
        const truncated = r.content.length > 500 ? r.content.substring(0, 500) + '...' : r.content
        parts.push(`Content: ${truncated}`)
      }
      parts.push('')
    }

    return {
      results,
      formatted: parts.join('\n'),
      count: results.length
    }
  }
}
