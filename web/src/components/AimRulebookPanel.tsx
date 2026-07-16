/**
 * AimRulebookPanel — read-only view of the project's rulebook pack
 * (aim-mode-shell-ux-spec.md v2.2 J5): the manifest header plus every
 * text artifact in the pack (mappings, canonicalizers, extractors,
 * runners, target-base checklist). Answers "what rules does this line
 * convert by?" without opening the EvoFlux repo.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText, Loader2 } from 'lucide-react'
import { getAimRulebook } from '@/api/client'
import { MarkdownBlock } from '@/utils/markdown'
import { cn } from '@/lib/utils'
import type { CodingProject } from '@/api/types'

export function AimRulebookPanel({ project }: { project: CodingProject }) {
  const [selected, setSelected] = useState<string>('rulebook.yaml')

  const rulebookQuery = useQuery({
    queryKey: ['projects', 'detail', project.id, 'aim-rulebook'],
    queryFn: () => getAimRulebook(project.id),
    staleTime: 60_000,
  })
  const rulebook = rulebookQuery.data
  const selectedFile = rulebook?.files.find((f) => f.path === selected) ?? rulebook?.files[0]

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-(--color-border) px-4 py-3">
        <p className="text-sm font-medium text-(--color-text)">Rulebook</p>
        {rulebook && (
          <>
            <span className="rounded bg-(--bg-key) px-2 py-0.5 text-[10px] text-(--color-text-subtle)">
              {rulebook.id}
              {typeof rulebook.manifest.version === 'string'
                ? ` v${rulebook.manifest.version}`
                : ''}
            </span>
            {typeof rulebook.manifest.parser_strategy === 'string' && (
              <span className="rounded bg-(--bg-key) px-2 py-0.5 text-[10px] text-(--color-text-subtle)">
                parser: {rulebook.manifest.parser_strategy}
              </span>
            )}
            <span className="text-[10px] text-(--color-text-subtle)">read-only</span>
          </>
        )}
      </div>

      {rulebookQuery.isLoading ? (
        <p className="flex items-center gap-1.5 p-4 text-xs text-(--color-text-subtle)">
          <Loader2 size={12} className="animate-spin" /> Loading rulebook…
        </p>
      ) : rulebookQuery.isError ? (
        <p className="p-4 text-xs text-(--color-error)">
          {rulebookQuery.error instanceof Error
            ? rulebookQuery.error.message
            : 'Rulebook pack is not installed on this machine.'}
        </p>
      ) : (
        <div className="flex min-h-0 flex-1">
          <div className="w-72 shrink-0 overflow-y-auto border-r border-(--color-border) p-2">
            {rulebook?.files.map((file) => (
              <button
                key={file.path}
                type="button"
                onClick={() => setSelected(file.path)}
                className={cn(
                  'flex w-full items-center gap-1.5 truncate rounded px-2 py-1 text-left text-xs transition-colors',
                  selectedFile?.path === file.path
                    ? 'bg-(--bg-key) text-(--color-text)'
                    : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
                )}
                title={file.path}
              >
                <FileText size={11} className="shrink-0" />
                <span className="truncate">{file.path}</span>
              </button>
            ))}
          </div>
          <div className="min-w-0 flex-1 overflow-y-auto p-4">
            {!selectedFile ? (
              <p className="text-xs text-(--color-text-subtle)">Pack has no readable files.</p>
            ) : selectedFile.path.endsWith('.md') ? (
              <div className="prose prose-sm max-w-none text-sm text-(--color-text)">
                <MarkdownBlock content={selectedFile.content} />
              </div>
            ) : (
              <pre className="whitespace-pre-wrap font-mono text-xs leading-4 text-(--color-text-2)">
                {selectedFile.content}
              </pre>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
