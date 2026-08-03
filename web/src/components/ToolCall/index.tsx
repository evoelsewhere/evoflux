/**
 * ToolCall — inline record of a tool invocation.
 *
 * Visual language follows the pencil source (nodes ``dqwZw`` / ``LJOUY``)
 * and the canonical spec at ``applications.md#tool-call-row``:
 *
 *   - Collapsed row: no card fill; sits on the ambient chat surface.
 *   - Header row: mono tool label + optional summary + chevron.
 *   - Expanded body: separate bordered inspector with section panels so
 *     args/results read as secondary diagnostic content.
 *
 * Running state is carried by subtle header animation; result content carries
 * success/failure details.
 *
 * The per-tool header/args customisation lives in ``./display.tsx``;
 * this module owns only the chrome (collapse, copy, motion).
 */

import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronRight, Copy, Check, MonitorPlayIcon } from 'lucide-react'
import { ToolResult } from '../ToolResult'
import { getToolDisplay } from './display'
import { DiffView } from './DiffView'
import { ReadView } from './ReadView'
import { getDiffStats } from './diffUtils'
import { panelTransition, useMotionPreset } from '@/lib/motion'
import { useUIStore } from '@/stores/useUIStore'
import { useTeamStore } from '@/stores/useTeamStore'
import { SubagentTaskCard } from '@/components/SubagentTaskCard'
import { ImageAttachment } from '@/components/ImageAttachment'
import { FileCard } from '@/components/FileCard'
import { ActivityStatus } from '@/components/motion/ActivityStatus'
import { resolveApiUrl } from '@/api/client'
import type { MessageAttachment } from '@/api/types'
import type { ToolCallState } from './types'

interface ToolCallProps {
  name: string
  args?: string
  done?: boolean
  liveOutput?: string
  result?: string // tool response content
  durationMs?: number
  startedAt?: number
  attachments?: MessageAttachment[]
}

export function ToolAttachments({
  attachments,
  limit,
}: {
  attachments?: MessageAttachment[]
  limit?: number
}) {
  if (!attachments || attachments.length === 0) return null
  const visible = limit ? attachments.slice(0, limit) : attachments
  const remaining = attachments.length - visible.length

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-2">
      {visible.map((attachment, index) =>
        attachment.category === 'image' ? (
          <ImageAttachment
            key={`${attachment.url ?? attachment.filename ?? index}`}
            src={resolveApiUrl(attachment.url) || ''}
            alt={attachment.original_name || `Tool image ${index + 1}`}
            compact
          />
        ) : (
          <FileCard
            key={`${attachment.url ?? attachment.filename ?? index}`}
            name={attachment.original_name || attachment.filename || `Tool file ${index + 1}`}
            mediaType={attachment.media_type}
            url={resolveApiUrl(attachment.preview_url || attachment.url)}
            clickable={Boolean(attachment.preview_url || attachment.url)}
            downloadUrl={resolveApiUrl(attachment.download_url)}
          />
        ),
      )}
      {remaining > 0 && (
        <span className="text-xs text-(--color-text-muted)">+{remaining} more</span>
      )}
    </div>
  )
}

function isFailedResult(result: string | undefined): boolean {
  if (!result) return false
  const firstLine = result.trimStart().split('\n', 1)[0]?.toLowerCase() ?? ''
  return (
    firstLine.startsWith('[failed') ||
    firstLine.startsWith('[error') ||
    firstLine.includes('exit code 1') ||
    firstLine.includes('exit 1')
  )
}

function formatShellResult(result: string | undefined): { statusLine: string | null; body: string | null } {
  if (!result) return { statusLine: null, body: null }

  const firstNewline = result.indexOf('\n')
  const firstLine = firstNewline >= 0 ? result.slice(0, firstNewline).trim() : result.trim()
  const hasStatusLine = /^\[(Succeeded|Failed|Error)/i.test(firstLine)

  if (!hasStatusLine) {
    return { statusLine: null, body: result }
  }

  const body = firstNewline >= 0 ? result.slice(firstNewline + 1).trimStart() : ''
  return { statusLine: firstLine, body: body || null }
}

function formatToolLabel(name: string): string {
  if (!name) return 'Tool'
  return name
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`

  const totalSeconds = Math.round(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}m ${seconds}s`
}

function cleanActivityLabel(label: string): string {
  return label.replace(/[.…]+$/u, '').trim()
}

function toolActivityLabel(
  name: string,
  state: Extract<ToolCallState, 'start' | 'running'>,
  headerTitle: string | null,
): string {
  const target = headerTitle ? cleanActivityLabel(headerTitle) : null
  if (state === 'start') return target || `Preparing ${formatToolLabel(name)}`

  switch (name) {
    case 'read': return `Reading ${target || 'file'}`
    case 'write': return `Writing ${target || 'file'}`
    case 'edit': return `Editing ${target || 'file'}`
    case 'patch': return `Applying ${target || 'patch'}`
    case 'rm': return `Removing ${target || 'file'}`
    case 'skill': return `Loading ${target || 'skill'}`
    case 'shell': return target || 'Running command'
    case 'python': return target || 'Running Python'
    case 'browser_use':
    case 'webbridge': return target || 'Using browser'
    case 'web_search': return target ? `Searching ${target}` : 'Searching web'
    case 'web_fetch': return target ? `Reading ${target}` : 'Reading page'
    case 'wiki_search': return target ? `Searching memory for ${target}` : 'Searching memory'
    case 'grep':
    case 'code_search': return target || 'Searching code'
    case 'glob': return target || 'Scanning files'
    case 'ls': return target || 'Listing files'
    default: return target || `Running ${formatToolLabel(name)}`
  }
}

export const ToolCall = memo(function ToolCall({ name, args, done, liveOutput, result, durationMs, startedAt, attachments }: ToolCallProps) {
  // Hooks must be called unconditionally — before any early returns
  const preset = useMotionPreset()
  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null)
  const [copiedArgs, setCopiedArgs] = useState(false)
  const [copiedResult, setCopiedResult] = useState(false)
  const liveOutputRef = useRef<HTMLPreElement>(null)
  const [now, setNow] = useState(() => Date.now())

  // Determine status: start (name only) → running (args) → success/failed (result)
  const isPending = args === undefined || args === null
  const isRunning = !isPending && !done
  const state: ToolCallState = isPending
    ? 'start'
    : isRunning
      ? 'running'
      : isFailedResult(result)
        ? 'failed'
        : 'success'

  // getToolDisplay JSON.parses args and getDiffStats runs a line diff —
  // memoized so parent re-renders (streaming ticks) don't redo the work.
  const { header, headerTitle, formattedArgs, language, suppressResult } =
    useMemo(() => getToolDisplay(name, args), [name, args])
  const usesDiffView = name === 'edit' || name === 'patch' || name === 'write'
  const usesReadView = name === 'read'
  const diffStats = useMemo(
    () => ((usesDiffView || name === 'rm') && args ? getDiffStats(name, args, result) : null),
    [name, args, result, usesDiffView],
  )
  // Pending-state header comes from getToolDisplay's no-args branch
  // (e.g. ``recall`` → "Checking memory…", ``team_message`` →
  // "Preparing message…"). Tools without a custom pending header return
  // ``header: null`` from that branch and fall back to the raw tool name
  // below, preserving the previous behaviour for every other tool.
  const visibleHeader = header
  const shownResult = suppressResult ? undefined : result
  const shownLiveOutput = shownResult ? undefined : liveOutput
  const hasReadResult = usesReadView && Boolean(result)
  const isShell = language === 'bash'
  const isShellTerminal = isShell && Boolean(formattedArgs)
  const shellResult = isShell ? formatShellResult(shownResult) : null
  const shellOutput = shellResult?.body ?? shownLiveOutput

  useEffect(() => {
    if (done || !startedAt) return
    const id = window.setInterval(() => setNow(Date.now()), 100)
    return () => window.clearInterval(id)
  }, [done, startedAt])

  useEffect(() => {
    const el = liveOutputRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [shownLiveOutput, manualExpanded])

  const handleCopyArgs = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const text = isShellTerminal
      ? `${formattedArgs}${shellOutput ? `\n${shellOutput}` : ''}`
      : formattedArgs || args || ''
    try {
      await navigator.clipboard.writeText(text)
      setCopiedArgs(true)
      setTimeout(() => setCopiedArgs(false), 1500)
    } catch {
      // ignore
    }
  }

  const handleCopyResult = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const text = result || ''
    try {
      await navigator.clipboard.writeText(text)
      setCopiedResult(true)
      setTimeout(() => setCopiedResult(false), 1500)
    } catch {
      // ignore
    }
  }

  const hasDetails = Boolean(formattedArgs || shownLiveOutput || shownResult || hasReadResult)
  const expanded = manualExpanded ?? false
  const displayName = name || 'tool'
  const toolLabel = formatToolLabel(displayName)
  const title = headerTitle ? `${toolLabel}: ${headerTitle}` : toolLabel
  const elapsedMs = durationMs ?? (!done && startedAt ? now - startedAt : undefined)
  const activityLabel = state === 'start' || state === 'running'
    ? toolActivityLabel(name, state, headerTitle)
    : null

  // Cursor-like Task chrome for team_delegate — replace generic tool row.
  if (name === 'team_delegate') {
    let agent = 'agent'
    let taskTitle = 'Delegated task'
    let isolation: 'shared' | 'worktree' | undefined
    let repoCount: number | undefined
    try {
      const parsed = args ? (JSON.parse(args) as Record<string, unknown>) : {}
      agent =
        (typeof parsed.to === 'string' && parsed.to) ||
        (typeof parsed.agent === 'string' && parsed.agent) ||
        (typeof parsed.member === 'string' && parsed.member) ||
        'agent'
      taskTitle =
        (typeof parsed.title === 'string' && parsed.title) ||
        (typeof parsed.task === 'string' && parsed.task) ||
        (typeof parsed.goal === 'string' && parsed.goal) ||
        (typeof parsed.content === 'string' && parsed.content) ||
        (typeof parsed.prompt === 'string' && parsed.prompt) ||
        taskTitle
      isolation =
        parsed.isolation === 'worktree' || parsed.isolation === 'shared'
          ? parsed.isolation
          : undefined
      repoCount = Array.isArray(parsed.target_repos) ? parsed.target_repos.length : undefined
    } catch {
      // keep defaults
    }
    const setActiveAgent = useTeamStore.getState().setActiveAgent
    return (
      <div className="my-2">
        <SubagentTaskCard
          agent={agent}
          title={taskTitle}
          status={isRunning ? 'running' : state === 'failed' ? 'idle' : 'done'}
          isolation={isolation}
          repoCount={repoCount}
          onFocus={() => setActiveAgent(agent)}
        />
      </div>
    )
  }

  return (
    <div className="my-2">
      {/* Header row — separate from the details container so collapsed tools stay lightweight. */}
      <button
        type="button"
        onClick={() => hasDetails && setManualExpanded(!expanded)}
        className={`group inline-flex max-w-full items-center gap-1.5 py-1 text-left text-xs transition-colors duration-(--motion-fast) ease-(--ease-out) focus-visible:outline-2 focus-visible:outline-(--focus-ring) ${
          hasDetails
            ? 'cursor-pointer text-(--color-text) hover:text-(--color-accent)'
            : 'cursor-default'
        }`}
        aria-expanded={expanded}
        aria-label={
          hasDetails
            ? expanded
              ? `Collapse ${displayName} details`
              : `Expand ${displayName} details`
            : `${displayName} (no details)`
        }
      >
        {/* Header content: tool-specific summary or fallback to tool name.
            Mono+600 per pencil dqwZw. */}
        {activityLabel ? (
          <ActivityStatus
            label={activityLabel}
            className="min-w-0 truncate font-mono text-xs"
          />
        ) : (
          <span className="min-w-0 truncate font-mono text-(--color-text)" title={title}>
            <span className="font-semibold">{toolLabel}</span>
            {visibleHeader && (
              <>
                <span>: </span>
                {/* Data inside the header is wrapped in `Arg` (display.tsx),
                    which carries its own `data-i18n-ignore`. */}
                <span title={headerTitle ?? undefined}>{visibleHeader}</span>
              </>
            )}
            {diffStats && (
              <span className="ml-2 inline-flex items-center gap-1 font-semibold select-none">
                {diffStats.additions > 0 && (
                  <span className="text-[var(--color-diff-add-text)]">+{diffStats.additions}</span>
                )}
                {diffStats.deletions > 0 && (
                  <span className="text-[var(--color-diff-del-text)]">-{diffStats.deletions}</span>
                )}
              </span>
            )}
          </span>
        )}

        {elapsedMs !== undefined && (
          <span className="shrink-0 font-mono text-xs text-(--color-text-muted)" title="Duration">
            {formatDuration(elapsedMs)}
          </span>
        )}

        {hasDetails && (
          <ChevronRight
            size={13}
            className={`shrink-0 text-(--color-text-muted) transition-transform duration-(--motion-fast) ease-(--ease-out) ${expanded ? 'rotate-90' : ''}`}
            aria-hidden
          />
        )}
      </button>

      {/* "See Browser" button — visible when browser_use tool is active */}
      {name === 'browser_use' && <SeeBrowserButton />}

      <ToolAttachments attachments={attachments} />

      {/* Expandable details — divider then warm paper body per pencil LJOUY */}
      <AnimatePresence initial={false}>
        {expanded && hasDetails && (
          <motion.div
            key="tool-details"
            initial={preset.intensity === 'reduced' ? false : { height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={preset.intensity === 'reduced' ? undefined : { height: 0, opacity: 0 }}
            transition={panelTransition(preset)}
            className="overflow-hidden"
          >
            <section className="group relative mt-1 ml-2 overflow-hidden border-l border-(--color-border) pl-3">
              {usesDiffView ? (
                <DiffView
                  toolName={name}
                  args={args || ''}
                  result={result}
                  onCollapse={() => setManualExpanded(false)}
                />
              ) : usesReadView && result ? (
                <ReadView
                  args={args || ''}
                  result={result}
                  onCollapse={() => setManualExpanded(false)}
                />
              ) : (
                <>
                  {/* Args section — caption + copy sit above the content. */}
                  {formattedArgs && (
                    <div>
                      <div className="flex items-center justify-between gap-3 border-b border-(--color-border) bg-(--bg-key) py-0.5 pr-1.5 pl-3">
                        <span className="font-mono text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                          {isShellTerminal ? 'terminal' : 'arguments'}
                        </span>
                        <button
                          type="button"
                          onClick={handleCopyArgs}
                          className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) opacity-100 transition-[opacity,background-color,color] duration-(--motion-fast) hover:bg-(--bg-key) hover:text-(--color-text-2) focus-visible:outline-2 focus-visible:outline-(--focus-ring) md:h-6 md:w-6 md:opacity-0 md:group-hover:opacity-100"
                          aria-label="Copy arguments"
                          title="Copy"
                        >
                          {copiedArgs ? (
                            <Check size={12} className="text-(--color-success)" />
                          ) : (
                            <Copy size={12} />
                          )}
                        </button>
                      </div>
                      {isShellTerminal ? (
                        <div className="flex flex-col gap-1 p-2.5">
                          <pre
                            ref={shownLiveOutput ? liveOutputRef : undefined}
                            className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-(--color-text)"
                          >
                            <span className="select-none text-(--color-text-muted)">$ </span>
                            <span className="text-(--color-accent)">{formattedArgs}</span>
                            {shellOutput ? `\n${shellOutput}` : ''}
                          </pre>
                          {shellResult?.statusLine && (
                            <span
                              data-i18n-ignore
                              className={`font-mono text-xs font-medium ${
                                shellResult.statusLine.startsWith('[Succeeded')
                                  ? 'text-(--color-success)'
                                  : 'text-(--color-error)'
                              }`}
                            >
                              {shellResult.statusLine}
                            </span>
                          )}
                        </div>
                      ) : (
                        <pre className="overflow-auto whitespace-pre-wrap break-all px-3 py-2.5 font-mono text-xs leading-relaxed text-(--color-text)">
                          {formattedArgs}
                        </pre>
                      )}
                    </div>
                  )}

                  {shownLiveOutput && !isShellTerminal && (
                    <div>
                      <div className={`flex items-center justify-between gap-3 border-b border-(--color-border) bg-(--bg-key) py-0.5 pr-1.5 pl-3 ${formattedArgs ? 'border-t' : ''}`}>
                        <span className="font-mono text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                          output
                        </span>
                      </div>
                      <pre
                        ref={liveOutputRef}
                        className="max-h-64 overflow-auto whitespace-pre-wrap break-words px-3 py-2.5 font-mono text-xs leading-relaxed text-(--color-text)"
                      >
                        {shownLiveOutput}
                      </pre>
                    </div>
                  )}

                  {/* Result section — same caption treatment as args. */}
                  {shownResult && !isShellTerminal && (
                    <div>
                      <div className={`flex items-center justify-between gap-3 border-b border-(--color-border) bg-(--bg-key) py-0.5 pr-1.5 pl-3 ${formattedArgs || shownLiveOutput ? 'border-t' : ''}`}>
                        <span className="font-mono text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                          result
                        </span>
                        <button
                          type="button"
                          onClick={handleCopyResult}
                          className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) opacity-100 transition-[opacity,background-color,color] duration-(--motion-fast) hover:bg-(--bg-key) hover:text-(--color-text-2) focus-visible:outline-2 focus-visible:outline-(--focus-ring) md:h-6 md:w-6 md:opacity-0 md:group-hover:opacity-100"
                          aria-label="Copy result"
                          title="Copy result"
                        >
                          {copiedResult ? (
                            <Check size={12} className="text-(--color-success)" />
                          ) : (
                            <Copy size={12} />
                          )}
                        </button>
                      </div>
                      <div data-i18n-ignore className="px-3 py-2.5 text-xs leading-relaxed text-(--color-text)">
                        <ToolResult toolName={name} result={shownResult} />
                      </div>
                    </div>
                  )}
                </>
              )}
            </section>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
})

function SeeBrowserButton() {
  const toggleBrowser = useUIStore((s) => s.toggleBrowser)
  const browserOpen = useUIStore((s) =>
    s.workbenchTabs.some((tab) => tab.tool === 'browser'),
  )
  const browserActive = useTeamStore((s) => s.browserSession?.active ?? false)

  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        toggleBrowser()
      }}
      className={`ml-1 inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold transition-colors border focus-visible:outline-2 focus-visible:outline-(--focus-ring) ${
        browserOpen
          ? 'border-(--accent-blue) bg-(--accent-blue) text-(--color-text-on-accent)'
          : browserActive
            ? 'border-(--accent-blue) bg-(--accent-blue-soft) text-(--accent-blue-text) hover:bg-(--accent-blue) hover:text-(--color-text-on-accent) hover:border-(--accent-blue)'
            : 'border-(--color-border-strong) bg-(--bg-page) text-(--accent-blue-text) hover:bg-(--accent-blue-soft) hover:border-(--accent-blue)'
      }`}
      title={browserOpen ? 'Hide browser panel' : 'See browser live'}
    >
      <MonitorPlayIcon size={11} />
      <span>{browserOpen ? 'Hide' : 'See Browser'}</span>
    </button>
  )
}
