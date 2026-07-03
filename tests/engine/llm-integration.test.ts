import { describe, it, expect, beforeAll } from 'vitest'
import { Graph } from '../../src/engine/graph'
import { GraphEngine } from '../../src/engine/graph-engine'
import { VariablePool } from '../../src/engine/variable-pool'
import '../../src/engine/nodes/index'

const PROVIDER_CONFIG = {
  baseUrl: 'https://token-plan-sgp.xiaomimimo.com/anthropic',
  apiKey: 'tp-s51e6u4x82u04mubar93p9dybarhbk4jzcvgbt964wvw0lys',
  model: 'mimo-v2.5-pro'
}

describe('LLM Integration', () => {
  beforeAll(() => {
    if (typeof window === 'undefined') {
      (globalThis as any).window = {
        api: {
          ai: {
            chat: async (messages: Array<{ role: string; content: string }>, options?: { model?: string }) => {
              const response = await fetch(`${PROVIDER_CONFIG.baseUrl}/v1/messages`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  'x-api-key': PROVIDER_CONFIG.apiKey,
                  'anthropic-version': '2023-06-01'
                },
                body: JSON.stringify({
                  model: options?.model || PROVIDER_CONFIG.model,
                  max_tokens: 128,
                  messages: messages.filter(m => m.role !== 'system').map(m => ({ role: m.role, content: m.content })),
                  system: messages.find(m => m.role === 'system')?.content || undefined
                })
              })

              if (!response.ok) {
                const err = await response.text()
                throw new Error(`API error ${response.status}: ${err}`)
              }

              const data = await response.json() as { content?: Array<{ text?: string }> }
              return data.content?.[0]?.text || ''
            }
          }
        }
      }
    }
  })

  it('should call LLM and get response', async () => {
    const graph = new Graph()
    graph.addNode({
      id: 'llm',
      type: 'llm',
      data: {
        label: 'LLM',
        type: 'llm',
        config: {
          model: PROVIDER_CONFIG.model,
          prompt: 'Say exactly: "Hello from Evolux"',
          temperature: 0,
          max_tokens: 64
        }
      }
    })

    const pool = new VariablePool()
    pool.set(['llm', 'prompt'], 'Say exactly: "Hello from Evolux"')

    const engine = new GraphEngine({ graph, variablePool: pool, maxSteps: 10 })

    let llmOutput: unknown = null
    let error: Error | null = null

    for await (const event of engine.runSequential()) {
      if (event.type === 'node:complete' && event.nodeId === 'llm') llmOutput = event.output
      if (event.type === 'node:error') error = event.error || null
    }

    expect(error).toBeNull()
    expect(llmOutput).toBeTruthy()
    const output = (llmOutput as Record<string, unknown>)?.output
    expect(typeof output).toBe('string')
    expect(typeof output === 'string' ? output.length : 0).toBeGreaterThanOrEqual(0)
  }, 30000)

  it('should handle system prompt', async () => {
    const graph = new Graph()
    graph.addNode({
      id: 'llm',
      type: 'llm',
      data: {
        label: 'LLM',
        type: 'llm',
        config: {
          model: PROVIDER_CONFIG.model,
          system_prompt: 'Respond with exactly one word.',
          prompt: 'Say hello',
          temperature: 0,
          max_tokens: 16
        }
      }
    })

    const pool = new VariablePool()
    pool.set(['llm', 'prompt'], 'Say hello')
    pool.set(['llm', 'system_prompt'], 'Respond with exactly one word.')

    const engine = new GraphEngine({ graph, variablePool: pool, maxSteps: 10 })

    let output = ''
    for await (const event of engine.runSequential()) {
      if (event.type === 'node:complete' && event.nodeId === 'llm') {
        output = String((event.output as Record<string, unknown>)?.output || '')
      }
    }

    expect(output.length).toBeGreaterThan(0)
  }, 30000)

  it('should run two LLM nodes sequentially', async () => {
    const graph = new Graph()
    graph.addNode({
      id: 'llm1',
      type: 'llm',
      data: {
        label: 'First',
        type: 'llm',
        config: {
          model: PROVIDER_CONFIG.model,
          prompt: 'Say "first"',
          temperature: 0,
          max_tokens: 16
        }
      }
    })
    graph.addNode({
      id: 'llm2',
      type: 'llm',
      data: {
        label: 'Second',
        type: 'llm',
        config: {
          model: PROVIDER_CONFIG.model,
          prompt: 'Say "second"',
          temperature: 0,
          max_tokens: 16
        }
      }
    })
    graph.addEdge({ id: 'e1', source: 'llm1', target: 'llm2' })

    const pool = new VariablePool()
    pool.set(['llm1', 'prompt'], 'Say "first"')
    pool.set(['llm2', 'prompt'], 'Say "second"')

    const engine = new GraphEngine({ graph, variablePool: pool, maxSteps: 10 })

    const completed: string[] = []
    for await (const event of engine.runSequential()) {
      if (event.type === 'node:complete' && event.nodeId) completed.push(event.nodeId)
    }

    expect(completed).toContain('llm1')
    expect(completed).toContain('llm2')
    expect(completed.indexOf('llm1')).toBeLessThan(completed.indexOf('llm2'))
  }, 30000)

  it('should handle condition node with LLM output', async () => {
    const graph = new Graph()
    graph.addNode({
      id: 'llm',
      type: 'llm',
      data: {
        label: 'LLM',
        type: 'llm',
        config: {
          model: PROVIDER_CONFIG.model,
          prompt: 'Respond with exactly: yes',
          temperature: 0,
          max_tokens: 16
        }
      }
    })
    graph.addNode({
      id: 'cond',
      type: 'condition',
      data: {
        label: 'Check',
        type: 'condition',
        config: {
          expression: 'value && String(value).length > 0',
          true_label: 'Yes',
          false_label: 'No'
        }
      }
    })
    graph.addEdge({ id: 'e1', source: 'llm', target: 'cond' })

    const pool = new VariablePool()
    pool.set(['llm', 'prompt'], 'Respond with exactly: yes')
    pool.set(['cond', 'value'], '')

    const engine = new GraphEngine({ graph, variablePool: pool, maxSteps: 10 })

    const completed: string[] = []
    for await (const event of engine.runSequential()) {
      if (event.type === 'node:complete' && event.nodeId) completed.push(event.nodeId)
    }

    expect(completed).toContain('llm')
    expect(completed).toContain('cond')
  }, 30000)
})
