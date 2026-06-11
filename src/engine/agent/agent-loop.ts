import { createToolContext, executeTool, TOOL_DEFINITIONS, type ToolContext, type ToolResult } from './coding-tools'

export interface AgentConfig {
  task: string
  codebasePath: string
  context?: string
  maxIterations?: number
  provider?: string
  model?: string
}

export interface AgentEvent {
  type: 'thinking' | 'tool_call' | 'tool_result' | 'message' | 'complete' | 'error' | 'needs_info'
  content: string
  tool?: string
  toolArgs?: Record<string, unknown>
  toolResult?: ToolResult
  iteration?: number
  filesChanged?: string[]
}

const SYSTEM_PROMPT = `You are a coding agent. You have access to tools to read, write, edit files and execute bash commands.

Your job is to complete the given task by:
1. First, understand the codebase structure (list files, read key files)
2. Plan your implementation
3. Make changes using edit_file or write_file
4. Verify changes with bash (run tests, build, etc.)
5. If you need more information, ask for it

Rules:
- Always read files before editing them
- Use edit_file for small changes, write_file for new files or complete rewrites
- Run tests after changes to verify correctness
- Be precise with edit_file — old_text must match exactly
- If you need information that's not in the codebase, say NEED_INFO: <what you need>
- When done, say DONE: <summary of changes>

Available tools: read_file, write_file, edit_file, bash, grep, find, list_dir`

function buildToolResultMessage(toolName: string, args: Record<string, unknown>, result: ToolResult): string {
  const status = result.success ? '✓' : '✗'
  const output = result.output?.substring(0, 8000) || ''
  const error = result.error ? `\nError: ${result.error}` : ''
  return `[${status} ${toolName}(${JSON.stringify(args).substring(0, 200)})]\n${output}${error}`
}

export async function* runAgent(
  config: AgentConfig,
  aiChat: (messages: Array<{ role: string; content: string }>, opts?: { model?: string; provider?: string }) => Promise<string>
): AsyncGenerator<AgentEvent> {
  const maxIterations = config.maxIterations ?? 30
  const ctx = createToolContext(config.codebasePath)
  const filesChanged = new Set<string>()

  const messages: Array<{ role: string; content: string }> = [
    { role: 'system', content: SYSTEM_PROMPT },
    { role: 'user', content: `Working directory: ${config.codebasePath}\n\n${config.context ? `Context from knowledge base:\n${config.context}\n\n` : ''}Task: ${config.task}` }
  ]

  yield { type: 'thinking', content: 'Starting coding agent...', iteration: 0 }

  for (let i = 0; i < maxIterations; i++) {
    yield { type: 'thinking', content: `Iteration ${i + 1}/${maxIterations}...`, iteration: i + 1 }

    let response: string
    try {
      response = await aiChat(messages, { model: config.model, provider: config.provider })
    } catch (error) {
      yield { type: 'error', content: `LLM error: ${error instanceof Error ? error.message : String(error)}`, iteration: i + 1 }
      return
    }

    messages.push({ role: 'assistant', content: response })

    if (response.includes('DONE:')) {
      const summary = response.split('DONE:')[1].trim()
      yield { type: 'complete', content: summary, iteration: i + 1, filesChanged: Array.from(filesChanged) }
      return
    }

    if (response.includes('NEED_INFO:')) {
      const info = response.split('NEED_INFO:')[1].trim()
      yield { type: 'needs_info', content: info, iteration: i + 1 }
      return
    }

    const toolCalls = parseToolCalls(response)
    if (toolCalls.length === 0) {
      yield { type: 'message', content: response.substring(0, 500), iteration: i + 1 }
      messages.push({ role: 'user', content: 'Please use a tool to continue, or say DONE: if you are finished.' })
      continue
    }

    for (const call of toolCalls) {
      yield { type: 'tool_call', content: `${call.name}(${JSON.stringify(call.args).substring(0, 200)})`, tool: call.name, toolArgs: call.args, iteration: i + 1 }

      const result = await executeTool(call.name, call.args, ctx)

      if (call.name === 'write_file' || call.name === 'edit_file') {
        const path = String(call.args.path)
        filesChanged.add(path)
      }

      yield { type: 'tool_result', content: result.output?.substring(0, 500) || result.error || '', tool: call.name, toolResult: result, iteration: i + 1 }

      const toolMsg = buildToolResultMessage(call.name, call.args, result)
      messages.push({ role: 'user', content: toolMsg })
    }
  }

  yield { type: 'error', content: `Max iterations (${maxIterations}) reached`, iteration: maxIterations }
}

interface ToolCall {
  name: string
  args: Record<string, unknown>
}

function parseToolCalls(text: string): ToolCall[] {
  const calls: ToolCall[] = []

  const jsonPattern = /```(?:tool|json)?\s*\n?([\s\S]*?)```/g
  let match
  while ((match = jsonPattern.exec(text)) !== null) {
    try {
      const parsed = JSON.parse(match[1].trim())
      if (parsed.tool || parsed.name) {
        calls.push({
          name: parsed.tool || parsed.name,
          args: parsed.args || parsed.parameters || parsed.input || {}
        })
      }
    } catch { /* not valid JSON */ }
  }

  if (calls.length === 0) {
    const toolPattern = /\b(read_file|write_file|edit_file|bash|grep|find|list_dir)\s*\(\s*(\{[\s\S]*?\})\s*\)/g
    while ((match = toolPattern.exec(text)) !== null) {
      try {
        const args = JSON.parse(match[2])
        calls.push({ name: match[1], args })
      } catch { /* not valid JSON */ }
    }
  }

  if (calls.length === 0) {
    const toolNames = TOOL_DEFINITIONS.map(t => t.name)
    for (const toolName of toolNames) {
      const idx = text.indexOf(toolName)
      if (idx === -1) continue
      const afterTool = text.substring(idx + toolName.length)
      const jsonMatch = afterTool.match(/\{[\s\S]*?\}/)
      if (jsonMatch) {
        try {
          const args = JSON.parse(jsonMatch[0])
          if (typeof args === 'object' && args !== null) {
            calls.push({ name: toolName, args })
          }
        } catch { /* not valid JSON */ }
      }
    }
  }

  return calls
}
