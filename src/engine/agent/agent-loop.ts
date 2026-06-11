import { createToolContext, executeTool, TOOL_DEFINITIONS, type ToolContext, type ToolResult } from './coding-tools'
import { readFile } from 'fs/promises'
import { join, extname } from 'path'
import { readdir } from 'fs/promises'

export interface AgentConfig {
  task: string
  codebasePath: string
  context?: string
  maxIterations?: number
  provider?: string
  model?: string
}

export interface AgentEvent {
  type: 'thinking' | 'plan' | 'tool_call' | 'tool_result' | 'message' | 'complete' | 'error' | 'needs_info' | 'checkpoint'
  content: string
  tool?: string
  toolArgs?: Record<string, unknown>
  toolResult?: ToolResult
  iteration?: number
  filesChanged?: string[]
  plan?: string[]
}

interface ToolCall {
  name: string
  args: Record<string, unknown>
}

interface Message {
  role: string
  content: string
}

const SKIP_DIRS = new Set(['node_modules', '.git', 'dist', 'out', '.next', '__pycache__', '.venv', 'build', 'coverage', '.cache'])
const BINARY_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'ico', 'svg', 'woff', 'woff2', 'ttf', 'eot', 'pdf', 'zip', 'tar', 'gz', 'exe', 'dll', 'so', 'dylib', 'mp3', 'mp4', 'wav'])

async function buildProjectContext(codebasePath: string): Promise<string> {
  const parts: string[] = []

  try {
    const pkgRaw = await readFile(join(codebasePath, 'package.json'), 'utf-8')
    const pkg = JSON.parse(pkgRaw)
    parts.push(`## package.json
Name: ${pkg.name || 'unknown'}
Version: ${pkg.version || 'unknown'}
Scripts: ${Object.keys(pkg.scripts || {}).join(', ')}
Dependencies: ${Object.keys(pkg.dependencies || {}).slice(0, 20).join(', ')}${Object.keys(pkg.dependencies || {}).length > 20 ? '...' : ''}`)
  } catch { /* no package.json */ }

  try {
    const readme = await readFile(join(codebasePath, 'README.md'), 'utf-8')
    parts.push(`## README.md\n${readme.substring(0, 2000)}`)
  } catch { /* no README */ }

  try {
    const tree = await buildFileTree(codebasePath, 2)
    parts.push(`## Project Structure\n${tree}`)
  } catch { /* */ }

  return parts.join('\n\n')
}

async function buildFileTree(dir: string, depth: number, prefix = ''): Promise<string> {
  if (depth <= 0) return ''
  const entries = await readdir(dir, { withFileTypes: true })
  const lines: string[] = []
  const filtered = entries
    .filter(e => !SKIP_DIRS.has(e.name) && !e.name.startsWith('.'))
    .sort((a, b) => {
      if (a.isDirectory() && !b.isDirectory()) return -1
      if (!a.isDirectory() && b.isDirectory()) return 1
      return a.name.localeCompare(b.name)
    })
    .slice(0, 40)

  for (const entry of filtered) {
    if (entry.isDirectory()) {
      lines.push(`${prefix}📁 ${entry.name}/`)
      if (depth > 1) {
        const sub = await buildFileTree(join(dir, entry.name), depth - 1, prefix + '  ')
        lines.push(sub)
      }
    } else {
      lines.push(`${prefix}📄 ${entry.name}`)
    }
  }
  if (entries.length > 40) lines.push(`${prefix}... +${entries.length - 40} more`)
  return lines.join('\n')
}

function buildSystemPrompt(projectContext: string, kbContext?: string): string {
  return `You are an expert coding agent. You read codebases, understand architecture, write clean code, and verify your work.

## Your Capabilities
You have tools to: read files, write files, edit files, run bash commands, search code, manage git, and run tests.

## How You Work

### Step 1: Understand
Before making any changes:
- Read the project structure (get_file_tree)
- Read key files (README, package.json, config files)
- Search for relevant code (grep)
- Understand the architecture

### Step 2: Plan
Before coding, think through your approach:
- Use the think tool to outline your plan
- Identify which files need changes
- Consider edge cases and error handling
- Plan for testing

### Step 3: Implement
Make changes carefully:
- Read a file before editing it
- Use edit_file for precise changes (exact text replacement)
- Use write_file for new files or complete rewrites
- Make small, focused changes
- Check your work with git_diff

### Step 4: Verify
After changes:
- Run tests (run_tests)
- Run build if applicable (bash: npm run build)
- Check for errors
- Verify the logic is correct

### Step 5: Checkpoint
Save your progress:
- Use git_checkpoint to save working state
- Use git_diff to verify changes before committing

## Important Rules
1. ALWAYS read a file before editing it — you need to see the exact content
2. Use edit_file for small changes — old_text must match EXACTLY (including whitespace)
3. Use write_file for new files or complete rewrites
4. Run tests after changes to verify correctness
5. If tests fail, analyze the error and fix it
6. If you need more information, say NEED_INFO: <what you need>
7. When the task is complete, say DONE: <summary of all changes>
8. Be concise — don't repeat yourself
9. If stuck, try a different approach or ask for help
10. Use think tool to reason through complex problems

## Project Context
${projectContext}

${kbContext ? `## Knowledge Base Context\n${kbContext}` : ''}

## Available Tools
${TOOL_DEFINITIONS.map(t => `- **${t.name}**: ${t.description}`).join('\n')}

When you need to call a tool, output a JSON code block:
\`\`\`json
{"tool": "tool_name", "args": {"param": "value"}}
\`\`\`

You can call multiple tools in sequence. Always explain what you're doing briefly before calling a tool.`
}

function buildToolResultMessage(toolName: string, args: Record<string, unknown>, result: ToolResult): string {
  const status = result.success ? '✓' : '✗'
  const argsStr = JSON.stringify(args).substring(0, 300)
  const output = result.output?.substring(0, 12000) || ''
  const error = result.error ? `\nError: ${result.error}` : ''
  return `[Tool Result: ${status} ${toolName}(${argsStr})]\n${output}${error}`
}

export async function* runAgent(
  config: AgentConfig,
  aiChat: (messages: Message[], opts?: { model?: string; provider?: string }) => Promise<string>
): AsyncGenerator<AgentEvent> {
  const maxIterations = config.maxIterations ?? 30
  const ctx = createToolContext(config.codebasePath)
  const filesChanged = new Set<string>()
  const startTime = Date.now()

  yield { type: 'thinking', content: 'Analyzing project structure...', iteration: 0 }

  const projectContext = await buildProjectContext(config.codebasePath)
  const systemPrompt = buildSystemPrompt(projectContext, config.context)

  const messages: Message[] = [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: `Working directory: ${config.codebasePath}\n\nTask: ${config.task}` }
  ]

  yield { type: 'thinking', content: 'Starting implementation...', iteration: 0 }

  let consecutiveErrors = 0
  let lastToolCalls: ToolCall[] = []

  for (let i = 0; i < maxIterations; i++) {
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(0)
    yield { type: 'thinking', content: `Step ${i + 1}/${maxIterations} (${elapsed}s elapsed)...`, iteration: i + 1 }

    let response: string
    try {
      response = await aiChat(messages, { model: config.model, provider: config.provider })
      consecutiveErrors = 0
    } catch (error) {
      consecutiveErrors++
      const errMsg = error instanceof Error ? error.message : String(error)
      yield { type: 'error', content: `LLM error (attempt ${consecutiveErrors}): ${errMsg}`, iteration: i + 1 }
      if (consecutiveErrors >= 3) {
        yield { type: 'error', content: 'Too many consecutive LLM errors, stopping.', iteration: i + 1 }
        return
      }
      messages.push({ role: 'user', content: `Error calling LLM: ${errMsg}. Please try again.` })
      continue
    }

    messages.push({ role: 'assistant', content: response })

    if (response.includes('DONE:')) {
      const summary = response.split('DONE:')[1].trim().split('\n')[0]
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(0)
      yield {
        type: 'complete',
        content: `${summary}\n\nCompleted in ${elapsed}s, ${i + 1} steps, ${filesChanged.size} files changed.`,
        iteration: i + 1,
        filesChanged: Array.from(filesChanged)
      }
      return
    }

    if (response.includes('NEED_INFO:')) {
      const info = response.split('NEED_INFO:')[1].trim().split('\n')[0]
      yield { type: 'needs_info', content: info, iteration: i + 1 }
      return
    }

    const toolCalls = parseToolCalls(response)

    if (toolCalls.length === 0) {
      const hasCodeBlock = response.includes('```')
      if (hasCodeBlock) {
        yield { type: 'message', content: response.substring(0, 300), iteration: i + 1 }
        messages.push({ role: 'user', content: 'I see you wrote some code but didn\'t use a tool to save it. Please use write_file or edit_file to make changes, or use think to plan your approach.' })
      } else {
        yield { type: 'message', content: response.substring(0, 300), iteration: i + 1 }
        messages.push({ role: 'user', content: 'Please use a tool to continue working on the task. Use think to plan, read_file to explore, or edit_file/write_file to make changes.' })
      }
      continue
    }

    lastToolCalls = toolCalls

    for (const call of toolCalls) {
      yield {
        type: 'tool_call',
        content: `${call.name}(${JSON.stringify(call.args).substring(0, 300)})`,
        tool: call.name,
        toolArgs: call.args,
        iteration: i + 1
      }

      const result = await executeTool(call.name, call.args, ctx)

      if (call.name === 'write_file' || call.name === 'edit_file') {
        const path = String(call.args.path)
        filesChanged.add(path)
      }

      if (call.name === 'git_checkpoint') {
        yield {
          type: 'checkpoint',
          content: result.output || 'Checkpoint created',
          iteration: i + 1,
          filesChanged: Array.from(filesChanged)
        }
      }

      yield {
        type: 'tool_result',
        content: result.output?.substring(0, 500) || result.error || '',
        tool: call.name,
        toolResult: result,
        iteration: i + 1
      }

      const toolMsg = buildToolResultMessage(call.name, call.args, result)
      messages.push({ role: 'user', content: toolMsg })

      if (!result.success && (call.name === 'edit_file' || call.name === 'write_file')) {
        messages.push({
          role: 'user',
          content: `The ${call.name} call failed. Please read the file first to see its exact content, then try again with the correct text.`
        })
      }
    }

    if (messages.length > 50) {
      const system = messages[0]
      const recent = messages.slice(-30)
      messages.splice(0, messages.length, system, ...recent)
    }
  }

  yield {
    type: 'error',
    content: `Max iterations (${maxIterations}) reached. ${filesChanged.size} files changed. Use the changes so far or increase max_iterations.`,
    iteration: maxIterations,
    filesChanged: Array.from(filesChanged)
  }
}

function parseToolCalls(text: string): ToolCall[] {
  const calls: ToolCall[] = []

  // Pattern 1: ```json { "tool": "...", "args": {...} } ```
  const jsonPattern = /```(?:json|tool)?\s*\n?([\s\S]*?)```/g
  let match
  while ((match = jsonPattern.exec(text)) !== null) {
    try {
      const cleaned = match[1].trim()
      const parsed = JSON.parse(cleaned)
      if (parsed.tool || parsed.name) {
        calls.push({
          name: parsed.tool || parsed.name,
          args: parsed.args || parsed.parameters || parsed.input || {}
        })
      }
    } catch { /* not valid JSON */ }
  }

  // Pattern 2: tool_name({ "key": "value" })
  if (calls.length === 0) {
    const toolPattern = /\b(read_file|write_file|edit_file|bash|grep|find|list_dir|git_checkpoint|git_diff|run_tests|think|get_file_tree)\s*\(\s*(\{[\s\S]*?\})\s*\)/g
    while ((match = toolPattern.exec(text)) !== null) {
      try {
        const args = JSON.parse(match[2])
        calls.push({ name: match[1], args })
      } catch { /* not valid JSON */ }
    }
  }

  // Pattern 3: tool_name followed by JSON object
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
