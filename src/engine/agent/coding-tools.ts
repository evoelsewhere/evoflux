import { readFile, writeFile, stat, readdir, access } from 'fs/promises'
import { join, relative, dirname, extname, basename } from 'path'
import { execFile, exec } from 'child_process'
import { promisify } from 'util'

const execFileAsync = promisify(execFile)
const execAsync = promisify(exec)

export interface ToolResult {
  success: boolean
  output: string
  error?: string
}

export interface FileDiff {
  path: string
  oldContent: string | null
  newContent: string
  added: number
  removed: number
}

export interface ToolContext {
  workingDir: string
  filesRead: Set<string>
  filesChanged: Set<string>
  fileDiffs: FileDiff[]
  readFile: (path: string) => Promise<string>
  writeFile: (path: string, content: string) => Promise<void>
  editFile: (path: string, oldText: string, newText: string) => Promise<ToolResult>
  bash: (command: string, timeout?: number) => Promise<ToolResult>
  grep: (pattern: string, path?: string, include?: string) => Promise<ToolResult>
  find: (pattern: string, path?: string) => Promise<ToolResult>
  listDir: (path?: string, depth?: number) => Promise<ToolResult>
  gitCheckpoint: (message: string) => Promise<ToolResult>
  gitDiff: (path?: string) => Promise<ToolResult>
  runTests: (command?: string) => Promise<ToolResult>
  think: (thought: string) => ToolResult
  getFileTree: (maxDepth?: number) => Promise<ToolResult>
}

export function createToolContext(workingDir: string): ToolContext {
  const filesRead = new Set<string>()
  const filesChanged = new Set<string>()
  const fileDiffs: FileDiff[] = []
  const fileSnapshots = new Map<string, string>()

  async function captureSnapshot(path: string): Promise<string | null> {
    try {
      const fullPath = path.startsWith('/') ? path : join(workingDir, path)
      return await readFile(fullPath, 'utf-8')
    } catch { return null }
  }

  function recordDiff(path: string, oldContent: string | null, newContent: string) {
    const oldLines = (oldContent || '').split('\n')
    const newLines = newContent.split('\n')
    let added = 0; let removed = 0
    const maxLen = Math.max(oldLines.length, newLines.length)
    for (let i = 0; i < maxLen; i++) {
      if (i >= oldLines.length) added++
      else if (i >= newLines.length) removed++
      else if (oldLines[i] !== newLines[i]) { added++; removed++ }
    }
    const relPath = path.startsWith('/') ? relative(workingDir, path) : path
    fileDiffs.push({ path: relPath, oldContent, newContent, added, removed })
  }

  return {
    workingDir,
    filesRead,
    filesChanged,
    fileDiffs,

    async readFile(path: string): Promise<string> {
      const fullPath = path.startsWith('/') ? path : join(workingDir, path)
      const content = await readFile(fullPath, 'utf-8')
      const relPath = relative(workingDir, fullPath)
      filesRead.add(relPath)
      if (!fileSnapshots.has(relPath)) fileSnapshots.set(relPath, content)
      return content
    },

    async writeFile(path: string, content: string): Promise<void> {
      const fullPath = path.startsWith('/') ? path : join(workingDir, path)
      const relPath = relative(workingDir, fullPath)
      const oldContent = fileSnapshots.get(relPath) ?? await captureSnapshot(path)
      await writeFile(fullPath, content, 'utf-8')
      filesChanged.add(relPath)
      fileSnapshots.set(relPath, content)
      recordDiff(path, oldContent, content)
    },

    async editFile(path: string, oldText: string, newText: string): Promise<ToolResult> {
      try {
        const fullPath = path.startsWith('/') ? path : join(workingDir, path)
        const content = await readFile(fullPath, 'utf-8')
        if (!content.includes(oldText)) {
          const lines = content.split('\n')
          const similar = lines.filter(l => l.trim().length > 5 && oldText.includes(l.trim().substring(0, 20)))
          const hint = similar.length > 0 ? `\nSimilar lines found:\n${similar.slice(0, 3).join('\n')}` : ''
          return { success: false, output: '', error: `Text not found in ${path}.${hint}\nMake sure old_text matches exactly including whitespace and indentation.` }
        }
        const newContent = content.replace(oldText, newText)
        const relPath = relative(workingDir, fullPath)
        if (!fileSnapshots.has(relPath)) fileSnapshots.set(relPath, content)
        await writeFile(fullPath, newContent, 'utf-8')
        filesChanged.add(relPath)
        recordDiff(path, fileSnapshots.get(relPath) || content, newContent)
        fileSnapshots.set(relPath, newContent)
        return { success: true, output: `Edited ${path} (${oldText.length} chars → ${newText.length} chars)` }
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
        const args = ['-rn', '--color=never', '-C', '2']
        if (include) args.push(`--include=${include}`)
        args.push(pattern)
        args.push(path || '.')
        const { stdout } = await execFileAsync('grep', args, {
          cwd: workingDir,
          timeout: 10000,
          maxBuffer: 1024 * 1024 * 5
        })
        const lines = stdout.trim().split('\n').slice(0, 150)
        return { success: true, output: lines.join('\n') || 'No matches' }
      } catch (e: any) {
        if (e.code === 1) return { success: true, output: 'No matches' }
        return { success: false, output: '', error: e.message }
      }
    },

    async find(pattern: string, path?: string): Promise<ToolResult> {
      try {
        const { stdout } = await execFileAsync('find', [path || '.', '-name', pattern, '-type', 'f', '-not', 'path', '*/node_modules/*', '-not', 'path', '*/.git/*'], {
          cwd: workingDir,
          timeout: 10000,
          maxBuffer: 1024 * 1024 * 5
        })
        const files = stdout.trim().split('\n').filter(Boolean).slice(0, 200)
        return { success: true, output: files.join('\n') || 'No files found' }
      } catch (e: any) {
        return { success: false, output: '', error: e.message }
      }
    },

    async listDir(path?: string, depth = 1): Promise<ToolResult> {
      try {
        const targetPath = path ? (path.startsWith('/') ? path : join(workingDir, path)) : workingDir
        const entries = await readdir(targetPath, { withFileTypes: true })
        const lines: string[] = []
        for (const e of entries) {
          if (e.name.startsWith('.') || e.name === 'node_modules') continue
          if (e.isDirectory()) {
            lines.push(`📁 ${e.name}/`)
            if (depth > 1) {
              try {
                const sub = await readdir(join(targetPath, e.name), { withFileTypes: true })
                for (const s of sub.slice(0, 10)) {
                  if (s.name.startsWith('.')) continue
                  lines.push(`  ${s.isDirectory() ? '📁' : '📄'} ${s.name}`)
                }
                if (sub.length > 10) lines.push(`  ... +${sub.length - 10} more`)
              } catch { /* skip */ }
            }
          } else {
            lines.push(`📄 ${e.name}`)
          }
        }
        return { success: true, output: lines.join('\n') || 'Empty directory' }
      } catch (e: any) {
        return { success: false, output: '', error: e.message }
      }
    },

    async gitCheckpoint(message: string): Promise<ToolResult> {
      try {
        await execFileAsync('git', ['add', '-A'], { cwd: workingDir, timeout: 10000 })
        const { stdout: status } = await execFileAsync('git', ['status', '--porcelain'], { cwd: workingDir, timeout: 5000 })
        if (!status.trim()) return { success: true, output: 'No changes to commit' }
        await execFileAsync('git', ['commit', '-m', `[agent] ${message}`], { cwd: workingDir, timeout: 10000 })
        const { stdout: hash } = await execFileAsync('git', ['rev-parse', '--short', 'HEAD'], { cwd: workingDir, timeout: 5000 })
        return { success: true, output: `Committed: ${hash.trim()} — ${message}` }
      } catch (e: any) {
        return { success: false, output: '', error: e.message }
      }
    },

    async gitDiff(path?: string): Promise<ToolResult> {
      try {
        const args = ['diff', '--stat']
        if (path) args.push('--', path)
        const { stdout } = await execFileAsync('git', args, { cwd: workingDir, timeout: 10000 })
        return { success: true, output: stdout || 'No changes' }
      } catch (e: any) {
        return { success: false, output: '', error: e.message }
      }
    },

    async runTests(command?: string): Promise<ToolResult> {
      const testCmd = command || 'npm test'
      return await this.bash(testCmd, 60000)
    },

    think(thought: string): ToolResult {
      return { success: true, output: `[Thinking]\n${thought}` }
    },

    async getFileTree(maxDepth = 3): Promise<ToolResult> {
      try {
        const { stdout } = await execFileAsync('find', ['.', '-maxdepth', String(maxDepth), '-not', 'path', '*/node_modules/*', '-not', 'path', '*/.git/*', '-not', 'path', '*/dist/*', '-not', 'path', '*/.next/*'], {
          cwd: workingDir,
          timeout: 10000,
          maxBuffer: 1024 * 1024 * 2
        })
        const lines = stdout.trim().split('\n').filter(Boolean).slice(0, 300)
        return { success: true, output: lines.join('\n') }
      } catch (e: any) {
        return { success: false, output: '', error: e.message }
      }
    }
  }
}

export const TOOL_DEFINITIONS = [
  {
    name: 'read_file',
    description: 'Read the contents of a file. Returns the full file content with line numbers.',
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
    description: 'Edit a file by replacing exact text. The old_text must match exactly including whitespace and indentation. Use read_file first to see the exact content.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'File path' },
        old_text: { type: 'string', description: 'Exact text to find and replace (must match file content exactly)' },
        new_text: { type: 'string', description: 'Replacement text' }
      },
      required: ['path', 'old_text', 'new_text']
    }
  },
  {
    name: 'bash',
    description: 'Execute a bash command. Use for running tests, builds, git commands, installing packages, etc.',
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
    description: 'Search for a pattern in files. Returns matching lines with file paths, line numbers, and context.',
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
    description: 'Find files by name pattern. Excludes node_modules and .git by default.',
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
    description: 'List files and directories in a path. Shows directory structure.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'Directory path (default: working directory)' },
        depth: { type: 'number', description: 'Directory depth to show (default: 1)' }
      }
    }
  },
  {
    name: 'git_checkpoint',
    description: 'Create a git checkpoint (commit) of current changes. Use before risky changes to enable rollback.',
    parameters: {
      type: 'object',
      properties: {
        message: { type: 'string', description: 'Commit message describing the checkpoint' }
      },
      required: ['message']
    }
  },
  {
    name: 'git_diff',
    description: 'Show git diff of current changes. Useful to verify what you changed.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'Specific file to diff (optional, shows all changes if omitted)' }
      }
    }
  },
  {
    name: 'run_tests',
    description: 'Run the project test suite. Uses npm test by default.',
    parameters: {
      type: 'object',
      properties: {
        command: { type: 'string', description: 'Custom test command (default: npm test)' }
      }
    }
  },
  {
    name: 'think',
    description: 'Use this tool to think through a problem, plan your approach, or reason about the code. This helps you organize your thoughts before making changes.',
    parameters: {
      type: 'object',
      properties: {
        thought: { type: 'string', description: 'Your thinking process, analysis, or plan' }
      },
      required: ['thought']
    }
  },
  {
    name: 'get_file_tree',
    description: 'Get the project file tree structure. Useful for understanding the codebase layout.',
    parameters: {
      type: 'object',
      properties: {
        max_depth: { type: 'number', description: 'Maximum directory depth (default: 3)' }
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
        const lines = content.split('\n')
        const numbered = lines.map((l, i) => `${i + 1}: ${l}`).join('\n')
        return { success: true, output: numbered.substring(0, 50000) }
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
      return await ctx.listDir(
        args.path ? String(args.path) : undefined,
        args.depth as number | undefined
      )

    case 'git_checkpoint':
      return await ctx.gitCheckpoint(String(args.message))

    case 'git_diff':
      return await ctx.gitDiff(args.path ? String(args.path) : undefined)

    case 'run_tests':
      return await ctx.runTests(args.command ? String(args.command) : undefined)

    case 'think':
      return ctx.think(String(args.thought))

    case 'get_file_tree':
      return await ctx.getFileTree(args.max_depth as number | undefined)

    default:
      return { success: false, output: '', error: `Unknown tool: ${name}` }
  }
}
