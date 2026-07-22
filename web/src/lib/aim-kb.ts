import type { CodingProject, ProjectWorkspaceItem } from '@/api/types'

export function resolveAimRolePath(
  project: CodingProject,
  role: 'kb' | 'target' | 'source',
): string | null {
  return resolveAimRoleWorkspaces(project, role)[0]?.path ?? null
}

export function resolveAimRoleWorkspaces(
  project: CodingProject,
  role: 'kb' | 'target' | 'source',
): ProjectWorkspaceItem[] {
  const aim = project.settings?.aim as
    | { roles?: Record<string, string[]> }
    | undefined
  const ids = aim?.roles?.[role] ?? []
  const found: ProjectWorkspaceItem[] = []
  for (const id of ids) {
    const workspace = project.workspaces.find((item) => item.workspace_id === id)
    if (workspace) found.push(workspace)
  }
  return found
}

export function splitFrontmatter(source: string): {
  meta: Array<[string, string]>
  body: string
} {
  const match = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(source)
  if (!match) return { meta: [], body: source }
  const meta: Array<[string, string]> = []
  for (const rawLine of match[1].split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line) continue
    const kv = /^([A-Za-z0-9_.-]+):\s*(.*)$/.exec(line)
    if (kv) {
      meta.push([kv[1], kv[2]])
    } else if (meta.length > 0) {
      const item = line.replace(/^-\s*/, '')
      const last = meta[meta.length - 1]
      last[1] = last[1] ? `${last[1]}, ${item}` : item
    }
  }
  return { meta, body: source.slice(match[0].length) }
}
