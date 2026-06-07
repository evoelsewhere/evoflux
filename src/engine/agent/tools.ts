import type { VariablePool } from '../variable-pool'

export type ToolHandlerType = 'sandbox_code' | 'sandbox_shell' | 'file_read' | 'file_write' | 'memory_search' | 'http' | 'custom'

export interface ToolParameter {
  name: string
  type: 'string' | 'number' | 'boolean' | 'object' | 'array'
  description: string
  required: boolean
}

export interface AgentTool {
  name: string
  description: string
  parameters: ToolParameter[]
  handler: ToolHandlerType
  handlerFn?: (args: Record<string, unknown>, context: ToolContext) => Promise<string>
}

export interface ToolContext {
  pool: VariablePool
  nodeId: string
  signal?: AbortSignal
  sandbox?: unknown
  memory?: unknown
}

export interface ToolPermission {
  allowedTools?: string[]
  blockedTools?: string[]
  allowedShellCommands?: string[]
  blockedShellCommands?: string[]
  allowedFilePatterns?: string[]
  blockedFilePatterns?: string[]
  maxFileSizeBytes?: number
}

export interface ToolResult {
  success: boolean
  output: string
  error?: string
}

const toolRegistry = new Map<string, AgentTool>()

export function registerTool(tool: AgentTool): void {
  toolRegistry.set(tool.name, tool)
}

export function getTool(name: string): AgentTool | undefined {
  return toolRegistry.get(name)
}

export function getAllTools(): AgentTool[] {
  return Array.from(toolRegistry.values())
}

export function getToolNames(): string[] {
  return Array.from(toolRegistry.keys())
}

export function hasTool(name: string): boolean {
  return toolRegistry.has(name)
}

export function checkPermission(tool: AgentTool, permission: ToolPermission): void {
  if (permission.blockedTools?.includes(tool.name)) {
    throw new Error(`Tool '${tool.name}' is blocked by permission policy`)
  }
  if (permission.allowedTools && !permission.allowedTools.includes(tool.name)) {
    throw new Error(`Tool '${tool.name}' is not in allowed tools list`)
  }
}

export function checkShellPermission(command: string, permission: ToolPermission): void {
  if (permission.blockedShellCommands?.some(cmd => command.startsWith(cmd))) {
    throw new Error(`Shell command blocked: '${command.split(' ')[0]}'`)
  }
  if (permission.allowedShellCommands && !permission.allowedShellCommands.some(cmd => command.startsWith(cmd))) {
    throw new Error(`Shell command not allowed: '${command.split(' ')[0]}'`)
  }
}

export function checkFilePermission(filePath: string, permission: ToolPermission): void {
  if (permission.blockedFilePatterns?.some(pattern => filePath.includes(pattern))) {
    throw new Error(`File path blocked: '${filePath}'`)
  }
}
