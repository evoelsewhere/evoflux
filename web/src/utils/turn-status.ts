/**
 * What the agent is doing *right now*, derived from the live turn's blocks.
 *
 * The transcript already knows this — a tool block without `toolDone` is a
 * running call, a growing thinking block is reasoning — but until now three
 * call sites each rendered their own partial reading of it and the wide view
 * said only "Working for 1m 57s". This is the single derivation they share.
 *
 * The phase is only a fallback: the backend emits `model_calling` once per
 * turn, before `agent.run`, so it cannot distinguish the model calls inside
 * a tool loop. The block tail can: after a tool finishes, the model has the
 * turn again and nothing has streamed back yet — that is "waiting".
 */
import type { ContentBlock } from '@/api/types'

export type LiveTurnActivityKind =
  | 'tool'
  | 'thinking'
  | 'responding'
  | 'waiting'
  | 'preparing'

export interface LiveTurnActivity {
  kind: LiveTurnActivityKind
  /** One short present-tense phrase, e.g. "Editing main.rs". */
  label: string
  /** Set only for `kind: 'tool'` — selects the leading icon. */
  toolName: string | null
}

/**
 * Present-participle verbs for a call that is still running.
 *
 * `ToolCallGroup` keeps a past-tense map for finished calls, and the two
 * deliberately diverge rather than share one table: a collapsed group
 * summarises ("Read files"), a live line names the target ("Reading
 * main.rs"). Tools absent here fall back to `Running`.
 */
const ACTIVE_VERBS: Record<string, string> = {
  bash: 'Running',
  shell: 'Running',
  run_command: 'Running',
  python: 'Running',
  read: 'Reading',
  read_file: 'Reading',
  write: 'Writing',
  write_file: 'Writing',
  edit: 'Editing',
  edit_file: 'Editing',
  patch: 'Patching',
  glob: 'Listing',
  ls: 'Listing',
  grep: 'Searching',
  code_context: 'Querying',
  web_search: 'Searching',
  web_fetch: 'Fetching',
  browser_use: 'Browsing',
  webbridge: 'Browsing',
  git: 'Running git',
  recall: 'Checking memory',
  skill: 'Loading skill',
  team_delegate: 'Delegating',
  team_message: 'Messaging',
}

/** Argument keys naming a filesystem path, shown as a basename. */
const PATH_KEYS = new Set(['file_path', 'path', 'filepath', 'file', 'notebook_path'])

/** Argument keys worth printing, most specific first. */
const TARGET_KEYS = [
  'file_path',
  'path',
  'filepath',
  'file',
  'notebook_path',
  'command',
  'pattern',
  'query',
  'url',
  'name',
  'description',
]

const MAX_TARGET = 42

function truncate(value: string, max = MAX_TARGET): string {
  const normalized = value.replace(/\s+/g, ' ').trim()
  return normalized.length > max ? `${normalized.slice(0, max - 1)}…` : normalized
}

function basename(value: string): string {
  return value.split(/[\\/]/).filter(Boolean).at(-1) ?? value
}

/** The one argument worth naming in a one-line status, or null. */
function toolTarget(args: string | undefined): string | null {
  if (!args) return null
  let parsed: Record<string, unknown>
  try {
    parsed = JSON.parse(args) as Record<string, unknown>
  } catch {
    return truncate(args)
  }
  for (const key of TARGET_KEYS) {
    const value = parsed[key]
    if (typeof value !== 'string' || !value.trim()) continue
    return truncate(PATH_KEYS.has(key) ? basename(value) : value)
  }
  return null
}

export function activeToolLabel(toolName: string, args: string | undefined): string {
  const verb = ACTIVE_VERBS[toolName]
  const target = toolTarget(args)
  if (verb) return target ? `${verb} ${target}` : `${verb}…`
  return target ? `Running ${toolName} · ${target}` : `Running ${toolName}`
}

/** The last block that says anything about the agent's own state. */
function lastAgentBlock(blocks: ContentBlock[]): ContentBlock | null {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index]
    if (block.type !== 'user') return block
  }
  return null
}

export function liveTurnActivity(
  blocks: ContentBlock[],
  phase: 'ingress' | 'model_calling' | null,
  modelName: string | null,
): LiveTurnActivity {
  const waiting: LiveTurnActivity = {
    kind: 'waiting',
    label: `Waiting for ${modelName ?? 'the model'}…`,
    toolName: null,
  }
  const last = lastAgentBlock(blocks)

  if (last?.type === 'tool' && !last.toolDone) {
    const toolName = last.toolName ?? 'tool'
    return { kind: 'tool', label: activeToolLabel(toolName, last.toolArgs), toolName }
  }
  if (!last) {
    // Nothing has come back yet: either EvoFlux is still assembling the turn
    // or the request is already out with the provider.
    return phase === 'model_calling'
      ? waiting
      : { kind: 'preparing', label: 'Preparing…', toolName: null }
  }
  if (last.type === 'thinking') {
    return { kind: 'thinking', label: 'Thinking…', toolName: null }
  }
  if (last.type === 'text') {
    return { kind: 'responding', label: 'Responding…', toolName: null }
  }
  // A finished tool, or any other completed block — the model has the turn
  // again and has not streamed anything back.
  return waiting
}
