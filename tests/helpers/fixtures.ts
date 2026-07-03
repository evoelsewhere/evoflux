import { mkdtemp, writeFile, mkdir, rm } from 'fs/promises'
import { join } from 'path'
import { tmpdir } from 'os'

export interface TestFixture {
  dir: string
  cleanup: () => Promise<void>
}

export async function createTempProject(files: Record<string, string>): Promise<TestFixture> {
  const dir = await mkdtemp(join(tmpdir(), 'evolux-test-'))

  for (const [relativePath, content] of Object.entries(files)) {
    const fullPath = join(dir, relativePath)
    const { dirname } = await import('path')
    await mkdir(dirname(fullPath), { recursive: true })
    await writeFile(fullPath, content, 'utf-8')
  }

  return {
    dir,
    cleanup: () => rm(dir, { recursive: true, force: true }),
  }
}

export async function createCodeProject(): Promise<TestFixture> {
  return createTempProject({
    'index.ts': 'import { greet } from "./src/greeter"\nconsole.log(greet("World"))',
    'src/greeter.ts': 'export function greet(name: string): string {\n  return `Hello, ${name}!`\n}',
    'src/utils.ts': 'export function add(a: number, b: number): number {\n  return a + b\n}',
    'README.md': '# Test Project\n\nA test project for integration testing.',
    'package.json': '{"name": "test", "version": "1.0.0"}',
    '.gitignore': 'node_modules\ndist',
  })
}
