import { registerTool, type AgentTool, type ToolContext } from './tools'
import { createSandbox } from '../sandbox/sandbox'

async function runCode(args: Record<string, unknown>, ctx: ToolContext): Promise<string> {
  const language = String(args.language || 'python')
  const code = String(args.code || '')
  if (!code) return 'Error: No code provided'

  try {
    const sandbox = await createSandbox({ workflowId: ctx.nodeId, runId: `agent-${ctx.nodeId}` })
    const result = await sandbox.execCode(language as 'python' | 'javascript', code)
    if (result.stderr && !result.stdout) return `Error: ${result.stderr}`
    return result.stdout || '(no output)'
  } catch (error) {
    return `Error: ${error instanceof Error ? error.message : 'Code execution failed'}`
  }
}

async function runCommand(args: Record<string, unknown>, ctx: ToolContext): Promise<string> {
  const command = String(args.command || '')
  if (!command) return 'Error: No command provided'

  try {
    const sandbox = await createSandbox({ workflowId: ctx.nodeId, runId: `agent-${ctx.nodeId}` })
    const result = await sandbox.exec(command, { timeoutMs: 30000 })
    if (result.exitCode !== 0 && !result.stdout) return `Error (exit ${result.exitCode}): ${result.stderr}`
    return result.stdout || result.stderr || '(no output)'
  } catch (error) {
    return `Error: ${error instanceof Error ? error.message : 'Command failed'}`
  }
}

async function readFile(args: Record<string, unknown>, ctx: ToolContext): Promise<string> {
  const filePath = String(args.path || '')
  if (!filePath) return 'Error: No file path provided'

  try {
    const sandbox = await createSandbox({ workflowId: ctx.nodeId, runId: `agent-${ctx.nodeId}` })
    const content = await sandbox.readFile(filePath)
    if (content.length > 50000) return content.substring(0, 50000) + '\n... [truncated]'
    return content
  } catch (error) {
    return `Error reading file: ${error instanceof Error ? error.message : 'Unknown error'}`
  }
}

async function writeFile(args: Record<string, unknown>, ctx: ToolContext): Promise<string> {
  const filePath = String(args.path || '')
  const content = String(args.content || '')
  if (!filePath) return 'Error: No file path provided'

  try {
    const sandbox = await createSandbox({ workflowId: ctx.nodeId, runId: `agent-${ctx.nodeId}` })
    await sandbox.writeFile(filePath, content)
    return `Successfully wrote ${content.length} characters to ${filePath}`
  } catch (error) {
    return `Error writing file: ${error instanceof Error ? error.message : 'Unknown error'}`
  }
}

async function searchMemory(args: Record<string, unknown>, _ctx: ToolContext): Promise<string> {
  const query = String(args.query || '')
  if (!query) return 'Error: No query provided'
  return 'Memory search not available yet. Will be implemented in F6 integration.'
}

async function httpRequest(args: Record<string, unknown>, _ctx: ToolContext): Promise<string> {
  const url = String(args.url || '')
  const method = String(args.method || 'GET').toUpperCase()
  const body = args.body

  if (!url) return 'Error: No URL provided'

  try {
    const response = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined
    })
    const text = await response.text()
    if (text.length > 10000) return text.substring(0, 10000) + '\n... [truncated]'
    return text
  } catch (error) {
    return `Error: ${error instanceof Error ? error.message : 'Request failed'}`
  }
}

const builtinTools: AgentTool[] = [
  {
    name: 'run_code',
    description: 'Execute Python or JavaScript code in a sandbox. Use for calculations, data processing, or testing logic.',
    parameters: [
      { name: 'language', type: 'string', description: 'Programming language: python or javascript', required: true },
      { name: 'code', type: 'string', description: 'Code to execute', required: true }
    ],
    handler: 'sandbox_code',
    handlerFn: runCode
  },
  {
    name: 'run_command',
    description: 'Execute a shell command. Use for running scripts, installing packages, or system operations.',
    parameters: [
      { name: 'command', type: 'string', description: 'Shell command to execute', required: true }
    ],
    handler: 'sandbox_shell',
    handlerFn: runCommand
  },
  {
    name: 'read_file',
    description: 'Read the contents of a file from the filesystem.',
    parameters: [
      { name: 'path', type: 'string', description: 'Absolute path to the file', required: true }
    ],
    handler: 'file_read',
    handlerFn: readFile
  },
  {
    name: 'write_file',
    description: 'Write content to a file. Creates parent directories if needed.',
    parameters: [
      { name: 'path', type: 'string', description: 'Absolute path to the file', required: true },
      { name: 'content', type: 'string', description: 'Content to write', required: true }
    ],
    handler: 'file_write',
    handlerFn: writeFile
  },
  {
    name: 'search_memory',
    description: 'Search workflow memory for relevant context from past executions.',
    parameters: [
      { name: 'query', type: 'string', description: 'Search query', required: true },
      { name: 'type', type: 'string', description: 'Memory type: semantic, episodic, or procedural', required: false }
    ],
    handler: 'memory_search',
    handlerFn: searchMemory
  },
  {
    name: 'http_request',
    description: 'Make an HTTP request to an external API endpoint.',
    parameters: [
      { name: 'url', type: 'string', description: 'URL to request', required: true },
      { name: 'method', type: 'string', description: 'HTTP method: GET, POST, PUT, DELETE', required: false },
      { name: 'body', type: 'object', description: 'Request body for POST/PUT', required: false }
    ],
    handler: 'http',
    handlerFn: httpRequest
  }
]

export function registerBuiltinTools(): void {
  for (const tool of builtinTools) {
    registerTool(tool)
  }
}
