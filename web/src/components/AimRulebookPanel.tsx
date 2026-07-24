/**
 * AimRulebookPanel — read-only view of the project's local rulebook
 * (aim-mode-shell-ux-spec.md v2.2 J5): answers "what rules does this line
 * convert by?" without opening the EvoFlux repo.
 *
 * Two layers, mirroring how an architect reads a rulebook:
 * - Overview (default): the manifest made legible — description, source →
 *   target stacks with their file extensions, unit kinds, parser strategy,
 *   extractors, agent/skill overlays, runners, compare profile.
 * - Files: the rulebook artifacts in the same folder tree + kind-aware
 *   preview the KB screen uses (frontmatter strip + markdown for .md,
 *   code block for yaml/sh).
 */

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, BookMarked, Loader2 } from 'lucide-react'
import { getAimRulebook } from '@/api/client'
import { MarkdownBlock, CodeBlock } from '@/utils/markdown'
import { splitFrontmatter } from '@/lib/aim-kb'
import { buildTree } from '@/utils/workspaceFileTree'
import { TreeNodeView } from '@/components/CodingWorkspacePanel'
import { cn } from '@/lib/utils'
import type { AimRulebook, CodingProject, WorkspaceFileInfo } from '@/api/types'

const EMPTY_CHANGED_PATHS = new Set<string>()

/** The manifest's known fields, typed loosely — packs evolve ahead of the
 * UI, so everything is optional and unknown keys still show under Files. */
interface ManifestShape {
  description?: string
  source?: { stack?: string; file_extensions?: string[] }
  target?: { stack?: string; file_extensions?: string[] }
  unit_kinds?: string[]
  parser_strategy?: string
  extractors?: string[]
  compare_default_profile?: string
  overlays?: { agents?: string[]; skills?: string[] }
  runners?: Record<string, string>
  capabilities?: Record<string, 'ready' | 'template' | 'unavailable'>
}

export function AimRulebookPanel({ project }: { project: CodingProject }) {
  // '' = the Overview pseudo-item; anything else is a rulebook file path.
  const [selected, setSelected] = useState<string>('')

  const rulebookQuery = useQuery({
    queryKey: ['projects', 'detail', project.id, 'aim-rulebook'],
    queryFn: () => getAimRulebook(project.id),
    staleTime: 60_000,
  })
  const rulebook = rulebookQuery.data
  const manifest = (rulebook?.manifest ?? {}) as ManifestShape

  // The KB screen's tree wants WorkspaceFileInfo — synthesize it from the
  // rulebook's inline files (content already came down with the response).
  const treeFiles = useMemo<WorkspaceFileInfo[]>(
    () =>
      (rulebook?.files ?? []).map((file) => ({
        path: file.path,
        name: file.path.split('/').pop() ?? file.path,
        size: new Blob([file.content]).size,
        mtime: 0,
        mime: 'text/plain',
      })),
    [rulebook?.files],
  )
  const tree = useMemo(() => buildTree(treeFiles), [treeFiles])
  const selectedFile = rulebook?.files.find((f) => f.path === selected) ?? null

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
            <span
              className="rounded bg-(--bg-key) px-2 py-0.5 text-[10px] text-(--color-text-subtle)"
              title="Defined in this project's KB repository at rulebook/."
            >
              project-owned
            </span>
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
            : 'The KB-local rulebook is unavailable or invalid.'}
        </p>
      ) : (
        <div className="flex min-h-0 flex-1">
          <div className="w-72 shrink-0 overflow-y-auto border-r border-(--color-border) p-2">
            {/* Overview pseudo-item above the rulebook's file tree */}
            <button
              type="button"
              onClick={() => setSelected('')}
              className={cn(
                'mb-1 flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs transition-colors',
                selected === ''
                  ? 'bg-(--bg-key) text-(--color-accent)'
                  : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)',
              )}
            >
              <BookMarked size={12} className="shrink-0" />
              <span className="truncate font-medium">Overview</span>
            </button>
            <TreeNodeView
              node={tree}
              depth={0}
              selectedPath={selected || null}
              onFileSelect={(file) => setSelected(file?.path ?? '')}
              changedPaths={EMPTY_CHANGED_PATHS}
            />
          </div>

          <div className="min-w-0 flex-1 overflow-y-auto p-4">
            {selected === '' || !selectedFile ? (
              rulebook && <ManifestOverview rulebook={rulebook} manifest={manifest} />
            ) : (
              <PackFilePreview path={selectedFile.path} content={selectedFile.content} />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Chips({ values }: { values: string[] }) {
  return (
    <span className="flex flex-wrap gap-1">
      {values.map((value) => (
        <span
          key={value}
          className="rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-[11px] text-(--color-text-2)"
        >
          {value}
        </span>
      ))}
    </span>
  )
}

function OverviewRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8.5rem_1fr] items-baseline gap-x-3 gap-y-1">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-(--color-text-subtle)">
        {label}
      </span>
      <div className="min-w-0 text-xs text-(--color-text-2)">{children}</div>
    </div>
  )
}

function ManifestOverview({
  rulebook,
  manifest,
}: {
  rulebook: AimRulebook
  manifest: ManifestShape
}) {
  const version =
    typeof rulebook.manifest.version === 'string' ? rulebook.manifest.version : null
  return (
    <div className="max-w-2xl space-y-4">
      {/* Identity: what migrates into what */}
      <div className="rounded-md bg-(--bg-key) px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-(--color-text)">{rulebook.id}</span>
          {version && (
            <span className="rounded bg-(--bg-page) px-1.5 py-0.5 text-[10px] text-(--color-text-subtle)">
              v{version}
            </span>
          )}
          {(manifest.source?.stack || manifest.target?.stack) && (
            <span className="ml-auto flex items-center gap-1.5 font-mono text-xs text-(--color-text-2)">
              {manifest.source?.stack ?? '?'}
              <ArrowRight size={12} className="text-(--color-accent)" />
              {manifest.target?.stack ?? '?'}
            </span>
          )}
        </div>
        {typeof manifest.description === 'string' && (
          <p className="mt-2 text-xs leading-5 text-(--color-text-muted)">
            {manifest.description.trim()}
          </p>
        )}
      </div>

      <div className="space-y-2.5">
        {manifest.source?.file_extensions && (
          <OverviewRow label="Source files">
            <Chips values={manifest.source.file_extensions} />
          </OverviewRow>
        )}
        {manifest.target?.file_extensions && (
          <OverviewRow label="Target files">
            <Chips values={manifest.target.file_extensions} />
          </OverviewRow>
        )}
        {manifest.unit_kinds && manifest.unit_kinds.length > 0 && (
          <OverviewRow label="Unit kinds">
            <Chips values={manifest.unit_kinds} />
          </OverviewRow>
        )}
        {manifest.capabilities && (
          <OverviewRow label="Capabilities">
            <span className="flex flex-wrap gap-1">
              {Object.entries(manifest.capabilities).map(([name, status]) => (
                <span
                  key={name}
                  className={cn(
                    'rounded px-1.5 py-0.5 font-mono text-[11px]',
                    status === 'ready'
                      ? 'bg-(--color-success-bg,var(--bg-key)) text-(--color-success)'
                      : status === 'template'
                        ? 'bg-(--bg-key) text-(--color-warning,orange)'
                        : 'bg-(--color-error-subtle,var(--bg-key)) text-(--color-error)',
                  )}
                >
                  {name}: {status}
                </span>
              ))}
            </span>
          </OverviewRow>
        )}
        {typeof manifest.parser_strategy === 'string' && (
          <OverviewRow label="Parser">
            <span className="font-mono">{manifest.parser_strategy}</span>
          </OverviewRow>
        )}
        {manifest.extractors && manifest.extractors.length > 0 && (
          <OverviewRow label="Extractors">
            <Chips values={manifest.extractors} />
          </OverviewRow>
        )}
        {manifest.overlays?.agents && manifest.overlays.agents.length > 0 && (
          <OverviewRow label="Agent overlays">
            <span className="flex flex-col gap-1">
              <Chips values={manifest.overlays.agents} />
              <span className="text-[10px] text-(--color-text-subtle)">
                Project reference guidance only. These files are not merged into the
                global AIM agent roster.
              </span>
            </span>
          </OverviewRow>
        )}
        {manifest.overlays?.skills && manifest.overlays.skills.length > 0 && (
          <OverviewRow label="Skill overlays">
            <span className="flex flex-col gap-1">
              <Chips values={manifest.overlays.skills} />
              <span className="text-[10px] text-(--color-text-subtle)">
                Project reference guidance only. These files are not installed into the
                global skill library.
              </span>
            </span>
          </OverviewRow>
        )}
        {manifest.runners && Object.keys(manifest.runners).length > 0 && (
          <OverviewRow label="Runners">
            <Chips
              values={Object.entries(manifest.runners).map(([key, value]) => `${key}: ${value}`)}
            />
          </OverviewRow>
        )}
        {typeof manifest.compare_default_profile === 'string' && (
          <OverviewRow label="Compare profile">
            <span className="font-mono">{manifest.compare_default_profile}</span>
          </OverviewRow>
        )}
        <OverviewRow label="Rulebook files">
          <span>
            {rulebook.files.length} readable file{rulebook.files.length === 1 ? '' : 's'} — browse
            them in the tree.
          </span>
        </OverviewRow>
      </div>
    </div>
  )
}

function PackFilePreview({ path, content }: { path: string; content: string }) {
  if (path.endsWith('.md')) {
    const { meta, body } = splitFrontmatter(content)
    return (
      <div>
        {meta.length > 0 && (
          <div className="mb-4 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-md bg-(--bg-key) px-3 py-2">
            {meta.map(([key, value]) => (
              <div key={key} className="contents">
                <span className="font-mono text-[10px] uppercase tracking-wider text-(--color-text-subtle)">
                  {key}
                </span>
                <span className="min-w-0 break-words text-xs text-(--color-text-2)">
                  {value || '—'}
                </span>
              </div>
            ))}
          </div>
        )}
        <div className="prose prose-sm max-w-none text-sm text-(--color-text)">
          <MarkdownBlock content={body} />
        </div>
      </div>
    )
  }
  const extension = path.split('.').pop()?.toLowerCase() ?? ''
  return (
    <CodeBlock language={extension || undefined} rawText={content}>
      {content}
    </CodeBlock>
  )
}
