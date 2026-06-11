import { readFile, writeFile, stat, readdir } from 'fs/promises'
import { join, relative, dirname } from 'path'
import { execFile } from 'child_process'
import { promisify } from 'util'

const execFileAsync = promisify(execFile)

export interface ToolResult {
  success: boolean
  output: string
  error?: string
}

export interface ToolContext {
  workingDir: string
  readFile: (path: string) => Promise<string>
  writeFile: (path: string, content: string) => Promise<void>
  editFile: (path: string, oldText: string, newText: string) => Promise<ToolResult>
  bash: (command: string, timeout?: number) => Promise<ToolResult>
  grep: (pattern: string, path?: string, include?: string) => Promise<ToolResult>
  find: (pattern: string, path?: string) => Promise<ToolResult>
  listDir: (path?: string) => Promise<ToolResult>
}

export function createToolContext(workingDir: string): ToolContext {
  return {
    workingDir,

    async readFile(path: string): Promise<string> {
      const fullPath = path.startsWith('/') ? path : join(workingDir, path)
      return await readFile(fullPath, 'utf-8')
    },

    async writeFile(path: string, content: string): Promise<void> {
      const fullPath = path.startsWith('/') ? path : join(workingDir, path)
      await writeFile(fullPath, content, 'utf-8')
    },

    async editFile(path: string, oldText: string, newText: string): Promise<ToolResult> {
      try {
        const fullPath = path.startsWith('/') ? path : join(workingDir, path)
        const content = await readFile(fullPath, 'utf-8')
        if (!content.includes(oldText)) {
          return { success: false, output: '', error: `Text not found in ${path}` }
        }
        const newContent = content.replace(oldText, newText)
        await writeFile(fullPath, newContent, 'utf-8')
        return { success: true, output: `Edited ${path}` }
      } catch (e) {
        return { success: false, output: '', error: (e as Error).message }
      }
    },

    async bash(command: string, timeout = 30000): Promise<ToolResult> {
      try {
        const { stdout, stderr } = await execFileAsync('bash', ['-c', command], {
          cwd: workingDir,
          timeout,
          maxBuffer: 1024 * 1024 * 10
        })
        return { success: true, output: stdout + (stderr ? `\n[stderr]\n${stderr}` : '') }
      } catch (e: any) {
        return {
          success: false,
          output: (e.stdout || '') + (e.stderr ? `\n[stderr]\n${e.stderr}` : ''),
          error: e.message
        }
      }
    },

    async grep(pattern: string, path?: string, include?: string): Promise<ToolResult> {
      try {
        const args = ['-rn', '--color=never']
        if (include) args.push(`--include=${include}`)
        args.push(pattern)
        args.push(path || '.')
        const { stdout } = await execFileAsync('grep', args, {
          cwd: workingDir,
          timeout: 10000,
          maxBuffer: 1024 * 1024 * 5
        })
        const lines = stdout.trim().split('\n').slice(0, 100)
        return { success: true, output: lines.join('\n') || 'No matches' }
      } catch (e: any) {
        if (e.code === 1) return { success: true, output: 'No matches' }
        return { success: false, output: '', error: e.message }
      }
    },

    async find(pattern: string, path?: string): Promise<ToolResult> {
      try {
        const { stdout } = await execFileAsync('find', [path || '.', '-name', pattern, '-type', 'f'], {
          cwd: workingDir,
          timeout: 10000,
          maxBuffer: 1024 * 1024 * 5
        })
        const files = stdout.trim().split('\n').filter(Boolean).slice(0, 100)
        return { success: true, output: files.join('\n') || 'No files found' }
      } catch (e: any) {
        return { success: false, output: '', error: e.message }
      }
    },

    async listDir(path?: string): Promise<ToolResult> {
      try {
        const targetPath = path ? (path.startsWith('/') ? path : join(workingDir, path)) : workingDir
        const entries = await readdir(targetPath, { withFileTypes: true })
        const lines = entries
          .filter(e => !e.name.startsWith('.'))
          .sort((a, b) => {
            if (a.isDirectory() && !b.isDirectory()) return -1
            if (!a.isDirectory() && b.isDirectory()) return 1
            return a.name.localeCompare(b.name)
          })
          .map(e => `${e.isDirectory() ? '📁' : '📄'} ${e.name}`)
        return { success: true, output: lines.join('\n') || 'Empty directory' }
      } catch (e: any) {
        return { success: false, output: '', error: e.message }
      }
    }
  }
}

export const TOOL_DEFINITIONS = [
  {
    name: 'read_file',
    description: 'Read the contents of a file. Returns the full file content.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'File path relative to working directory or absolute path' }
      },
      required: ['path']
    }
  },
  {
    name: 'write_file',
    description: 'Write content to a file. Creates the file if it does not exist, overwrites if it does.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'File path relative to working directory' },
        content: { type: 'string', description: 'Content to write to the file' }
      },
      required: ['path', 'content']
    }
  },
  {
    name: 'edit_file',
    description: 'Edit a file by replacing exact text. The old_text must match exactly.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'File path' },
        old_text: { type: 'string', description: 'Exact text to find and replace' },
        new_text: { type: 'string', description: 'Replacement text' }
      },
      required: ['path', 'old_text', 'new_text']
    }
  },
  {
    name: 'bash',
    description: 'Execute a bash command. Use for running tests, builds, git commands, etc.',
    parameters: {
      type: 'object',
      properties: {
        command: { type: 'string', description: 'Bash command to execute' },
        timeout: { type: 'number', description: 'Timeout in milliseconds (default: 30000)' }
      },
      required: ['command']
    }
  },
  {
    name: 'grep',
    description: 'Search for a pattern in files. Returns matching lines with file paths and line numbers.',
    parameters: {
      type: 'object',
      properties: {
        pattern: { type: 'string', description: 'Search pattern (regex supported)' },
        path: { type: 'string', description: 'Directory or file to search in (default: current dir)' },
        include: { type: 'string', description: 'File pattern to include (e.g. "*.ts")' }
      },
      required: ['pattern']
    }
  },
  {
    name: 'find',
    description: 'Find files by name pattern.',
    parameters: {
      type: 'object',
      properties: {
        pattern: { type: 'string', description: 'File name pattern (e.g. "*.ts", "README*")' },
        path: { type: 'string', description: 'Directory to search in (default: current dir)' }
      },
      required: ['pattern']
    }
  },
  {
    name: 'list_dir',
    description: 'List files and directories in a path.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'Directory path (default: working directory)' }
      }
    }
  }
]

export async function executeTool(
  name: string,
  args: Record<string, unknown>,
  ctx: ToolContext
): Promise<ToolResult> {
  switch (name) {
    case 'read_file':
      try {
        const content = await ctx.readFile(String(args.path))
        return { success: true, output: content.substring(0, 50000) }
      } catch (e) { return { success: false, output: '', error: (e as Error).message } }

    case 'write_file':
      try {
        await ctx.writeFile(String(args.path), String(args.content))
        return { success: true, output: `Written ${String(args.content).length} chars to ${args.path}` }
      } catch (e) { return { success: false, output: '', error: (e as Error).message } }

    case 'edit_file':
      return await ctx.editFile(String(args.path), String(args.old_text), String(args.new_text))

    case 'bash':
      return await ctx.bash(String(args.command), args.timeout as number | undefined)

    case 'grep':
      return await ctx.grep(
        String(args.pattern),
        args.path ? String(args.path) : undefined,
        args.include ? String(args.include) : undefined
      )

    case 'find':
      return await ctx.find(
        String(args.pattern),
        args.path ? String(args.path) : undefined
      )

    case 'list_dir':
      return await ctx.listDir(args.path ? String(args.path) : undefined)

    default:
      return { success: false, output: '', error: `Unknown tool: ${name}` }
  }
}
