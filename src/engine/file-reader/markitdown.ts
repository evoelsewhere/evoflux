import { detectFileType, getFileName, type FileCategory } from './file-detector'

export interface MarkitdownResult {
  content: string
  title?: string
  convertedBy: 'markitdown' | 'plain_text' | 'binary_skip'
}

const MARKITDOWN_CATEGORIES: FileCategory[] = ['office', 'pdf', 'image', 'audio', 'archive', 'web', 'data']

export async function convertFile(filePath: string, options?: { useMarkitdown?: boolean }): Promise<MarkitdownResult> {
  const info = detectFileType(filePath)
  const fileName = getFileName(filePath)

  if (info.parser === 'skip') {
    return { content: `[Binary file: ${fileName}]`, convertedBy: 'binary_skip' }
  }

  if (info.parser === 'plain') {
    return readPlainText(filePath)
  }

  if (info.parser === 'markdown') {
    return readPlainText(filePath)
  }

  if (info.parser === 'csv') {
    return readPlainText(filePath)
  }

  if (info.parser === 'markitdown' || (options?.useMarkitdown && MARKITDOWN_CATEGORIES.includes(info.category))) {
    return convertViaMarkitdown(filePath)
  }

  return readPlainText(filePath)
}

async function readPlainText(filePath: string): Promise<MarkitdownResult> {
  try {
    const fs = await import('fs/promises')
    const content = await fs.readFile(filePath, 'utf-8')
    return { content, convertedBy: 'plain_text' }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Read failed'
    return { content: `[Error reading file: ${message}]`, convertedBy: 'plain_text' }
  }
}

async function convertViaMarkitdown(filePath: string): Promise<MarkitdownResult> {
  try {
    const { execFile } = await import('child_process')
    const { promisify } = await import('util')
    const execFileAsync = promisify(execFile)

    const { stdout } = await execFileAsync('markitdown', [filePath], {
      timeout: 30000,
      maxBuffer: 50 * 1024 * 1024
    })

    return { content: stdout, convertedBy: 'markitdown' }
  } catch {
    // Fallback: try Python API
    try {
      return await convertViaPython(filePath)
    } catch {
      return readPlainText(filePath)
    }
  }
}

async function convertViaPython(filePath: string): Promise<MarkitdownResult> {
  const { execFile } = await import('child_process')
  const { promisify } = await import('util')
  const execFileAsync = promisify(execFile)

  const script = `
import sys
from markitdown import MarkItDown
md = MarkItDown()
result = md.convert(sys.argv[1])
print(result.text_content)
`
  const { stdout } = await execFileAsync('python', ['-c', script, filePath], {
    timeout: 30000,
    maxBuffer: 50 * 1024 * 1024
  })

  return { content: stdout, convertedBy: 'markitdown' }
}

export function isMarkitdownAvailable(): Promise<boolean> {
  return new Promise((resolve) => {
    const { execFile } = require('child_process')
    execFile('markitdown', ['--version'], { timeout: 5000 }, (error: Error | null) => {
      resolve(!error)
    })
  })
}
