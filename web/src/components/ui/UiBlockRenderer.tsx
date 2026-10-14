import { useState } from 'react'
import { useTeamStore } from '@/stores/useTeamStore'
import { UiButtons } from './UiButtons'
import { UiCalculator } from './UiCalculator'
import { UiCallout } from './UiCallout'
import { UiChart } from './UiChart'
import { UiChecklist } from './UiChecklist'
import { UiFlashcards } from './UiFlashcards'
import { UiForm } from './UiForm'
import { UiKeyValue } from './UiKeyValue'
import { UiProgress } from './UiProgress'
import { UiStatCards } from './UiStatCards'
import { UiSteps } from './UiSteps'
import { UiTable } from './UiTable'
import { UiCustom } from './UiCustom'
import { UiLayout } from './UiLayout'
import type { UiBlockNode, UiInteractionState } from './ui-block-types'
import { UI_BLOCK_MAX_DEPTH } from './ui-block-types'

export interface UiBlockRendererProps {
  blocks: UiBlockNode[]
  /** Group title stamped on the block (tool's `title` argument). */
  title?: string
  /**
   * Overrides the prompt sink (tests). Default falls back to
   * `useTeamStore.sendMessage` — the same fallback as WidgetRenderer.
   */
  onSendPrompt?: (prompt: string) => Promise<boolean> | boolean | void
  /** Announce progress updates to assistive tech (live streaming). */
  live?: boolean
}

function UnsupportedCard({ type }: { type?: string }) {
  return (
    <div className="rounded-md border border-dashed border-(--color-border) px-3 py-2 text-sm text-(--color-text-muted)">
      Unsupported block{type ? `: ${type}` : ''}
    </div>
  )
}

function renderNode(node: UiBlockNode, live?: boolean) {
  switch (node.type) {
    case 'stat_cards':
      return <UiStatCards block={node} />
    case 'chart':
      return <UiChart spec={node.spec} />
    case 'steps':
      return <UiSteps block={node} />
    case 'table':
      return <UiTable block={node} />
    case 'key_value':
      return <UiKeyValue block={node} />
    case 'callout':
      return <UiCallout block={node} />
    case 'progress':
      return <UiProgress block={node} live={live} />
    case 'flashcards':
      return <UiFlashcards block={node} />
    case 'checklist':
      return <UiChecklist block={node} />
    case 'calculator':
      return <UiCalculator block={node} />
    default:
      // Forward-compat: unknown node types render a neutral card (§5.5).
      return <UnsupportedCard type={(node as { type?: string }).type} />
  }
}

export function UiBlockRenderer({ blocks, title, onSendPrompt, live }: UiBlockRendererProps) {
  const storeSendPrompt = useTeamStore((s) => s.sendMessage)
  const [state, setState] = useState<UiInteractionState>('idle')

  const sendPrompt = (prompt: string) => {
    if (state === 'pending') return
    setState('pending')
    const send = onSendPrompt ?? storeSendPrompt
    Promise.resolve(send(prompt))
      .then((ok) => setState(ok === false ? 'failed' : 'submitted'))
      .catch(() => setState('failed'))
  }

  const nodes = Array.isArray(blocks) ? blocks : []

  // Depth-threaded dispatch for layout children (spec §2.2/§2.3): `layout`
  // nodes render through UiLayout's renderChild while under the cap; deeper
  // ones fall back to the existing UiCallout so malformed/hand-edited tool
  // args that bypassed server validation still terminate.
  const renderChildAt = (node: UiBlockNode, depth: number) => {
    switch (node.type) {
      case 'buttons':
        return <UiButtons block={node} onSendPrompt={sendPrompt} />
      case 'form':
        return <UiForm block={node} onSendPrompt={sendPrompt} />
      case 'layout':
        if (depth >= UI_BLOCK_MAX_DEPTH)
          return (
            <UiCallout
              block={{ type: 'callout', tone: 'warning', body: 'Layout nested too deep' }}
            />
          )
        return <UiLayout block={node} depth={depth} renderChild={renderChildAt} />
      case 'custom':
        return <UiCustom block={node} />
      default:
        return renderNode(node, live)
    }
  }

  return (
    <div className="space-y-2">
      {title && <p className="text-xs font-medium text-(--color-text-muted)">{title}</p>}
      {nodes.map((node, i) => {
        if (!node || typeof node !== 'object' || typeof node.type !== 'string')
          return <UnsupportedCard key={i} />
        switch (node.type) {
          case 'buttons':
            return <UiButtons key={i} block={node} onSendPrompt={sendPrompt} />
          case 'form':
            return <UiForm key={i} block={node} onSendPrompt={sendPrompt} />
          case 'layout':
          case 'custom':
            return <div key={i}>{renderChildAt(node, 0)}</div>
          default:
            return <div key={i}>{renderNode(node, live)}</div>
        }
      })}
      <p role="status" aria-live="polite" className="min-h-4 text-xs text-(--color-text-muted)">
        {state === 'pending' && 'Sending…'}
        {state === 'submitted' && 'Sent — the agent will reply in this chat.'}
        {state === 'failed' && 'Could not send — please try again.'}
      </p>
    </div>
  )
}
