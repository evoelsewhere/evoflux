import type { ContentBlock, WorkspaceFileInfo } from '@/api/types'
import { extractToolPaths } from '@/stores/useTeamStore/helpers'
import { workspaceFileKind, type WorkspaceFileKind } from '@/lib/workspace-file-kind'

/** Kinds the Files panel previews richly, and so worth a card in the chat. */
const PREVIEWABLE_KINDS = new Set<WorkspaceFileKind>(['pptx', 'xlsx', 'docx', 'pdf', 'image'])

// Folders agents keep scratch renders in (QA screenshots, crops); images
// there are working material, not results, so they get no card.
const SCRATCH_IMAGE_FOLDERS = new Set(['qa', 'crops'])

function isScratchImage(file: WorkspaceFileInfo): boolean {
  if (workspaceFileKind(file) !== 'image') return false
  const folders = normalize(file.path).toLowerCase().split('/').slice(0, -1)
  return folders.some((folder) => SCRATCH_IMAGE_FOLDERS.has(folder))
}

// A path-like token ending in a previewable extension, inside a command line.
const COMMAND_FILE_RE = /[^\s"'`<>|;&()=]+\.(?:pptx|xlsx|docx|pdf|png|jpe?g|gif|webp|svg)\b/gi

function normalize(path: string): string {
  return path.trim().replace(/\\/g, '/').replace(/^\.\//, '')
}

function commandText(toolArgs: string | undefined): string {
  if (!toolArgs) return ''
  try {
    const parsed = JSON.parse(toolArgs) as { command?: unknown, cmd?: unknown }
    const command = parsed.command ?? parsed.cmd
    return typeof command === 'string' ? command : ''
  } catch {
    return ''
  }
}

/**
 * Paths of files a turn's tools wrote, edited or produced, in first-touched
 * order: `write`/`edit`/`patch` targets, plus previewable files named on a
 * shell command line (a deck built by a script). Files the turn removed are
 * left out. Mentions in the assistant's prose do not count.
 */
export function turnFileMentions(blocks: readonly ContentBlock[]): string[] {
  const seen = new Set<string>()
  const removed = new Set<string>()
  const ordered: string[] = []
  const add = (path: string) => {
    const normalized = normalize(path)
    if (!normalized || seen.has(normalized)) return
    seen.add(normalized)
    ordered.push(normalized)
  }
  for (const block of blocks) {
    if (block.type !== 'tool' || !block.toolName) continue
    if (block.toolName === 'rm') {
      for (const path of extractToolPaths('rm', block.toolArgs) ?? []) removed.add(normalize(path))
      continue
    }
    if (block.toolName === 'shell' || block.toolName === 'process') {
      for (const match of commandText(block.toolArgs).matchAll(COMMAND_FILE_RE)) add(match[0])
      continue
    }
    for (const path of extractToolPaths(block.toolName, block.toolArgs) ?? []) add(path)
  }
  return ordered.filter((path) => !removed.has(path))
}

/**
 * The workspace files behind ``mentions`` that the Files panel previews:
 * matched by relative path, by an absolute path under ``root``, or by a
 * file name that is unique in the workspace. Images in scratch folders
 * (``qa/``, ``crops/``) are left out.
 */
export function resolveTurnFiles(
  mentions: readonly string[],
  files: readonly WorkspaceFileInfo[],
  root?: string | null,
): WorkspaceFileInfo[] {
  if (mentions.length === 0 || files.length === 0) return []
  const byPath = new Map(files.map((file) => [normalize(file.path), file]))
  const byName = new Map<string, WorkspaceFileInfo | null>()
  for (const file of files) byName.set(file.name, byName.has(file.name) ? null : file)
  const rootPrefix = root ? `${normalize(root).replace(/\/+$/, '')}/` : null

  const resolved: WorkspaceFileInfo[] = []
  const picked = new Set<string>()
  for (const mention of mentions) {
    let relative = mention
    if (rootPrefix && relative.toLowerCase().startsWith(rootPrefix.toLowerCase())) {
      relative = relative.slice(rootPrefix.length)
    }
    const file = byPath.get(relative) ?? byName.get(relative.split('/').pop() ?? '') ?? null
    if (!file || picked.has(file.path) || !PREVIEWABLE_KINDS.has(workspaceFileKind(file))) continue
    if (isScratchImage(file)) continue
    picked.add(file.path)
    resolved.push(file)
  }
  return resolved
}
