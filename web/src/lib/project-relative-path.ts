/** Return a safe workspace-relative path for a native save-dialog result. */
export function projectRelativePath(workspace: string, selectedPath: string): string | null {
  const normalize = (path: string) => path
    .replace(/\\/g, '/')
    .replace(/([^/])\/{2,}/g, '$1/')
    .replace(/\/+$/, '')
  const root = normalize(workspace)
  const target = normalize(selectedPath)
  if (!root || !target) return null

  const rootPrefix = `${root.toLowerCase()}/`
  if (!target.toLowerCase().startsWith(rootPrefix)) return null

  const relative = target.slice(root.length + 1)
  if (!relative || relative.split('/').some((segment) => segment === '..' || segment === '.')) {
    return null
  }
  return relative
}
