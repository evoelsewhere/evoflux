import { useState } from 'react'
import type { VisualArtifactPayload } from '@/api/types'
import { VisualArtifactFrame } from '@/components/VisualArtifactFrame'
import type { ThemePreference } from '@/lib/theme'

interface Props {
  artifact: VisualArtifactPayload
  theme: ThemePreference
  reducedMotion: boolean
  onSendPrompt: (prompt: string) => void
}

export function DashboardArtifact({ artifact, theme, reducedMotion, onSendPrompt }: Props) {
  const [expanded, setExpanded] = useState(false)
  const verified = artifact.sources.filter((source) => source.verified)
  return (
    <section className="my-2 overflow-hidden rounded-xl border border-(--color-border) bg-(--color-surface)" aria-label={`${artifact.title} dashboard`}>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-(--color-border) px-4 py-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-(--color-text-primary)">{artifact.title}</h3>
          <p className="mt-1 text-xs text-(--color-text-subtle)">{artifact.summary}</p>
        </div>
        <button type="button" className="rounded-md border border-(--color-border) px-3 py-1.5 text-xs font-medium hover:bg-(--color-surface-hover)" onClick={() => onSendPrompt(`Refresh this dashboard using the same available data sources. Re-run the relevant source tools and replace artifact_id "${artifact.artifactId}" in place.`)}>
          Refresh with agent
        </button>
      </header>
      <VisualArtifactFrame artifact={artifact} theme={theme} reducedMotion={reducedMotion} onSendPrompt={onSendPrompt} />
      <div className="border-t border-(--color-border) px-4 py-2.5">
        {verified.length > 0 ? (
          <>
            <button type="button" aria-expanded={expanded} className="text-xs font-medium text-(--color-accent)" onClick={() => setExpanded((value) => !value)}>
              {expanded ? 'Hide data sources' : `Data sources · ${verified.length}`}
            </button>
            {expanded && <ul className="mt-2 space-y-2 text-xs text-(--color-text-subtle)">
              {verified.map((source) => (
                <li key={source.toolCallId} className="rounded-md bg-(--color-surface-subtle) p-2">
                  <p><span className="font-mono text-(--color-text-primary)">{source.toolName ?? 'Source tool'}</span> · {source.querySummary}</p>
                  <details className="mt-1">
                    <summary className="cursor-pointer">View saved arguments and result</summary>
                    {source.arguments && <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap">{source.arguments}</pre>}
                    {source.result && <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap">{source.result}</pre>}
                  </details>
                </li>
              ))}
            </ul>}
          </>
        ) : <p className="text-xs text-(--color-text-subtle)">Illustrative example · no verified source tool call is attached.</p>}
      </div>
    </section>
  )
}
