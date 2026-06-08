export type FileCategory = 'code' | 'web' | 'config' | 'markdown' | 'data' | 'docs' | 'office' | 'pdf' | 'image' | 'audio' | 'archive' | 'binary' | 'unknown'

export interface FileTypeInfo {
  extension: string
  category: FileCategory
  language?: string
  isBinary: boolean
  parser: 'plain' | 'markitdown' | 'markdown' | 'csv' | 'skip'
}

const EXTENSION_MAP: Record<string, FileTypeInfo> = {}

function reg(ext: string, category: FileCategory, opts: Partial<FileTypeInfo> = {}): void {
  EXTENSION_MAP[ext.toLowerCase()] = {
    extension: ext,
    category,
    isBinary: false,
    parser: 'plain',
    ...opts
  }
}

// Code
for (const ext of ['ts', 'tsx', 'js', 'jsx', 'py', 'java', 'go', 'rs', 'c', 'cpp', 'h', 'hpp', 'cs', 'rb', 'php', 'swift', 'kt', 'lua', 'sh', 'bash', 'bat', 'ps1', 'sql', 'r', 'scala', 'dart', 'zig', 'nim', 'ex', 'exs', 'hs', 'ml', 'clj', 'lisp', 'asm', 's']) {
  reg(ext, 'code', { language: ext })
}

// Web
for (const ext of ['html', 'htm', 'css', 'scss', 'sass', 'less', 'vue', 'svelte', 'astro']) {
  reg(ext, 'web', { language: ext })
}

// Config
for (const ext of ['json', 'yaml', 'yml', 'toml', 'ini', 'env', 'xml', 'properties', 'conf', 'cfg', 'editorconfig', 'gitignore', 'dockerignore', 'eslintrc', 'prettierrc']) {
  reg(ext, 'config')
}

// Markdown
for (const ext of ['md', 'mdx']) {
  reg(ext, 'markdown', { parser: 'markdown' })
}

// reStructuredText / LaTeX
reg('rst', 'docs')
reg('tex', 'docs')
reg('txt', 'docs')
reg('log', 'docs')
reg('diff', 'docs')
reg('patch', 'docs')
reg('adoc', 'docs')

// Data
for (const ext of ['csv', 'tsv']) {
  reg(ext, 'data', { parser: 'csv' })
}

// Office (markitdown)
for (const ext of ['docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls']) {
  reg(ext, 'office', { parser: 'markitdown', isBinary: true })
}

// PDF
reg('pdf', 'pdf', { parser: 'markitdown', isBinary: true })

// Images (binary, skip content)
for (const ext of ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'tif', 'webp', 'svg', 'ico']) {
  reg(ext, 'image', { isBinary: true, parser: 'markitdown' })
}

// Audio
for (const ext of ['mp3', 'wav', 'flac', 'ogg', 'm4a']) {
  reg(ext, 'audio', { isBinary: true, parser: 'markitdown' })
}

// Archive
for (const ext of ['zip', 'tar', 'gz', 'rar', '7z']) {
  reg(ext, 'archive', { isBinary: true, parser: 'markitdown' })
}

// Binary / skip
for (const ext of ['exe', 'dll', 'so', 'dylib', 'wasm', 'woff', 'woff2', 'ttf', 'otf', 'eot', 'bin', 'dat', 'db', 'sqlite', 'sqlite3', 'pyc', 'class', 'o', 'obj']) {
  reg(ext, 'binary', { isBinary: true, parser: 'skip' })
}

export function detectFileType(filePath: string): FileTypeInfo {
  const ext = getExtension(filePath)
  return EXTENSION_MAP[ext] || {
    extension: ext,
    category: 'unknown',
    isBinary: false,
    parser: 'plain'
  }
}

export function getExtension(filePath: string): string {
  const parts = filePath.split('.')
  if (parts.length < 2) return ''
  return parts[parts.length - 1].toLowerCase()
}

export function getFileName(filePath: string): string {
  const parts = filePath.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || ''
}

export function isBinaryFile(filePath: string): boolean {
  return detectFileType(filePath).isBinary
}

export function shouldSkipFile(filePath: string): boolean {
  return detectFileType(filePath).parser === 'skip'
}

export function getLanguage(filePath: string): string {
  const info = detectFileType(filePath)
  return info.language || info.category
}
