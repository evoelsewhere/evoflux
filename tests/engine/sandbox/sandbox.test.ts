import { describe, it, expect, afterAll } from 'vitest'
import { Sandbox, createSandbox, destroyAllSandboxes } from '../../../src/engine/sandbox/sandbox'

describe('Sandbox', () => {
  afterAll(async () => {
    await destroyAllSandboxes()
  })

  it('should create sandbox with temp directories', async () => {
    const sandbox = new Sandbox({ workflowId: 'test-wf', runId: 'test-run' })
    await sandbox.create()
    expect(sandbox.rootPath).toBeTruthy()

    const exists = await sandbox.exists('src')
    expect(exists).toBe(true)

    const outExists = await sandbox.exists('output')
    expect(outExists).toBe(true)

    await sandbox.destroy()
  })

  it('should write and read files', async () => {
    const sandbox = new Sandbox({ workflowId: 'test-wf', runId: 'wr-test' })
    await sandbox.create()

    await sandbox.writeFile('src/test.txt', 'Hello World')
    const content = await sandbox.readFile('src/test.txt')
    expect(content).toBe('Hello World')

    await sandbox.destroy()
  })

  it('should list directory contents', async () => {
    const sandbox = new Sandbox({ workflowId: 'test-wf', runId: 'ls-test' })
    await sandbox.create()

    await sandbox.writeFile('src/a.txt', 'a')
    await sandbox.writeFile('src/b.txt', 'b')

    const files = await sandbox.listDir('src')
    expect(files).toContain('a.txt')
    expect(files).toContain('b.txt')

    await sandbox.destroy()
  })

  it('should check file existence', async () => {
    const sandbox = new Sandbox({ workflowId: 'test-wf', runId: 'exists-test' })
    await sandbox.create()

    expect(await sandbox.exists('src/nonexistent.txt')).toBe(false)
    await sandbox.writeFile('src/exists.txt', 'yes')
    expect(await sandbox.exists('src/exists.txt')).toBe(true)

    await sandbox.destroy()
  })

  it('should get file stats', async () => {
    const sandbox = new Sandbox({ workflowId: 'test-wf', runId: 'stat-test' })
    await sandbox.create()

    await sandbox.writeFile('src/file.txt', 'content')
    const stat = await sandbox.stat('src/file.txt')
    expect(stat.isFile).toBe(true)
    expect(stat.isDir).toBe(false)
    expect(stat.size).toBeGreaterThan(0)

    await sandbox.destroy()
  })

  it('should delete files', async () => {
    const sandbox = new Sandbox({ workflowId: 'test-wf', runId: 'del-test' })
    await sandbox.create()

    await sandbox.writeFile('temp/del.txt', 'delete me')
    expect(await sandbox.exists('temp/del.txt')).toBe(true)

    await sandbox.deleteFile('temp/del.txt')
    expect(await sandbox.exists('temp/del.txt')).toBe(false)

    await sandbox.destroy()
  })

  it('should execute JavaScript code', async () => {
    const sandbox = new Sandbox({ workflowId: 'test-wf', runId: 'js-test' })
    await sandbox.create()

    const result = await sandbox.execCode('javascript', 'console.log("Hello from JS")')
    expect(result.stdout.trim()).toBe('Hello from JS')
    expect(result.exitCode).toBe(0)

    await sandbox.destroy()
  })

  it('should handle code errors', async () => {
    const sandbox = new Sandbox({ workflowId: 'test-wf', runId: 'err-test' })
    await sandbox.create()

    const result = await sandbox.execCode('javascript', 'throw new Error("test error")')
    expect(result.stderr).toContain('test error')
    expect(result.exitCode).not.toBe(0)

    await sandbox.destroy()
  })

  it('should execute shell commands', async () => {
    const sandbox = new Sandbox({ workflowId: 'test-wf', runId: 'shell-test' })
    await sandbox.create()

    const result = await sandbox.exec('echo hello')
    expect(result.stdout.trim()).toBe('hello')
    expect(result.exitCode).toBe(0)

    await sandbox.destroy()
  })

  it('should manage environment variables', async () => {
    const sandbox = new Sandbox({ workflowId: 'test-wf', runId: 'env-test' })
    await sandbox.create()

    sandbox.setEnv('MY_VAR', 'test_value')
    expect(sandbox.getEnv('MY_VAR')).toBe('test_value')

    const allEnv = sandbox.getAllEnv()
    expect(allEnv.MY_VAR).toBe('test_value')

    await sandbox.destroy()
  })

  it('should prevent path traversal', async () => {
    const sandbox = new Sandbox({ workflowId: 'test-wf', runId: 'traversal-test' })
    await sandbox.create()

    await expect(sandbox.readFile('../../../etc/passwd')).rejects.toThrow('Path traversal')
    await expect(sandbox.writeFile('../../../tmp/hacked.txt', 'bad')).rejects.toThrow('Path traversal')

    await sandbox.destroy()
  })

  it('should take and restore snapshots', async () => {
    const sandbox = new Sandbox({ workflowId: 'test-wf', runId: 'snap-test' })
    await sandbox.create()

    await sandbox.writeFile('src/data.txt', 'original data')
    const snapshot = await sandbox.snapshot()

    await sandbox.writeFile('src/data.txt', 'modified data')
    expect(await sandbox.readFile('src/data.txt')).toBe('modified data')

    await sandbox.restore(snapshot)
    expect(await sandbox.readFile('src/data.txt')).toBe('original data')

    await sandbox.destroy()
  })

  it('should use sandbox manager', async () => {
    const sb1 = await createSandbox({ workflowId: 'wf1', runId: 'run1' })
    const sb2 = await createSandbox({ workflowId: 'wf1', runId: 'run1' })
    expect(sb1.id).toBe(sb2.id) // Same instance

    const sb3 = await createSandbox({ workflowId: 'wf1', runId: 'run2' })
    expect(sb1.id).not.toBe(sb3.id) // Different run

    await sb1.destroy()
    await sb3.destroy()
  })
})
