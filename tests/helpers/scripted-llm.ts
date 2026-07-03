import { vi } from 'vitest'

export function createScriptedLLM(responses: string[]): ReturnType<typeof vi.fn> {
  let callIndex = 0
  return vi.fn().mockImplementation(() => {
    if (callIndex >= responses.length) return Promise.resolve('FINISH: Done')
    return Promise.resolve(responses[callIndex++])
  })
}

export function createSuccessLLM(answer: string): ReturnType<typeof vi.fn> {
  return vi.fn().mockResolvedValue(`FINISH: ${answer}`)
}

export function createToolCallLLM(
  toolName: string,
  toolArgs: Record<string, unknown>,
  finalAnswer: string
): ReturnType<typeof vi.fn> {
  let called = false
  return vi.fn().mockImplementation(() => {
    if (!called) {
      called = true
      return Promise.resolve(
        `Thought: I need to use ${toolName}\nAction:\n\`\`\`json\n${JSON.stringify({ tool: toolName, args: toolArgs })}\n\`\`\``
      )
    }
    return Promise.resolve(`Thought: Done\nFINISH: ${finalAnswer}`)
  })
}
