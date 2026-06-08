import { execFile } from 'child_process'
import { promisify } from 'util'
import { createHash } from 'crypto'
import { watch } from 'fs'
import { join } from 'path'

const execFileAsync = promisify(execFile)

export interface GitInfo {
  isRepo: boolean
  repoPath?: string
  branch?: string
  commitHash?: string
}

export interface ChangedFile {
  status: 'M' | 'A' | 'D' | 'R' | 'C' | '?'
  path: string
  oldPath?: string
}

export async function detectGitRepo(path: string): Promise<GitInfo> {
  try {
    const { stdout } = await execFileAsync('git', ['-C', path, 'rev-parse', '--git-dir'], { timeout: 5000 })
    const gitDir = stdout.trim()
    const repoPath = gitDir === '.git' ? path : gitDir.replace(/\/\.git$/, '')

    const [branchResult, commitResult] = await Promise.all([
      execFileAsync('git', ['-C', path, 'branch', '--show-current'], { timeout: 5000 }).catch(() => ({ stdout: '' })),
      execFileAsync('git', ['-C', path, 'rev-parse', 'HEAD'], { timeout: 5000 }).catch(() => ({ stdout: '' }))
    ])

    return {
      isRepo: true,
      repoPath,
      branch: branchResult.stdout.trim() || undefined,
      commitHash: commitResult.stdout.trim().substring(0, 8) || undefined
    }
  } catch {
    return { isRepo: false }
  }
}

export async function getCurrentBranch(path: string): Promise<string> {
  try {
    const { stdout } = await execFileAsync('git', ['-C', path, 'branch', '--show-current'], { timeout: 5000 })
    return stdout.trim() || 'HEAD'
  } catch {
    return 'HEAD'
  }
}

export async function getCurrentCommit(path: string): Promise<string> {
  try {
    const { stdout } = await execFileAsync('git', ['-C', path, 'rev-parse', 'HEAD'], { timeout: 5000 })
    return stdout.trim()
  } catch {
    return ''
  }
}

export async function getChangedFiles(path: string, sinceCommit?: string): Promise<ChangedFile[]> {
  try {
    const args = ['-C', path, 'diff', '--name-status']
    if (sinceCommit) args.push(`${sinceCommit}..HEAD`)
    else args.push('HEAD')

    const { stdout } = await execFileAsync('git', args, { timeout: 15000 })
    if (!stdout.trim()) return []

    return stdout.trim().split('\n').map(line => {
      const parts = line.split('\t')
      const status = parts[0] as ChangedFile['status']
      const filePath = parts[parts.length - 1]
      return {
        status: status === 'R' ? 'M' : status,
        path: filePath,
        oldPath: parts.length > 2 ? parts[1] : undefined
      }
    }).filter(f => f.path)
  } catch {
    return []
  }
}

export async function getFileDiff(path: string, filePath: string, sinceCommit?: string): Promise<string> {
  try {
    const args = ['-C', path, 'diff']
    if (sinceCommit) args.push(sinceCommit)
    args.push('--', filePath)

    const { stdout } = await execFileAsync('git', args, { timeout: 15000 })
    return stdout
  } catch {
    return ''
  }
}

export async function getFileContentAtCommit(path: string, filePath: string, commit: string): Promise<string> {
  try {
    const { stdout } = await execFileAsync('git', ['-C', path, 'show', `${commit}:${filePath}`], { timeout: 10000 })
    return stdout
  } catch {
    return ''
  }
}

export function getContentHash(content: string): string {
  return createHash('md5').update(content).digest('hex')
}

export async function getDiffStats(path: string, sinceCommit?: string): Promise<{ filesChanged: number; insertions: number; deletions: number }> {
  try {
    const args = ['-C', path, 'diff', '--stat']
    if (sinceCommit) args.push(`${sinceCommit}..HEAD`)

    const { stdout } = await execFileAsync('git', args, { timeout: 10000 })
    const summaryLine = stdout.trim().split('\n').pop() || ''
    const fileMatch = summaryLine.match(/(\d+) files? changed/)
    const insertMatch = summaryLine.match(/(\d+) insertions?/)
    const deleteMatch = summaryLine.match(/(\d+) deletions?/)

    return {
      filesChanged: fileMatch ? parseInt(fileMatch[1]) : 0,
      insertions: insertMatch ? parseInt(insertMatch[1]) : 0,
      deletions: deleteMatch ? parseInt(deleteMatch[1]) : 0
    }
  } catch {
    return { filesChanged: 0, insertions: 0, deletions: 0 }
  }
}

export function watchGitRepo(repoPath: string, callback: () => void): () => void {
  const gitDir = join(repoPath, '.git')
  const refsDir = join(gitDir, 'refs')
  const headFile = join(gitDir, 'HEAD')

  const watchers: Array<{ close: () => void }> = []

  try {
    const w1 = watch(refsDir, { recursive: true }, () => callback())
    watchers.push(w1)
  } catch { /* refs dir may not exist */ }

  try {
    const w2 = watch(headFile, () => callback())
    watchers.push(w2)
  } catch { /* head file may not exist */ }

  return () => {
    for (const w of watchers) {
      try { w.close() } catch { /* */ }
    }
  }
}
