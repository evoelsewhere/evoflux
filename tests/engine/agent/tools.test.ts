import { describe, it, expect, beforeAll } from 'vitest'
import { registerTool, getTool, getAllTools, hasTool, checkPermission, checkShellPermission, checkFilePermission, type AgentTool } from '../../../src/engine/agent/tools'
import { registerBuiltinTools } from '../../../src/engine/agent/builtin-tools'

describe('AgentTools', () => {
  beforeAll(() => {
    registerBuiltinTools()
  })

  it('should register built-in tools', () => {
    expect(hasTool('run_code')).toBe(true)
    expect(hasTool('run_command')).toBe(true)
    expect(hasTool('read_file')).toBe(true)
    expect(hasTool('write_file')).toBe(true)
    expect(hasTool('search_memory')).toBe(true)
    expect(hasTool('http_request')).toBe(true)
  })

  it('should get tool by name', () => {
    const tool = getTool('run_code')
    expect(tool).toBeDefined()
    expect(tool!.name).toBe('run_code')
    expect(tool!.handler).toBe('sandbox_code')
    expect(tool!.parameters.length).toBeGreaterThan(0)
  })

  it('should get all tools', () => {
    const tools = getAllTools()
    expect(tools.length).toBeGreaterThanOrEqual(6)
  })

  it('should register custom tool', () => {
    const customTool: AgentTool = {
      name: 'my_custom_tool',
      description: 'A custom tool',
      parameters: [{ name: 'input', type: 'string', description: 'Input', required: true }],
      handler: 'custom',
      handlerFn: async (args) => `Custom: ${args.input}`
    }
    registerTool(customTool)
    expect(hasTool('my_custom_tool')).toBe(true)
  })

  it('should check permission — blocked tool', () => {
    const tool = getTool('run_code')!
    expect(() => checkPermission(tool, { blockedTools: ['run_code'] })).toThrow()
  })

  it('should check permission — allowed tool', () => {
    const tool = getTool('run_code')!
    expect(() => checkPermission(tool, { allowedTools: ['run_code', 'read_file'] })).not.toThrow()
  })

  it('should check permission — tool not in allowed list', () => {
    const tool = getTool('run_code')!
    expect(() => checkPermission(tool, { allowedTools: ['read_file'] })).toThrow()
  })

  it('should check shell permission — blocked command', () => {
    expect(() => checkShellPermission('rm -rf /', { blockedShellCommands: ['rm'] })).toThrow()
  })

  it('should check shell permission — allowed command', () => {
    expect(() => checkShellPermission('ls -la', { allowedShellCommands: ['ls', 'cat'] })).not.toThrow()
  })

  it('should check file permission — blocked pattern', () => {
    expect(() => checkFilePermission('/etc/passwd', { blockedFilePatterns: ['/etc'] })).toThrow()
  })

  it('should execute read_file tool', async () => {
    const tool = getTool('read_file')!
    // Use the tool which creates its own sandbox
    const result = await tool.handlerFn!({ path: 'test.txt' }, { pool: undefined as any, nodeId: 'read-tool-test' })
    // File doesn't exist in sandbox, so we get an error
    expect(result).toContain('Error')
  })
})
