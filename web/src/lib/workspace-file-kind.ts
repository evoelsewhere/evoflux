import type { WorkspaceFileInfo } from '@/api/types'

const TEXT_EXTENSIONS = new Set([
  'txt', 'md', 'markdown', 'rst',
  'json', 'jsonl', 'ndjson', 'yaml', 'yml', 'toml', 'ini', 'env', 'gitignore',
  'csv', 'tsv', 'log',
  'py', 'ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs',
  'html', 'css', 'scss', 'sass',
  'sh', 'bash', 'zsh', 'fish',
  'rs', 'go', 'java', 'kt', 'c', 'cpp', 'h', 'hpp', 'rb', 'php', 'swift',
  'sql', 'xml', 'svg',
])

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'])
const PLAIN_TEXT_EXTENSIONS = new Set([
  'txt', 'log', 'csv', 'tsv', 'env', 'gitignore', 'ini', 'md', 'markdown', 'rst',
])

export type WorkspaceFileKind = 'image' | 'text' | 'docx' | 'xlsx' | 'pptx' | 'pdf' | 'binary'

export function workspaceFileExtension(name: string): string {
  const index = name.lastIndexOf('.')
  return index >= 0 ? name.slice(index + 1).toLowerCase() : ''
}

export function isWorkspaceCodeExtension(extension: string): boolean {
  return TEXT_EXTENSIONS.has(extension) && !PLAIN_TEXT_EXTENSIONS.has(extension)
}

export function workspaceFileKind(file: WorkspaceFileInfo): WorkspaceFileKind {
  const extension = workspaceFileExtension(file.name)
  // SVG is both an image and text — prefer the visual preview.
  if (IMAGE_EXTENSIONS.has(extension) || file.mime.startsWith('image/')) return 'image'
  if (extension === 'docx') return 'docx'
  if (extension === 'xlsx') return 'xlsx'
  if (extension === 'pptx') return 'pptx'
  if (extension === 'pdf' || file.mime === 'application/pdf') return 'pdf'
  if (!extension || TEXT_EXTENSIONS.has(extension)) return 'text'
  if (file.mime.startsWith('text/') || file.mime === 'application/json') return 'text'
  return 'binary'
}
