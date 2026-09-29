/**
 * Which repository of a Coding session a path belongs to.
 *
 * A Coding session runs in its primary repository (the project's first one,
 * or a worktree of one) but may read and write every other repository of its
 * project. Paths reach the UI in whatever shape the agent used: relative to
 * the primary (`src/app.ts`), climbing into a sibling (`../web/src/app.ts`),
 * or absolute with either separator (`C:\repos\web\src\app.ts`). Every
 * surface that opens, refreshes or cites a file has to route it to the
 * repository that owns it instead of assuming the primary.
 */
import type { CodingProject, CodingWorkspaceTreeResponse } from '@/api/types'

export interface RepositoryPath {
  /** The owning repository, exactly as the session's repository list names it. */
  workspace: string
  /** The path inside that repository, with `/` separators. */
  path: string
}

const WINDOWS_DRIVE_RE = /^[a-zA-Z]:\//

export function isAbsolutePath(path: string): boolean {
  const slashed = path.replace(/\\/g, '/')
  return slashed.startsWith('/') || WINDOWS_DRIVE_RE.test(slashed)
}

/** `/` separators with `.` and `..` segments folded away. */
export function normalizePath(path: string): string {
  const slashed = path.replace(/\\/g, '/')
  const drive = WINDOWS_DRIVE_RE.test(slashed) ? slashed.slice(0, 2) : ''
  const rest = drive ? slashed.slice(2) : slashed
  const rooted = rest.startsWith('/')
  const parts: string[] = []
  for (const part of rest.split('/')) {
    if (!part || part === '.') continue
    if (part === '..') {
      if (parts.length > 0 && parts[parts.length - 1] !== '..') parts.pop()
      else if (!rooted) parts.push('..')
      continue
    }
    parts.push(part)
  }
  const body = parts.join('/')
  return drive ? `${drive}/${body}` : rooted ? `/${body}` : body
}

// Windows paths compare case-insensitively, as the filesystem does.
function comparable(path: string): string {
  const normalized = normalizePath(path)
  return WINDOWS_DRIVE_RE.test(normalized) ? normalized.toLowerCase() : normalized
}

function joinPath(root: string, path: string): string {
  return normalizePath(`${root.replace(/\\/g, '/').replace(/\/+$/, '')}/${path}`)
}

/**
 * Route *path* to the repository that owns it.
 *
 * A relative path is taken relative to *primary*. When several repositories
 * contain the path — a managed worktree lives inside its source repository —
 * the deepest one wins. Returns ``null`` for a path outside every repository.
 */
export function resolveRepositoryPath(
  primary: string,
  repositories: readonly string[],
  path: string,
): RepositoryPath | null {
  const absolute = isAbsolutePath(path) ? normalizePath(path) : joinPath(primary, path)
  const target = comparable(absolute)
  let best: { workspace: string; root: string } | null = null
  for (const workspace of [primary, ...repositories]) {
    const root = comparable(workspace)
    if (target !== root && !target.startsWith(`${root}/`)) continue
    if (!best || root.length > best.root.length) best = { workspace, root }
  }
  if (!best) return null
  return { workspace: best.workspace, path: absolute.slice(best.root.length).replace(/^\/+/, '') }
}

/**
 * *path* inside *workspace* as the agent addresses it from *primary*: relative
 * for the primary's own files, absolute for any other repository's.
 */
export function agentPath(primary: string, workspace: string | null | undefined, path: string): string {
  if (!workspace || comparable(workspace) === comparable(primary)) return path
  return joinPath(workspace, path)
}

const REPOSITORY_WORKTREES_DIR = '/.evoflux/worktrees/'

/**
 * The project repository a worktree *workspace* was made from, if any.
 *
 * Recognises the repository-local worktree root (`<repo>/.evoflux/worktrees`)
 * by path, and any other managed worktree through the Coding overview.
 */
export function worktreeSourceRepository(
  workspace: string,
  repositories: readonly string[],
  overview?: CodingWorkspaceTreeResponse | null,
): string | null {
  const target = comparable(workspace)
  for (const repository of repositories) {
    if (target.startsWith(`${comparable(repository)}${REPOSITORY_WORKTREES_DIR}`)) return repository
  }
  const listed = overview?.repositories.find((repository) =>
    repository.worktrees.some((worktree) => comparable(worktree.path) === target),
  )
  if (!listed) return null
  return repositories.find((repository) => comparable(repository) === comparable(listed.path)) ?? null
}

/**
 * *project* as a session on *workspace* sees it: when the session runs in a
 * worktree, the worktree stands in for the repository it was made from, so
 * the file tree, Source Control and everything else open the checkout the
 * agent is actually working in.
 */
export function sessionProject(
  project: CodingProject,
  workspace: string | null | undefined,
  overview?: CodingWorkspaceTreeResponse | null,
): CodingProject {
  if (!workspace) return project
  const paths = project.workspaces.map((item) => item.path)
  if (paths.some((path) => comparable(path) === comparable(workspace))) return project
  const source = worktreeSourceRepository(workspace, paths, overview)
  if (!source) return project
  const worktreeName = workspace.replace(/[\\/]+$/, '').split(/[\\/]/).pop() ?? workspace
  return {
    ...project,
    workspaces: project.workspaces.map((item) =>
      item.path === source
        ? {
            ...item,
            path: workspace,
            display_name: `${item.display_name || item.name || worktreeName} (${worktreeName})`,
          }
        : item,
    ),
  }
}
