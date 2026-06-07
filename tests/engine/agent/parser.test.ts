import { describe, it, expect } from 'vitest'
import { parseAgentOutput } from '../../../src/engine/agent/parser'

describe('AgentParser', () => {
  it('should parse FINISH response', () => {
    const output = `Thought: I have completed the task.
FINISH: The answer is 42.`
    const result = parseAgentOutput(output)
    expect(result.type).toBe('finish')
    expect(result.finalAnswer).toBe('The answer is 42.')
  })

  it('should parse tool call with JSON block', () => {
    const output = `Thought: I need to read the file first.
Action:
\`\`\`json
{"tool": "read_file", "args": {"path": "/tmp/test.txt"}}
\`\`\``
    const result = parseAgentOutput(output)
    expect(result.type).toBe('tool_call')
    expect(result.toolName).toBe('read_file')
    expect(result.toolArgs).toEqual({ path: '/tmp/test.txt' })
  })

  it('should parse tool call with name and arguments', () => {
    const output = `Thought: I need to run some code.
Action:
\`\`\`json
{"name": "run_code", "arguments": {"language": "python", "code": "print(1+1)"}}
\`\`\``
    const result = parseAgentOutput(output)
    expect(result.type).toBe('tool_call')
    expect(result.toolName).toBe('run_code')
  })

  it('should parse unknown output', () => {
    const output = 'I think I need more information.'
    const result = parseAgentOutput(output)
    expect(result.type).toBe('unknown')
  })

  it('should handle FINAL ANSWER pattern', () => {
    const output = `Thought: Done.
FINAL ANSWER: The result is correct.`
    const result = parseAgentOutput(output)
    expect(result.type).toBe('finish')
  })

  it('should extract thought from output', () => {
    const output = `Thought: Let me analyze this code.
Action: do something`
    const result = parseAgentOutput(output)
    expect(result.thought).toContain('analyze')
  })
})
