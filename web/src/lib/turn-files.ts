import type { ContentBlock, WorkspaceFileInfo } from '@/api/types'
import { extractToolPaths } from '@/stores/useTeamStore/helpers'
import { workspaceFilePathFromHref } from '@/lib/workspace-file-link'
import { workspaceFileKind, type WorkspaceFileKind } from '@/lib/workspace-file-kind'

/** Documents a turn's tools produced get a card on their own. */
const DOCUMENT_KINDS = new Set<WorkspaceFileKind>(['pptx', 'xlsx', 'docx', 'pdf'])
/** Anything the Files panel previews richly gets a card when the reply links it. */
const PREVIEWABLE_KINDS = new Set<WorkspaceFileKind>([...DOCUMENT_KINDS, 'image'])

// A path-like token ending in a document extension, inside a command line.
const COMMAND_FILE_RE = /[^\s"'`<>|;&()=]+\.(?:pptx|xlsx|docx|pdf)\b/gi
// A Markdown link or image: [label](href) / ![alt](href "title").
const MARKDOWN_LINK_RE = /!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)/g

export interface TurnFileMentions {
  /** Files the turn's tools wrote, edited or named on a command line. */
  produced: string[]
  /** Workspace files the reply links, the agent's own pick of what to show. */
  linked: string[]
}

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

function unique(paths: Iterable<string>, exclude: Set<string>): string[] {
  const seen = new Set<string>()
  const ordered: string[] = []
  for (const raw of paths) {
    const path = normalize(raw)
    if (!path || seen.has(path) || exclude.has(path)) continue
    seen.add(path)
    ordered.push(path)
  }
  return ordered
}

/**
 * What a turn touched and what it chose to show, in order. ``produced``:
 * `write`/`edit`/`patch` targets plus documents named on a `shell` or
 * `process` command line (a deck built by a script). ``linked``: workspace
 * files the reply links in Markdown. Files the turn removed are left out;
 * plain or inline-code mentions do not count.
 */
export function turnFileMentions(blocks: readonly ContentBlock[], sessionId = ''): TurnFileMentions {
  const produced: string[] = []
  const linked: string[] = []
  const removed = new Set<string>()
  for (const block of blocks) {
    if (block.type === 'text') {
      for (const match of block.content.matchAll(MARKDOWN_LINK_RE)) {
        const path = workspaceFilePathFromHref(match[1] ?? '', sessionId)
        if (path) linked.push(path)
      }
      continue
    }
    if (block.type !== 'tool' || !block.toolName) continue
    if (block.toolName === 'rm') {
      for (const path of extractToolPaths('rm', block.toolArgs) ?? []) removed.add(normalize(path))
    } else if (block.toolName === 'shell' || block.toolName === 'process') {
      for (const match of commandText(block.toolArgs).matchAll(COMMAND_FILE_RE)) produced.push(match[0])
    } else {
      produced.push(...(extractToolPaths(block.toolName, block.toolArgs) ?? []))
    }
  }
  return { produced: unique(produced, removed), linked: unique(linked, removed) }
}

/**
 * The workspace files behind a turn's mentions that deserve a card: the
 * documents it produced, and every previewable file (images included) its
 * reply links. Paths match by relative path, by an absolute path under
 * ``root``, or by a file name that is unique in the workspace.
 */
export function resolveTurnFiles(
  mentions: TurnFileMentions,
  files: readonly WorkspaceFileInfo[],
  root?: string | null,
): WorkspaceFileInfo[] {
  if (files.length === 0) return []
  const byPath = new Map(files.map((file) => [normalize(file.path), file]))
  const byName = new Map<string, WorkspaceFileInfo | null>()
  for (const file of files) byName.set(file.name, byName.has(file.name) ? null : file)
  const rootPrefix = root ? `${normalize(root).replace(/\/+$/, '')}/` : null
  const find = (mention: string) => {
    let relative = mention
    if (rootPrefix && relative.toLowerCase().startsWith(rootPrefix.toLowerCase())) {
      relative = relative.slice(rootPrefix.length)
    }
    return byPath.get(relative) ?? byName.get(relative.split('/').pop() ?? '') ?? null
  }

  const resolved: WorkspaceFileInfo[] = []
  const picked = new Set<string>()
  const take = (mention: string, kinds: Set<WorkspaceFileKind>) => {
    const file = find(mention)
    if (!file || picked.has(file.path) || !kinds.has(workspaceFileKind(file))) return
    picked.add(file.path)
    resolved.push(file)
  }
  for (const mention of mentions.produced) take(mention, DOCUMENT_KINDS)
  for (const mention of mentions.linked) take(mention, PREVIEWABLE_KINDS)
  return resolved
}
