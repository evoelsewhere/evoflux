import { getFileName, shouldSkipFile } from './file-detector'

export interface TreeOptions {
  excludePatterns?: string[]
  maxDepth?: number
  maxEntries?: number
  includeHidden?: boolean
  showFiles?: boolean
}

const DEFAULT_EXCLUDE = ['node_modules', '.git', 'dist', 'out', '.next', '__pycache__', '.venv', 'venv', '.cache', 'coverage']

export interface TreeNode {
  name: string
  path: string
  isDirectory: boolean
  children?: TreeNode[]
}

export function buildTree(
  dirPath: string,
  readdir: (p: string) => string[],
  isDir: (p: string) => boolean,
  options: TreeOptions = {}
): TreeNode | null {
  const {
    excludePatterns = DEFAULT_EXCLUDE,
    maxDepth = 10,
    maxEntries = 1000,
    includeHidden = false,
    showFiles = true
  } = options

  let entryCount = 0

  function build(currentPath: string, depth: number): TreeNode | null {
    if (depth > maxDepth) return null
    if (entryCount >= maxEntries) return null

    const name = getFileName(currentPath) || currentPath
    const isDirectory = isDir(currentPath)

    if (!isDirectory) {
      if (!showFiles) return null
      if (shouldSkipFile(currentPath)) return null
      entryCount++
      return { name, path: currentPath, isDirectory: false }
    }

    if (shouldExclude(name, excludePatterns, includeHidden)) return null

    let entries: string[]
    try {
      entries = readdir(currentPath)
    } catch {
      return null
    }

    const children: TreeNode[] = []
    for (const entry of entries) {
      if (entryCount >= maxEntries) break
      const childPath = `${currentPath}/${entry}`
      const child = build(childPath, depth + 1)
      if (child) children.push(child)
    }

    children.sort((a, b) => {
      if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1
      return a.name.localeCompare(b.name)
    })

    entryCount++
    return { name, path: currentPath, isDirectory: true, children }
  }

  return build(dirPath, 0)
}

function shouldExclude(name: string, patterns: string[], includeHidden: boolean): boolean {
  if (!includeHidden && name.startsWith('.')) return true
  return patterns.includes(name)
}

export function renderTree(node: TreeNode, prefix = '', isLast = true): string {
  const lines: string[] = []
  const connector = isLast ? '└── ' : '├── '
  const childPrefix = prefix + (isLast ? '    ' : '│   ')

  if (node.isDirectory) {
    lines.push(`${prefix}${connector}${node.name}/`)
    if (node.children) {
      node.children.forEach((child, i) => {
        const last = i === node.children!.length - 1
        lines.push(renderTree(child, childPrefix, last))
      })
    }
  } else {
    lines.push(`${prefix}${connector}${node.name}`)
  }

  return lines.join('\n')
}

export function treeToString(root: TreeNode): string {
  const lines: string[] = [`${root.name}/`]
  if (root.children) {
    root.children.forEach((child, i) => {
      const last = i === root.children!.length - 1
      lines.push(renderTree(child, '', last))
    })
  }
  return lines.join('\n')
}
