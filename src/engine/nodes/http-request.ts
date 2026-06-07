import { BaseNode, type NodeMetadata, type NodeOutput, type NodeRunContext } from '../node-factory'
import type { VariablePool } from '../variable-pool'
import { NodeExecutionError } from '../errors'

interface HTTPConfig {
  url?: string
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH' | 'HEAD'
  headers?: Record<string, string>
  body?: unknown
  timeout_ms?: number
}

export class HTTPRequestNode extends BaseNode<HTTPConfig> {
  readonly type = 'http-request'

  getMetadata(): NodeMetadata {
    return {
      type: 'http-request',
      label: 'HTTP Request',
      icon: 'global',
      category: 'tools',
      description: 'Make external HTTP API calls.',
      inputs: [
        { name: 'url', label: 'URL', type: 'string', required: true },
        { name: 'body', label: 'Body', type: 'string', required: false }
      ],
      outputs: [
        { name: 'response', label: 'Response', type: 'string', required: false },
        { name: 'status', label: 'Status Code', type: 'number', required: false },
        { name: 'headers', label: 'Response Headers', type: 'object', required: false }
      ],
      defaultConfig: { method: 'GET', url: '', headers: {}, timeout_ms: 30000 }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    config: unknown,
    _pool: VariablePool,
    context: NodeRunContext
  ): Promise<NodeOutput> {
    const cfg = config as HTTPConfig
    const url = String(inputs.url || cfg.url || '')
    const method = cfg.method || 'GET'
    const headers = cfg.headers || {}
    const body = inputs.body ?? cfg.body
    const timeoutMs = cfg.timeout_ms || 30000

    if (!url) {
      throw new NodeExecutionError(context.nodeId, this.type, 'URL is required')
    }

    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), timeoutMs)

    try {
      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', ...headers },
        body: body && method !== 'GET' && method !== 'HEAD' ? (typeof body === 'string' ? body : JSON.stringify(body)) : undefined,
        signal: controller.signal
      })

      const responseText = await response.text()
      let responseData: unknown = responseText
      try {
        responseData = JSON.parse(responseText)
      } catch {
        // Keep as text
      }

      const responseHeaders: Record<string, string> = {}
      response.headers.forEach((value, key) => {
        responseHeaders[key] = value
      })

      return {
        response: typeof responseData === 'string' ? responseData : JSON.stringify(responseData, null, 2),
        status: response.status,
        headers: responseHeaders
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'HTTP request failed'
      throw new NodeExecutionError(context.nodeId, this.type, message, { cause: error })
    } finally {
      clearTimeout(timeout)
    }
  }
}
