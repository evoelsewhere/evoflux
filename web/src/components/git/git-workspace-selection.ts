import type { ProjectWorkspaceItem } from '@/api/types'

function normalizedPath(path: string): string {
  const normalized = path.replace(/\\/g, '/').replace(/\/+$/, '')
  return /^[a-z]:\//i.test(normalized) ? normalized.toLowerCase() : normalized
}

function matchingProjectWorkspace(
  path: string | null,
  projectWorkspaces: readonly ProjectWorkspaceItem[],
): ProjectWorkspaceItem | undefined {
  if (!path) return undefined
  const target = normalizedPath(path)
  return projectWorkspaces.find((item) => normalizedPath(item.path) === target)
}

/** Pick the repository shown by the project Source Control panel. */
export function resolveGitWorkspace(
  workspace: string | null,
  selectedWorkspace: string | null,
  projectWorkspaces: readonly ProjectWorkspaceItem[],
): string {
  if (selectedWorkspace) {
    const selectedProjectWorkspace = matchingProjectWorkspace(
      selectedWorkspace,
      projectWorkspaces,
    )
    if (selectedProjectWorkspace) return selectedProjectWorkspace.path
    if (workspace && normalizedPath(selectedWorkspace) === normalizedPath(workspace)) {
      return workspace
    }
  }

  if (workspace) return workspace
  return projectWorkspaces[0]?.path ?? ''
}

/**
 * Old project sessions can point at an aggregate project folder instead of
 * one of the member repositories. Only replace that invalid representative;
 * a valid member repository (including a non-Git folder awaiting init) stays
 * selected, and a Git worktree outside the member list stays untouched.
 */
export function projectRepositoryFallback(
  workspace: string,
  isGitRepository: boolean | undefined,
  projectWorkspaces: readonly ProjectWorkspaceItem[],
): string | null {
  if (isGitRepository !== false) return null
  if (matchingProjectWorkspace(workspace, projectWorkspaces)) return null
  return projectWorkspaces[0]?.path ?? null
}
