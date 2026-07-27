/**
 * HandoffCard — renders a structured handoff artifact inline.
 *
 * Replaces the plain InboxBubble when the inbox block carries
 * `extra._handoff_artifact`.  Shows summary, findings, evidence,
 * confidence, verification status, and next actions in a compact card.
 */

import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, ChevronUp, CheckCircle2, AlertTriangle, ArrowRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { panelTransition, useMotionPreset } from '@/lib/motion'

interface HandoffArtifact {
  summary: string
  status?: 'partial' | 'final'
  findings?: string[]
  evidence?: string[]
  confidence?: number | null
  next_actions?: string[]
  raw_data?: string | null
  verification?: {
    verified: boolean
    method: string
    result?: string | null
  } | null
}

interface HandoffCardProps {
  artifact: HandoffArtifact
  fromAgent: string
  compact?: boolean
}

function ConfidenceMeter({ value, compact }: { value: number; compact?: boolean }) {
  const pct = Math.round(value * 100)
  const color = value >= 0.8
    ? 'bg-(--color-success)'
    : value >= 0.5
      ? 'bg-(--color-warning)'
      : 'bg-(--color-error)'
  return (
    <div className={`flex items-center gap-2 ${compact ? 'text-xs' : 'text-xs'}`}>
      <span className="text-(--color-text-muted)">Confidence</span>
      <div className={`${compact ? 'h-1 w-12' : 'h-1.5 w-16'} overflow-hidden rounded-full bg-(--color-border)`}>
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-(--color-text-2)">{pct}%</span>
    </div>
  )
}

export function HandoffCard({ artifact, fromAgent, compact = false }: HandoffCardProps) {
  const preset = useMotionPreset()
  const [expanded, setExpanded] = useState(false)
  const hasDetails = Boolean(
    (artifact.findings && artifact.findings.length > 0) ||
    (artifact.evidence && artifact.evidence.length > 0) ||
    (artifact.next_actions && artifact.next_actions.length > 0) ||
    artifact.raw_data ||
    artifact.verification,
  )

  const textSize  = compact ? 'text-xs'    : 'text-sm'
  const maxWidth  = compact ? 'max-w-[88%]' : 'max-w-[78%]'
  const padding   = compact ? 'px-3 py-2'  : 'px-4 py-3'
  const labelSize = compact ? 'text-xs' : 'text-xs'

  const isPartial = artifact.status === 'partial'

  return (
    <div className="mb-4 flex justify-start">
      <div
        className={[
          maxWidth,
          padding,
          textSize,
          'relative rounded-lg rounded-bl-sm',
          isPartial
            ? 'border border-dashed border-(--color-warning)/50 bg-(--color-surface)'
            : 'border border-(--color-accent)/30 bg-(--color-surface)',
          'leading-relaxed text-(--color-text) shadow-sm',
        ].join(' ')}
      >
        {/* Header */}
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <p className={`${labelSize} font-semibold tracking-wide text-(--color-text-2)`}>
              Handoff from {fromAgent}
            </p>
            <Badge variant={isPartial ? 'outline' : 'secondary'} className={`${compact ? 'text-xs px-1 py-0' : 'text-xs px-1.5 py-0'}`}>
              {isPartial ? 'partial' : 'final'}
            </Badge>
          </div>

          {hasDetails && (
            <button
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
              title={expanded ? 'Collapse' : 'Expand'}
              className={[
                'flex items-center justify-center shrink-0',
                'rounded-md border border-(--color-border)',
                'bg-(--bg-page) text-(--color-text-muted)',
                compact ? 'h-4 w-4' : 'h-5 w-5',
                'transition-[background-color,border-color,box-shadow,opacity] duration-(--motion-fast)',
                'hover:border-(--color-accent) hover:text-(--color-accent)',
                'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-(--color-accent)',
                'active:scale-90',
              ].join(' ')}
            >
              {expanded
                ? <ChevronUp size={compact ? 10 : 12} />
                : <ChevronDown size={compact ? 10 : 12} />}
            </button>
          )}
        </div>

        {/* Summary */}
        <p className="text-(--color-text)">{artifact.summary}</p>

        {/* Confidence + Verification — always visible */}
        {(artifact.confidence != null || artifact.verification) && (
          <div className={`mt-2 flex flex-wrap items-center gap-3 ${compact ? 'gap-2' : 'gap-3'}`}>
            {artifact.confidence != null && (
              <ConfidenceMeter value={artifact.confidence} compact={compact} />
            )}
            {artifact.verification && (
              <span className={`flex items-center gap-1 ${labelSize} ${artifact.verification.verified ? 'text-(--color-success)' : 'text-(--color-warning)'}`}>
                {artifact.verification.verified
                  ? <><CheckCircle2 size={compact ? 10 : 12} /> {artifact.verification.method}</>
                  : <><AlertTriangle size={compact ? 10 : 12} /> Not verified</>}
              </span>
            )}
          </div>
        )}

        {/* Expandable details */}
        <AnimatePresence initial={false}>
          {expanded && hasDetails && (
            <motion.div
              key="handoff-details"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={panelTransition(preset)}
              className="overflow-hidden"
            >
              <div className={`mt-3 space-y-2 border-t border-(--color-border) pt-2 ${labelSize}`}>
                {artifact.findings && artifact.findings.length > 0 && (
                  <div>
                    <p className="mb-1 font-semibold text-(--color-text-2)">Findings</p>
                    <ul className="list-inside list-disc space-y-0.5 text-(--color-text)">
                      {artifact.findings.map((f, i) => <li key={i}>{f}</li>)}
                    </ul>
                  </div>
                )}
                {artifact.evidence && artifact.evidence.length > 0 && (
                  <div>
                    <p className="mb-1 font-semibold text-(--color-text-2)">Evidence</p>
                    <ul className="list-inside list-disc space-y-0.5 text-(--color-text-muted)">
                      {artifact.evidence.map((e, i) => <li key={i}>{e}</li>)}
                    </ul>
                  </div>
                )}
                {artifact.next_actions && artifact.next_actions.length > 0 && (
                  <div>
                    <p className="mb-1 font-semibold text-(--color-text-2)">Next Actions</p>
                    <ul className="space-y-0.5 text-(--color-text)">
                      {artifact.next_actions.map((a, i) => (
                        <li key={i} className="flex items-start gap-1">
                          <ArrowRight size={compact ? 10 : 12} className="mt-0.5 shrink-0 text-(--color-accent)" />
                          <span>{a}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {artifact.verification?.result && (
                  <div>
                    <p className="mb-1 font-semibold text-(--color-text-2)">Verification Result</p>
                    <p className="text-(--color-text-muted)">{artifact.verification.result}</p>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
