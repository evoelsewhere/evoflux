import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'
import '../../../src/engine/nodes/index'
import { setupWindowAPI, teardownWindowAPI, type MockWindowAPI } from '../../helpers/mock-window-api'

const pool = new VariablePool()
const ctx = { nodeId: 'agent-test', signal: undefined }

let mockAPI: MockWindowAPI

beforeAll(() => {
  mockAPI = setupWindowAPI()
})

afterAll(() => {
  teardownWindowAPI()
})

describe('ReActAgentNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('react-agent')
    expect(meta.type).toBe('react-agent')
    expect(meta.category).toBe('agent')
    expect(meta.outputs.some(o => o.name === 'output')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'iterations')).toBe(true)
  })

  it('should complete with FINISH response', async () => {
    mockAPI.chatMock.mockResolvedValueOnce('FINISH: The answer is 42')
    const node = NodeFactory.create('react-agent')
    const output = await node.run(
      { task: 'What is the answer?' },
      { provider: 'openai', model: 'gpt-4o', max_iterations: 5, tools: [] },
      pool,
      ctx
    )
    expect(output.output).toContain('42')
    expect(output.iterations).toBe(1)
    expect(output.thoughts).toBeDefined()
  })

  it('should handle tool calls', async () => {
    mockAPI.chatMock
      .mockResolvedValueOnce('Thought: I need to run code\nAction:\n```json\n{"tool": "run_code", "args": {"language": "javascript", "code": "1+1"}}\n```')
      .mockResolvedValueOnce('FINISH: The result is 2')
    const node = NodeFactory.create('react-agent')
    const output = await node.run(
      { task: 'Calculate 1+1' },
      { provider: 'openai', model: 'gpt-4o', max_iterations: 5, tools: ['run_code'] },
      pool,
      ctx
    )
    expect(output.output).toContain('2')
    expect(output.iterations).toBe(2)
  })

  it('should handle max iterations exceeded', async () => {
    mockAPI.chatMock.mockResolvedValue('Thought: Still working...')
    const node = NodeFactory.create('react-agent')
    const output = await node.run(
      { task: 'Complex task' },
      { provider: 'openai', model: 'gpt-4o', max_iterations: 2, tools: [] },
      pool,
      ctx
    )
    expect(output.iterations).toBe(2)
    expect(output.thoughts).toBeDefined()
  })

  it('should throw on missing task', async () => {
    const node = NodeFactory.create('react-agent')
    await expect(node.run({}, {}, pool, ctx)).rejects.toThrow('Task is required')
  })
})

describe('AgentOrchestratorNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('agent-orchestrator')
    expect(meta.type).toBe('agent-orchestrator')
    expect(meta.category).toBe('agent')
    expect(meta.outputs.some(o => o.name === 'output')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'results')).toBe(true)
  })

  it('should run sequential agents', async () => {
    mockAPI.chatMock.mockResolvedValue('FINISH: Task completed')
    const node = NodeFactory.create('agent-orchestrator')
    const output = await node.run(
      {},
      {
        task: 'Analyze the codebase',
        expected_output: 'A summary',
        process: 'sequential',
        agents: [
          { id: 'agent-1', name: 'Analyst', role: 'Code analyst', model: 'gpt-4o', provider: 'openai', tools: [] }
        ],
        max_rounds: 3,
      },
      pool,
      ctx
    )
    expect(output.output).toBeDefined()
    expect(output.results).toBeDefined()
    expect(Array.isArray(output.results)).toBe(true)
  })

  it('should throw on missing task', async () => {
    const node = NodeFactory.create('agent-orchestrator')
    await expect(node.run({}, {}, pool, ctx)).rejects.toThrow('Task is required')
  })

  it('should throw on empty agents', async () => {
    const node = NodeFactory.create('agent-orchestrator')
    await expect(
      node.run({}, { task: 'test', agents: [] }, pool, ctx)
    ).rejects.toThrow('At least one agent is required')
  })
})
