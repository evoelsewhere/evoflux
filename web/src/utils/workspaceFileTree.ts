/**
 * Pure helpers for building a file tree and change-status map from workspace
 * listings/diffs. Split out of CodingWorkspacePanel.tsx (a component file) so
 * Vite Fast Refresh doesn't fall back to a full reload on every edit there —
 * mixing non-component exports into a component module breaks its refresh
 * boundary.
 */

import type { WorkspaceFileInfo, WorkspaceGitDiffResponse } from '@/api/types'

export interface TreeNode {
  name: string
  path: string
  children: Map<string, TreeNode>
  file?: WorkspaceFileInfo
}

export type ChangedFileStatus = 'A' | 'M' | 'D'

const treeNodeNameCollator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: 'base',
})

function isDirectoryNode(node: TreeNode): boolean {
  return node.children.size > 0 && !node.file
}

function compareTreeNodes(left: TreeNode, right: TreeNode): number {
  const leftIsDir = isDirectoryNode(left)
  const rightIsDir = isDirectoryNode(right)
  if (leftIsDir !== rightIsDir) return leftIsDir ? -1 : 1
  return treeNodeNameCollator.compare(left.name, right.name)
}

function sortTreeNode(node: TreeNode): void {
  const sortedEntries = Array.from(node.children.entries()).sort(([, left], [, right]) => compareTreeNodes(left, right))
  node.children = new Map(sortedEntries)
  for (const child of node.children.values()) {
    sortTreeNode(child)
  }
}

export function sortTreeNodeChildren(node: TreeNode): TreeNode[] {
  return Array.from(node.children.values()).sort(compareTreeNodes)
}

export interface ChangedFileInfo {
  path: string
  status: ChangedFileStatus
  additions: number
  deletions: number
}

export function collectChangedFiles(diff?: WorkspaceGitDiffResponse): ChangedFileInfo[] {
  const files = new Map<string, ChangedFileInfo>()
  if (!diff?.is_git_repo) return []

  let current: ChangedFileInfo | null = null
  for (const line of diff.diff.split('\n')) {
    if (line.startsWith('diff --git ')) {
      const match = /^diff --git a\/(.*) b\/(.*)$/.exec(line)
      if (!match?.[2]) {
        current = null
        continue
      }
      current = files.get(match[2]) ?? { path: match[2], status: 'M', additions: 0, deletions: 0 }
      files.set(current.path, current)
      continue
    }
    if (!current) continue
    if (line.startsWith('new file mode')) current.status = 'A'
    else if (line.startsWith('deleted file mode')) current.status = 'D'
    else if (line.startsWith('+') && !line.startsWith('+++')) current.additions += 1
    else if (line.startsWith('-') && !line.startsWith('---')) current.deletions += 1
  }

  for (const path of diff.untracked ?? []) {
    const existing = files.get(path)
    if (existing) existing.status = 'A'
    else files.set(path, { path, status: 'A', additions: 0, deletions: 0 })
  }
  return Array.from(files.values()).sort((a, b) => a.path.localeCompare(b.path))
}

export function buildTree(files: WorkspaceFileInfo[]): TreeNode {
  const root: TreeNode = { name: '/', path: '', children: new Map() }
  for (const file of files) {
    const parts = file.path.split('/')
    let node = root
    parts.forEach((part, index) => {
      const path = parts.slice(0, index + 1).join('/')
      let child = node.children.get(part)
      if (!child) {
        child = { name: part, path, children: new Map() }
        node.children.set(part, child)
      }
      if (index === parts.length - 1) child.file = file
      node = child
    })
  }
  sortTreeNode(root)
  return root
}
