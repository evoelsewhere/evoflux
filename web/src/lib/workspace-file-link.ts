import { workspaceFileExtension } from '@/lib/workspace-file-kind'
import { useUIStore } from '@/stores/useUIStore'

const PREVIEWABLE_EXTENSIONS = new Set([
  'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx',
  'csv', 'tsv', 'txt', 'md', 'markdown', 'rst', 'log',
  'json', 'jsonl', 'yaml', 'yml', 'toml', 'ini', 'xml',
  'html', 'htm', 'css', 'scss', 'svg',
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp',
  'mp4', 'webm', 'mov', 'm4v', 'mp3', 'wav', 'ogg',
  'py', 'ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs',
  'sh', 'bash', 'zsh', 'rs', 'go', 'java', 'kt',
  'c', 'cc', 'cpp', 'h', 'hpp', 'cs', 'rb', 'php', 'swift', 'sql',
])

function decodePath(value: string): string | null {
  try {
    const decoded = value
      .split('/')
      .map((segment) => decodeURIComponent(segment))
      .join('/')
      .replace(/\\/g, '/')
      .replace(/^\.\//, '')
      .replace(/^\/+/, '')
    const segments = decoded.split('/').filter(Boolean)
    if (segments.length === 0 || segments.some((segment) => segment === '..')) return null
    const path = segments.join('/')
    return PREVIEWABLE_EXTENSIONS.has(workspaceFileExtension(path)) ? path : null
  } catch {
    return null
  }
}

/** Resolve an assistant-authored Markdown href to a safe workspace-relative path. */
export function workspaceFilePathFromHref(href: string, sessionId: string): string | null {
  const value = href.trim()
  if (!value || value.startsWith('#')) return null

  // Canonical backend media links may be relative or absolute and may carry
  // auth/download query parameters. Only accept links for the current session.
  try {
    const url = new URL(value, window.location.origin)
    const match = url.pathname.match(/\/api\/team\/([^/]+)\/media\/(.+)$/)
    if (match) {
      if (decodeURIComponent(match[1]) !== sessionId) return null
      return decodePath(match[2])
    }
  } catch {
    // Continue to the bare workspace-path cases below.
  }

  // Some model runtimes emit sandbox:/mnt/data/<artifact>. Keep only the
  // basename because generated artifacts are copied into the session workspace.
  if (/^sandbox:/i.test(value)) {
    const rawPath = value.replace(/^sandbox:/i, '').split(/[?#]/, 1)[0] ?? ''
    return decodePath(rawPath.split('/').at(-1) ?? '')
  }

  // External/protocol links remain normal browser links. Relative artifact
  // paths are handled by Files just like relative Markdown images already are.
  if (/^[a-z][a-z0-9+.-]*:/i.test(value) || value.startsWith('//')) return null
  return decodePath(value.split(/[?#]/, 1)[0] ?? '')
}

/** Open an internal artifact in the app-owned Files preview. */
export function openWorkspaceFileLink(href: string, sessionId?: string): boolean {
  if (!sessionId) return false
  const path = workspaceFilePathFromHref(href, sessionId)
  if (!path) return false
  useUIStore.getState().requestWorkspaceFile(sessionId, path)
  return true
}
