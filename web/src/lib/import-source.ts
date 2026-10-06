export type ImportSource =
  | 'claude_web'
  | 'claude_code'
  | 'chatgpt'
  | 'codex'
  | 'cursor'
  | 'generic'

export const IMPORT_SOURCE_LABELS: Record<ImportSource, string> = {
  claude_web: 'Claude.ai',
  claude_code: 'Claude Code',
  chatgpt: 'ChatGPT',
  codex: 'Codex',
  cursor: 'Cursor',
  generic: 'Other / Generic',
}

export function formatImportSource(source: string | null | undefined): string | null {
  if (!source) return null
  if (Object.hasOwn(IMPORT_SOURCE_LABELS, source)) {
    return IMPORT_SOURCE_LABELS[source as ImportSource]
  }
  return source
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}
