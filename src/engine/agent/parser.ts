export type ActionType = 'tool_call' | 'finish' | 'unknown'

export interface ParsedAction {
  type: ActionType
  thought: string
  toolName?: string
  toolArgs?: Record<string, unknown>
  finalAnswer?: string
}

const FINISH_PATTERNS = [
  /FINISH[:\s]*(.*)/is,
  /FINAL[_\s]ANSWER[:\s]*(.*)/is,
  /I['']m\s+done[.\s]*(.*)/is,
  /Task\s+complete[d]?[.\s]*(.*)/is
]

const TOOL_JSON_PATTERN = /```json\s*\n([\s\S]*?)\n```/

export function parseAgentOutput(output: string): ParsedAction {
  const thought = extractThought(output)

  for (const pattern of FINISH_PATTERNS) {
    const match = output.match(pattern)
    if (match) {
      return {
        type: 'finish',
        thought,
        finalAnswer: match[1]?.trim() || thought
      }
    }
  }

  const toolCall = extractToolCall(output)
  if (toolCall) {
    return {
      type: 'tool_call',
      thought,
      toolName: toolCall.name,
      toolArgs: toolCall.args
    }
  }

  return {
    type: 'unknown',
    thought
  }
}

function extractThought(output: string): string {
  const thoughtMatch = output.match(/Thought[:\s]*(.*?)(?=\s*(?:Action|Tool|FINISH|$))/is)
  if (thoughtMatch) return thoughtMatch[1].trim()

  const lines = output.split('\n').filter(l => l.trim())
  if (lines.length > 0) return lines[0].trim()
  return output.substring(0, 200)
}

function extractToolCall(output: string): { name: string; args: Record<string, unknown> } | null {
  const jsonMatch = output.match(TOOL_JSON_PATTERN)
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[1])
      if (parsed.tool || parsed.name || parsed.function) {
        const name = parsed.tool || parsed.name || parsed.function
        const args = parsed.args || parsed.arguments || parsed.parameters || parsed.input || {}
        return { name, args: typeof args === 'string' ? JSON.parse(args) : args }
      }
    } catch {
      // Not valid JSON
    }
  }

  const actionMatch = output.match(/(?:Action|Tool)[:\s]*["']?(\w+)["']?\s*(?:Arguments?|Input|Args)[:\s]*(\{[\s\S]*?\})/is)
  if (actionMatch) {
    try {
      return { name: actionMatch[1], args: JSON.parse(actionMatch[2]) }
    } catch {
      // Not valid JSON
    }
  }

  const simpleMatch = output.match(/(?:use|call|invoke|execute)\s+(?:tool\s+)?["']?(\w+)["']?\s*(?:with|:)\s*(\{[\s\S]*?\})/is)
  if (simpleMatch) {
    try {
      return { name: simpleMatch[1], args: JSON.parse(simpleMatch[2]) }
    } catch {
      // Not valid JSON
    }
  }

  return null
}

export function buildToolResultPrompt(toolName: string, result: string): string {
  return `Observation: Tool '${toolName}' returned:\n${result}\n\nThought:`
}

export function buildAgentSystemPrompt(tools: Array<{ name: string; description: string; parameters: unknown[] }>): string {
  const toolDescriptions = tools.map(t => {
    const params = t.parameters.map(p => {
      const p2 = p as { name: string; type: string; description: string; required: boolean }
      return `  - ${p2.name} (${p2.type}${p2.required ? ', required' : ''}): ${p2.description}`
    }).join('\n')
    return `### ${t.name}\n${t.description}\nParameters:\n${params}`
  }).join('\n\n')

  return `You are a helpful AI assistant that can use tools to complete tasks.

Available Tools:
${toolDescriptions}

To use a tool, respond with:
Thought: <your reasoning about what to do next>
Action:
\`\`\`json
{"tool": "<tool_name>", "args": {"<param>": "<value>"}}
\`\`\`

When you have completed the task, respond with:
Thought: <summary of what you accomplished>
FINISH: <your final answer>

Important:
- Always start with a Thought
- Use tools when needed, don't make up information
- If a tool returns an error, try a different approach
- When the task is complete, use FINISH`
}
