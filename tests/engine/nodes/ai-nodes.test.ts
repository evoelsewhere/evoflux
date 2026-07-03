import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { NodeFactory } from '../../../src/engine/node-factory'
import { VariablePool } from '../../../src/engine/variable-pool'
import '../../../src/engine/nodes/index'
import { setupWindowAPI, teardownWindowAPI, type MockWindowAPI } from '../../helpers/mock-window-api'

const pool = new VariablePool()
const ctx = { nodeId: 'ai-test', signal: undefined }

let mockAPI: MockWindowAPI

beforeAll(() => {
  mockAPI = setupWindowAPI()
})

afterAll(() => {
  teardownWindowAPI()
})

describe('LLMNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('llm')
    expect(meta.type).toBe('llm')
    expect(meta.category).toBe('ai')
    expect(meta.inputs.some(i => i.name === 'prompt')).toBe(true)
    expect(meta.outputs.some(o => o.name === 'output')).toBe(true)
  })

  it('should call LLM and return output', async () => {
    mockAPI.chatMock.mockResolvedValueOnce('Hello from LLM')
    const node = NodeFactory.create('llm')
    const output = await node.run(
      { prompt: 'Say hello' },
      { provider: 'openai', model: 'gpt-4o', temperature: 0.7 },
      pool,
      ctx
    )
    expect(output.output).toBe('Hello from LLM')
    expect(mockAPI.chatMock).toHaveBeenCalled()
  })

  it('should include system prompt in messages', async () => {
    mockAPI.chatMock.mockResolvedValueOnce('response')
    const node = NodeFactory.create('llm')
    await node.run(
      { prompt: 'test', system_prompt: 'You are a pirate' },
      { provider: 'openai', model: 'gpt-4o' },
      pool,
      ctx
    )
    const [messages] = mockAPI.chatMock.mock.calls[mockAPI.chatMock.mock.calls.length - 1]
    expect(messages).toEqual([
      { role: 'system', content: 'You are a pirate' },
      { role: 'user', content: 'test' },
    ])
  })

  it('should throw on missing prompt', async () => {
    const node = NodeFactory.create('llm')
    await expect(node.run({}, {}, pool, ctx)).rejects.toThrow('Prompt is required')
  })
})

describe('ParameterExtractorNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('parameter-extractor')
    expect(meta.type).toBe('parameter-extractor')
    expect(meta.category).toBe('ai')
    expect(meta.outputs.some(o => o.name === 'parameters')).toBe(true)
  })

  it('should extract parameters', async () => {
    mockAPI.chatMock.mockResolvedValueOnce(JSON.stringify({ city: 'Hanoi', country: 'Vietnam' }))
    const node = NodeFactory.create('parameter-extractor')
    const output = await node.run(
      { text: 'The weather in Hanoi, Vietnam is sunny' },
      { model: 'gpt-4o-mini', parameters: [{ name: 'city', type: 'string' }, { name: 'country', type: 'string' }] },
      pool,
      ctx
    )
    expect(output.parameters).toEqual({ city: 'Hanoi', country: 'Vietnam' })
  })
})

describe('QuestionClassifierNode', () => {
  it('should have correct metadata', () => {
    const meta = NodeFactory.getMetadata('question-classifier')
    expect(meta.type).toBe('question-classifier')
    expect(meta.category).toBe('ai')
    expect(meta.outputs.some(o => o.name === 'category')).toBe(true)
  })

  it('should classify question', async () => {
    mockAPI.chatMock.mockResolvedValueOnce('bug')
    const node = NodeFactory.create('question-classifier')
    const output = await node.run(
      { text: 'My app crashes when I click the button' },
      { model: 'gpt-4o-mini', categories: ['bug', 'feature', 'question'] },
      pool,
      ctx
    )
    expect(output.category).toBe('bug')
  })
})
