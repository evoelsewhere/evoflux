import { AlertTriangle, CheckCircle2, CircleDashed, XCircle } from 'lucide-react'

import type { AsddChangeDetail } from '@/api/types'
import { cn } from '@/lib/utils'
import { LazyMarkdownBlock } from '@/utils/LazyMarkdownBlock'

/**
 * Renders the change's artifacts the way a reviewer reads them on disk.
 *
 * Deliberately shows the Markdown rather than a form built from it: the file is
 * the contract, and a field-by-field rendering would quietly become a second
 * representation that can disagree with what is committed.
 */
export type AsddArtifactTab = 'proposal' | 'specs' | 'design' | 'tasks' | 'evidence'

const RESULT_ICONS = {
  passed: CheckCircle2,
  failed: XCircle,
  inconclusive: CircleDashed,
} as const

const RESULT_TONES: Record<string, string> = {
  passed: 'text-(--color-success)',
  failed: 'text-(--color-danger)',
  inconclusive: 'text-(--color-warning)',
}

function Empty({ children }: { children: string }) {
  return (
    <p className="rounded-lg border border-dashed border-(--color-border) px-3 py-6 text-center text-[11px] text-(--color-text-subtle)">
      {children}
    </p>
  )
}

export function AsddArtifactView({
  detail,
  tab,
}: {
  detail: AsddChangeDetail
  tab: AsddArtifactTab
}) {
  if (tab === 'proposal') {
    return detail.proposal.trim() ? (
      <div className="oa-prose text-xs">
        <LazyMarkdownBlock content={detail.proposal} />
      </div>
    ) : (
      <Empty>The proposal is still empty. Run “Draft proposal” to write it.</Empty>
    )
  }

  if (tab === 'design') {
    return detail.design ? (
      <div className="oa-prose text-xs">
        <LazyMarkdownBlock content={detail.design} />
      </div>
    ) : (
      <Empty>This change has no design document.</Empty>
    )
  }

  if (tab === 'tasks') {
    return detail.tasks ? (
      <div className="oa-prose text-xs">
        <LazyMarkdownBlock content={detail.tasks} />
      </div>
    ) : (
      <Empty>No task checklist has been written yet.</Empty>
    )
  }

  if (tab === 'evidence') {
    if (detail.evidence.length === 0) {
      return <Empty>Nothing has been recorded under evidence/ yet.</Empty>
    }
    return (
      <ul className="flex flex-col gap-2">
        {detail.evidence.map((item) => {
          const Icon = RESULT_ICONS[item.result as keyof typeof RESULT_ICONS] ?? CircleDashed
          return (
            <li
              key={item.id}
              className="rounded-lg border border-(--color-border) bg-(--bg-surface) px-3 py-2"
            >
              <div className="flex items-center gap-2">
                <Icon
                  size={12}
                  className={cn('shrink-0', RESULT_TONES[item.result] ?? 'text-(--color-text-subtle)')}
                />
                <span className="truncate font-mono text-[11px] font-medium text-(--color-text)">
                  {item.id}
                </span>
                <span className="rounded-full bg-(--bg-key)/70 px-1.5 py-0.5 text-[9px] uppercase tracking-[0.08em] text-(--color-text-subtle)">
                  {item.kind}
                </span>
                {item.requirement && (
                  <span className="ml-auto truncate text-[10px] text-(--color-text-muted)">
                    {item.requirement}
                  </span>
                )}
              </div>
              <p className="mt-1 text-[11px] leading-4 text-(--color-text-2)">{item.summary}</p>
            </li>
          )
        })}
      </ul>
    )
  }

  if (detail.deltas.length === 0) {
    return <Empty>No capability delta has been written yet.</Empty>
  }

  return (
    <div className="flex flex-col gap-4">
      {detail.deltas.map((delta) => (
        <section key={delta.capability}>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-mono text-xs font-semibold text-(--color-text)">
              {delta.capability}
            </h3>
            {delta.added.length > 0 && (
              <span className="rounded-full bg-(--color-success-subtle) px-1.5 py-0.5 text-[9px] font-medium text-(--color-success)">
                +{delta.added.length} added
              </span>
            )}
            {delta.modified.length > 0 && (
              <span className="rounded-full bg-(--color-warning)/12 px-1.5 py-0.5 text-[9px] font-medium text-(--color-warning)">
                ~{delta.modified.length} modified
              </span>
            )}
            {delta.removed.length > 0 && (
              <span className="rounded-full bg-(--color-danger)/12 px-1.5 py-0.5 text-[9px] font-medium text-(--color-danger)">
                −{delta.removed.length} removed
              </span>
            )}
          </div>

          {delta.problems.length > 0 && (
            <ul
              role="alert"
              className="mt-1.5 rounded-lg border border-(--color-warning)/35 bg-(--color-warning)/8 px-2.5 py-2 text-[10px] leading-4 text-(--color-text-muted)"
            >
              {delta.problems.map((problem) => (
                <li key={problem} className="flex items-start gap-1.5">
                  <AlertTriangle size={10} className="mt-0.5 shrink-0 text-(--color-warning)" />
                  {problem}
                </li>
              ))}
            </ul>
          )}

          <div className="oa-prose mt-2 text-xs">
            <LazyMarkdownBlock content={delta.body} />
          </div>
        </section>
      ))}
    </div>
  )
}
