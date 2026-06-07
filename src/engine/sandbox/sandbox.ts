import { nanoid } from 'nanoid'

export interface SandboxConfig {
  workflowId: string
  runId?: string
  type?: 'tempdir' | 'docker'
  env?: Record<string, string>
  allowedCommands?: string[]
  maxMemoryMb?: number
  maxCpuPercent?: number
}

export interface ExecResult {
  stdout: string
  stderr: string
  exitCode: number
  durationMs: number
}

export interface ExecOptions {
  timeoutMs?: number
  cwd?: string
  env?: Record<string, string>
  maxBuffer?: number
}

export interface SandboxSnapshot {
  id: string
  files: Array<{ path: string; content: string }>
  env: Record<string, string>
  createdAt: number
}

export class Sandbox {
  readonly id: string
  readonly workflowId: string
  readonly runId: string
  readonly rootPath: string
  private env: Record<string, string>
  private allowedCommands: string[]
  private destroyed = false

  constructor(config: SandboxConfig) {
    this.id = nanoid(10)
    this.workflowId = config.workflowId
    this.runId = config.runId || nanoid(10)
    this.rootPath = '' // Set in create()
    this.env = { ...config.env }
    this.allowedCommands = config.allowedCommands || []
  }

  async create(): Promise<void> {
    const fs = await import('fs/promises')
    const os = await import('os')
    const path = await import('path')

    const baseDir = path.join(os.tmpdir(), 'evoflux-sandboxes', this.workflowId, this.runId)
    await fs.mkdir(baseDir, { recursive: true })
    await fs.mkdir(path.join(baseDir, 'src'), { recursive: true })
    await fs.mkdir(path.join(baseDir, 'output'), { recursive: true })
    await fs.mkdir(path.join(baseDir, 'temp'), { recursive: true })

    // @ts-expect-error - assign after construction
    this.rootPath = baseDir
  }

  async destroy(): Promise<void> {
    if (this.destroyed) return
    this.destroyed = true
    try {
      const fs = await import('fs/promises')
      await fs.rm(this.rootPath, { recursive: true, force: true })
    } catch {
      // Best effort cleanup
    }
  }

  // Filesystem operations
  async readFile(filePath: string): Promise<string> {
    this.assertNotDestroyed()
    const fs = await import('fs/promises')
    const fullPath = this.resolvePath(filePath)
    return fs.readFile(fullPath, 'utf-8')
  }

  async writeFile(filePath: string, content: string): Promise<void> {
    this.assertNotDestroyed()
    const fs = await import('fs/promises')
    const path = await import('path')
    const fullPath = this.resolvePath(filePath)
    await fs.mkdir(path.dirname(fullPath), { recursive: true })
    await fs.writeFile(fullPath, content, 'utf-8')
  }

  async listDir(dirPath: string = ''): Promise<string[]> {
    this.assertNotDestroyed()
    const fs = await import('fs/promises')
    const fullPath = this.resolvePath(dirPath)
    return fs.readdir(fullPath)
  }

  async exists(filePath: string): Promise<boolean> {
    try {
      const fs = await import('fs/promises')
      await fs.access(this.resolvePath(filePath))
      return true
    } catch {
      return false
    }
  }

  async stat(filePath: string): Promise<{ size: number; isFile: boolean; isDir: boolean }> {
    this.assertNotDestroyed()
    const fs = await import('fs/promises')
    const s = await fs.stat(this.resolvePath(filePath))
    return { size: s.size, isFile: s.isFile(), isDir: s.isDirectory() }
  }

  async deleteFile(filePath: string): Promise<void> {
    this.assertNotDestroyed()
    const fs = await import('fs/promises')
    await fs.unlink(this.resolvePath(filePath))
  }

  // Process execution
  async exec(command: string, options: ExecOptions = {}): Promise<ExecResult> {
    this.assertNotDestroyed()
    this.checkCommandAllowed(command)

    const { execFile } = await import('child_process')
    const { promisify } = await import('util')
    const execFileAsync = promisify(execFile)

    const timeoutMs = options.timeoutMs || 30000
    const maxBuffer = options.maxBuffer || 10 * 1024 * 1024

    const startTime = Date.now()
    try {
      const isWin = process.platform === 'win32'
      const shell = isWin ? 'cmd.exe' : '/bin/sh'
      const shellArgs = isWin ? ['/c', command] : ['-c', command]

      const { stdout, stderr } = await execFileAsync(shell, shellArgs, {
        cwd: options.cwd || this.rootPath,
        env: { PATH: process.env.PATH, HOME: process.env.HOME, ...this.env, ...options.env },
        timeout: timeoutMs,
        maxBuffer
      })

      return {
        stdout: stdout?.toString() || '',
        stderr: stderr?.toString() || '',
        exitCode: 0,
        durationMs: Date.now() - startTime
      }
    } catch (error: unknown) {
      const err = error as { stdout?: string; stderr?: string; code?: number; message?: string }
      return {
        stdout: err.stdout?.toString() || '',
        stderr: err.stderr?.toString() || err.message || 'Command failed',
        exitCode: err.code ?? 1,
        durationMs: Date.now() - startTime
      }
    }
  }

  async execCode(language: 'python' | 'javascript' | 'js' | 'py', code: string, input?: string): Promise<ExecResult> {
    this.assertNotDestroyed()
    const path = await import('path')

    const lang = language === 'js' ? 'javascript' : language === 'py' ? 'python' : language
    const ext = lang === 'python' ? '.py' : '.js'
    const fileName = `script_${nanoid(6)}${ext}`
    const filePath = path.join(this.rootPath, 'temp', fileName)

    await this.writeFile(`temp/${fileName}`, code)

    let command: string
    if (lang === 'python') {
      command = `python ${filePath}`
    } else {
      command = `node ${filePath}`
    }

    const result = await this.exec(command, {
      timeoutMs: 30000,
      env: input ? { EVOLUX_INPUT: input } : undefined
    })

    // Cleanup
    try { await this.deleteFile(`temp/${fileName}`) } catch { /* ignore */ }

    return result
  }

  // Environment
  setEnv(key: string, value: string): void {
    this.env[key] = value
  }

  getEnv(key: string): string | undefined {
    return this.env[key]
  }

  getAllEnv(): Record<string, string> {
    return { ...this.env }
  }

  // Snapshot
  async snapshot(): Promise<SandboxSnapshot> {
    this.assertNotDestroyed()
    const fs = await import('fs/promises')
    const path = await import('path')

    const files: Array<{ path: string; content: string }> = []

    async function walk(dir: string, relativeTo: string) {
      const entries = await fs.readdir(dir, { withFileTypes: true })
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name)
        const relPath = path.relative(relativeTo, fullPath)
        if (entry.isDirectory()) {
          await walk(fullPath, relativeTo)
        } else {
          try {
            const content = await fs.readFile(fullPath, 'utf-8')
            files.push({ path: relPath, content })
          } catch {
            // Skip binary files
          }
        }
      }
    }

    await walk(this.rootPath, this.rootPath)

    return {
      id: nanoid(10),
      files,
      env: { ...this.env },
      createdAt: Date.now()
    }
  }

  async restore(snapshot: SandboxSnapshot): Promise<void> {
    this.assertNotDestroyed()
    for (const file of snapshot.files) {
      await this.writeFile(file.path, file.content)
    }
    this.env = { ...snapshot.env }
  }

  // Helpers
  private resolvePath(filePath: string): string {
    const path = require('path')
    const resolved = path.resolve(this.rootPath, filePath)
    // Prevent path traversal — resolved path must be within rootPath
    if (!resolved.startsWith(this.rootPath + path.sep) && resolved !== this.rootPath) {
      throw new Error(`Path traversal detected: ${filePath}`)
    }
    return resolved
  }

  private assertNotDestroyed(): void {
    if (this.destroyed) throw new Error('Sandbox has been destroyed')
  }

  private checkCommandAllowed(command: string): void {
    if (this.allowedCommands.length === 0) return
    const cmd = command.trim().split(/\s+/)[0]
    if (!this.allowedCommands.includes(cmd)) {
      throw new Error(`Command not allowed: ${cmd}. Allowed: ${this.allowedCommands.join(', ')}`)
    }
  }
}

// Sandbox manager — one sandbox per workflow run
const activeSandboxes = new Map<string, Sandbox>()

export async function createSandbox(config: SandboxConfig): Promise<Sandbox> {
  const key = `${config.workflowId}:${config.runId || 'default'}`
  if (activeSandboxes.has(key)) {
    return activeSandboxes.get(key)!
  }
  const sandbox = new Sandbox(config)
  await sandbox.create()
  activeSandboxes.set(key, sandbox)
  return sandbox
}

export function getSandbox(workflowId: string, runId?: string): Sandbox | undefined {
  const key = `${workflowId}:${runId || 'default'}`
  return activeSandboxes.get(key)
}

export async function destroySandbox(workflowId: string, runId?: string): Promise<void> {
  const key = `${workflowId}:${runId || 'default'}`
  const sandbox = activeSandboxes.get(key)
  if (sandbox) {
    await sandbox.destroy()
    activeSandboxes.delete(key)
  }
}

export async function destroyAllSandboxes(): Promise<void> {
  for (const sandbox of activeSandboxes.values()) {
    await sandbox.destroy()
  }
  activeSandboxes.clear()
}
