/**
 * Footer rendered at the bottom of a completed assistant turn, plus the
 * `AssistantTurn` wrapper that groups a turn's blocks and decides when to
 * show the footer.
 *
 * Used by both the compact pane (split / unified) and the wide single-agent
 * view. Each view passes its own `renderBlock` so the per-view block visuals
 * (e.g. compact vs roomy `UserBubble`) stay independent.
 */
import { Fragment, useMemo, useState, type ReactNode } from 'react'
import { Copy, Check, Play } from 'lucide-react'
import { lastTurnText } from '@/utils/format'
import {
  formatTurnCost,
  formatTurnDuration,
  formatTurnTokens,
  shortModelName,
} from '@/utils/turn-meta'
import { cn } from '@/lib/utils'
import { AssistantTurnContent } from './AssistantTurnContent'
import { easdToolReviewTarget } from './easd/easdToolReviewTarget'
import type { ContentBlock, TurnCost, TurnUsage } from '@/api/types'

export interface AssistantTurnFooterProps {
  /** Blocks belonging to a single assistant turn (no user blocks inside). */
  turnBlocks: ContentBlock[]
  /** Visual density: 'compact' for narrow panes, 'roomy' for the wide view. */
  size?: 'compact' | 'roomy'
  /** Continue from this assistant turn. Only passed for the trailing lead turn. */
  onContinue?: () => void
}

function usageTooltip(usage: TurnUsage): string {
  const newline = String.fromCharCode(10)
  const lines = [`Input ${usage.input.toLocaleString()}`]
  if (usage.cache) lines.push(`  of which cached ${usage.cache.toLocaleString()}`)
  if (usage.cache_write) {
    lines.push(`  cache written ${usage.cache_write.toLocaleString()}`)
  }
  lines.push(`Output ${usage.output.toLocaleString()}`)
  if (usage.thoughts) lines.push(`  of which thinking ${usage.thoughts.toLocaleString()}`)
  if (usage.calls && usage.calls > 1) lines.push(`${usage.calls} model calls`)
  return lines.join(newline)
}

const COST_COMPONENT_LABELS: [keyof TurnCost, string][] = [
  ['input_usd', 'Input'],
  ['cache_read_usd', 'Cache read'],
  ['cache_write_usd', 'Cache write'],
  ['reasoning_usd', 'Thinking'],
  ['output_usd', 'Output'],
]

function costTooltip(cost: TurnCost): string {
  const newline = String.fromCharCode(10)
  const lines = COST_COMPONENT_LABELS.flatMap(([key, label]) => {
    const value = cost[key]
    return typeof value === 'number' && value > 0
      ? [`${label} ${formatTurnCost(value)}`]
      : []
  })
  lines.push(`Estimated from models.dev rates`)
  return lines.join(newline)
}

export function AssistantTurnFooter({ turnBlocks, size = 'compact', onContinue }: AssistantTurnFooterProps) {
  const [copied, setCopied] = useState(false)
  const footerData = useMemo(() => {
    // Me lastTurnText walks back to the previous user block; pass the turn directly
    const textContent = lastTurnText(turnBlocks)
    let responseDurationMs: number | undefined
    let modelId: string | undefined
    let turnUsage: TurnUsage | undefined
    let hasTool = false
    let hasEasdReviewAction = false
    for (let i = turnBlocks.length - 1; i >= 0; i--) {
      const block = turnBlocks[i]
      responseDurationMs ??= typeof block.responseDurationMs === 'number'
        ? block.responseDurationMs
        : undefined
      modelId ??= typeof block.extra?.model === 'string' ? block.extra.model : undefined
      turnUsage ??= block.turnUsage
      hasTool ||= block.type === 'tool'
      hasEasdReviewAction ||= block.type === 'tool' && Boolean(
        easdToolReviewTarget(block.toolName, block.toolArgs, block.toolResult),
      )
      if (
        responseDurationMs !== undefined
        && modelId !== undefined
        && turnUsage !== undefined
        && hasTool
        && hasEasdReviewAction
      ) break
    }
    return {
      textContent,
      responseDurationMs,
      modelId,
      modelName: shortModelName(modelId),
      turnUsage,
      hasTool,
      hasEasdReviewAction,
    }
  }, [turnBlocks])
  const {
    textContent, responseDurationMs, modelId, modelName, turnUsage,
    hasTool, hasEasdReviewAction,
  } = footerData
  const canContinue = Boolean(onContinue && (textContent || hasTool) && !hasEasdReviewAction)
  const totalTokens = turnUsage ? turnUsage.input + turnUsage.output : 0
  // `input` is summed across every model call in the turn, so a prompt that
  // was read from cache is counted once per call. Measured on a three-call
  // turn: 58,798 input tokens of which 38,592 were cache reads — so the
  // headline read as 59k next to a cost of $0.003, and anyone multiplying
  // the two got three times the real spend.
  //
  // Both cache classes are part of `input` and neither bills at the input
  // rate, so both break that multiplication — in opposite directions. Reads
  // are a fraction of the rate and make a turn look dearer than it was;
  // writes cost more than plain input and make it look cheaper. Naming the
  // shares is what lets the volume and the price agree.
  const inputShares = turnUsage && turnUsage.input > 0
    ? ([
        ['cached', turnUsage.cache ?? 0],
        ['written', turnUsage.cache_write ?? 0],
      ] as const)
        .map(([name, tokens]) => ({
          name,
          percent: Math.round((tokens / turnUsage.input) * 100),
        }))
        // Under a twentieth of the prompt explains nothing about the price.
        .filter((share) => share.percent >= 5)
    : []
  const cost = turnUsage?.cost


  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(textContent)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* ignore */ }
  }

  const iconSize = size === 'roomy' ? 11 : 10
  // One run of facts, middot-separated, in a single monospaced size. Five
  // values sat side by side with only whitespace between them read as one
  // ambiguous string — the separators are what make `8.6s 137k` two facts
  // instead of a number nobody can parse.
  const meta: { key: string; label: string; title?: string }[] = []
  if (modelName) meta.push({ key: 'model', label: modelName, title: modelId })
  if (responseDurationMs !== undefined) {
    meta.push({
      key: 'duration',
      label: formatTurnDuration(responseDurationMs),
      title: 'Response duration',
    })
  }
  if (turnUsage && totalTokens > 0) {
    meta.push({
      key: 'tokens',
      label: inputShares.length
        ? `${formatTurnTokens(totalTokens)} tokens · ${inputShares
            .map((share) => `${share.percent}% ${share.name}`)
            .join(', ')}`
        : `${formatTurnTokens(totalTokens)} tokens`,
      title: usageTooltip(turnUsage),
    })
  }
  if (cost && cost.estimated_usd > 0) {
    meta.push({
      key: 'cost',
      label: formatTurnCost(cost.estimated_usd),
      title: costTooltip(cost),
    })
  }

  if (!textContent && !canContinue && meta.length === 0) return null

  return (
    <div
      className={cn(
        'flex min-w-0 flex-wrap items-center',
        size === 'roomy' ? 'mt-1 gap-x-1.5 gap-y-0.5' : 'mt-0.5 gap-x-1 gap-y-0.5',
      )}
    >
      {textContent && (
        <button
          onClick={handleCopy}
          className="rounded-xs p-0.5 text-(--color-text-muted) transition-colors hover:text-(--color-text-2)"
          aria-label="Copy response"
          title="Copy"
        >
          {copied
            ? <Check size={iconSize} className="text-(--color-success)" />
            : <Copy size={iconSize} />}
        </button>
      )}
      {canContinue && onContinue && (
        <button
          onClick={onContinue}
          className="rounded-xs p-0.5 text-(--color-text-muted) transition-colors hover:text-(--color-text-2)"
          aria-label="Continue response"
          title="Continue"
        >
          <Play size={iconSize} />
        </button>
      )}
      {meta.map((item, index) => (
        <Fragment key={item.key}>
          {index > 0 && (
            <span
              aria-hidden="true"
              className="select-none text-(--color-text-subtle) text-xs"
            >
              ·
            </span>
          )}
          <span
            className="truncate font-mono text-(--color-text-subtle) text-xs"
            title={item.title}
          >
            {item.label}
          </span>
        </Fragment>
      ))}
    </div>
  )
}

export interface AssistantTurnProps {
  /** Blocks belonging to this turn (no user blocks inside). */
  blocks: ContentBlock[]
  /** Absolute index of `blocks[0]` in the parent's full block list. */
  startIndex: number
  /** True while the agent is actively streaming. */
  isWorking: boolean
  /** True when this turn has no user block after it (i.e. trailing). Only
   *  trailing turns can be "live"; any turn followed by a user message is
   *  finalized regardless of `isWorking`. */
  isTrailingTurn: boolean
  /** Total length of the parent's full block list (for `isLast` cursor). */
  totalBlocks: number
  /** Per-view block renderer. */
  renderBlock: (args: { block: ContentBlock; isStreaming: boolean; isLast: boolean }) => ReactNode
  /** Footer density. */
  size?: 'compact' | 'roomy'
  /** Continue from this turn when it is the trailing finalized lead turn. */
  onContinue?: () => void
  sessionId?: string
  latestMCPAppBlockIds?: Set<string>
}

export function AssistantTurn({
  blocks,
  startIndex,
  isWorking,
  isTrailingTurn,
  totalBlocks,
  renderBlock,
  size = 'compact',
  onContinue,
  sessionId,
  latestMCPAppBlockIds,
}: AssistantTurnProps) {
  const turnIsStreaming = isWorking && isTrailingTurn
  const canContinue = isTrailingTurn && !isWorking ? onContinue : undefined
  const blockAbsIdx = useMemo(
    () => new Map(blocks.map((b, j) => [b.id, startIndex + j])),
    [blocks, startIndex],
  )

  return (
    <div className="space-y-2">
      <AssistantTurnContent
        blocks={blocks}
        turnIsStreaming={turnIsStreaming}
        sessionId={sessionId}
        latestMCPAppBlockIds={latestMCPAppBlockIds}
        compact={size === 'compact'}
        renderBlock={({ block, isStreaming }) => renderBlock({
          block,
          isStreaming,
          isLast: (blockAbsIdx.get(block.id) ?? startIndex) === totalBlocks - 1,
        })}
      />
      {!turnIsStreaming && <AssistantTurnFooter turnBlocks={blocks} size={size} onContinue={canContinue} />}
    </div>
  )
}
