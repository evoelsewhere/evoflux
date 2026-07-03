import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ListResourcesRequestSchema,
  ReadResourceRequestSchema
} from '@modelcontextprotocol/sdk/types.js'
import { TOOL_DEFINITIONS, handleToolCall } from './tools'
import { listKBs, getKB, listDocuments, listChunks, getKBStats, getDocument, listSources } from '../../src/engine/db/kb-repo'

export class EvoluxMCPServer {
  private server: Server
  private running = false

  constructor() {
    this.server = new Server(
      { name: 'evolux-kb', version: '1.0.0' },
      { capabilities: { tools: {}, resources: {} } }
    )

    this.registerHandlers()
  }

  private registerHandlers() {
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: TOOL_DEFINITIONS
    }))

    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params
      return await handleToolCall(name, (args || {}) as Record<string, unknown>)
    })

    this.server.setRequestHandler(ListResourcesRequestSchema, async () => {
      const kbs = listKBs()
      const resources = [
        { uri: 'kb://list', name: 'Knowledge Bases', mimeType: 'application/json', description: 'List of all knowledge bases' }
      ]

      for (const kb of kbs) {
        resources.push({
          uri: `kb://${kb.id}`,
          name: kb.name,
          mimeType: 'application/json',
          description: kb.description || `Knowledge base: ${kb.name}`
        })

        const docs = listDocuments(kb.id)
        for (const doc of docs) {
          resources.push({
            uri: `kb://${kb.id}/doc/${doc.id}`,
            name: doc.name,
            mimeType: 'text/plain',
            description: `${doc.name} (${doc.chunk_count} chunks)`
          })
        }
      }

      return { resources }
    })

    this.server.setRequestHandler(ReadResourceRequestSchema, async (request) => {
      const uri = request.params.uri

      if (uri === 'kb://list') {
        const kbs = listKBs()
        return {
          contents: [{
            uri,
            mimeType: 'application/json',
            text: JSON.stringify(kbs.map(kb => {
              let stats = {}
              try { stats = JSON.parse(kb.stats_json) } catch {}
              return { id: kb.id, name: kb.name, description: kb.description, stats }
            }), null, 2)
          }]
        }
      }

      const kbMatch = uri.match(/^kb:\/\/([^/]+)$/)
      if (kbMatch) {
        const kb = getKB(kbMatch[1])
        if (!kb) throw new Error(`KB not found: ${kbMatch[1]}`)
        const stats = getKBStats(kb.id)
        const sources = listSources(kb.id)
        return {
          contents: [{
            uri,
            mimeType: 'application/json',
            text: JSON.stringify({ ...kb, stats, sources }, null, 2)
          }]
        }
      }

      const docMatch = uri.match(/^kb:\/\/([^/]+)\/doc\/([^/]+)$/)
      if (docMatch) {
        const doc = getDocument(docMatch[2])
        if (!doc) throw new Error(`Document not found: ${docMatch[2]}`)
        const chunks = listChunks(doc.id)
        return {
          contents: [{
            uri,
            mimeType: 'application/json',
            text: JSON.stringify({ ...doc, chunks }, null, 2)
          }]
        }
      }

      throw new Error(`Unknown resource URI: ${uri}`)
    })
  }

  async startStdio(): Promise<void> {
    if (this.running) return
    const transport = new StdioServerTransport()
    await this.server.connect(transport)
    this.running = true
    console.error('[MCP] Server started on stdio')
  }

  async stop(): Promise<void> {
    if (!this.running) return
    await this.server.close()
    this.running = false
    console.error('[MCP] Server stopped')
  }

  isRunning(): boolean {
    return this.running
  }
}
