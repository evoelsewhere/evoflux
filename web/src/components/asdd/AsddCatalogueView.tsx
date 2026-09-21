/**
 * The capability catalogue and the archive.
 *
 * ASDD's current truth is `specs/<capability>/spec.md` — a change is only ever
 * a delta against it — but the panel had no way to read one. The counts in the
 * changes header said "4 capabilities · 2 archived" and led nowhere, so the one
 * artifact the method treats as authoritative was the one thing the UI could
 * not show.
 */
import { useMemo, useState } from 'react'
import { Archive, ChevronLeft, FileText, Layers, Loader2 } from 'lucide-react'

import type { AsddRepositoryListing } from '@/api/types'
import { useAsddSpecQuery } from '@/queries'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { LazyMarkdownBlock } from '@/utils/LazyMarkdownBlock'
import { errorText } from './vocabulary'

type CatalogueTab = 'capabilities' | 'archived'

const TAB_OPTIONS = [
  { value: 'capabilities', label: 'Capabilities' },
  { value: 'archived', label: 'Archived' },
] as const

/** `2026-09-17-add-spec-search-filter` reads better split into its two parts. */
function splitArchiveEntry(entry: string): { date: string; slug: string } {
  const match = /^(\d{4}-\d{2}-\d{2})-(.+)$/.exec(entry)
  return match ? { date: match[1], slug: match[2] } : { date: '', slug: entry }
}

function Empty({ icon: Icon, title, body }: { icon: typeof Layers; title: string; body: string }) {
  return (
    <div className="mx-auto mt-10 max-w-sm text-center">
      <Icon size={20} className="mx-auto text-(--color-text-subtle)" />
      <h3 className="mt-3 text-sm font-semibold text-(--color-text)">{title}</h3>
      <p className="mt-1 text-[11px] leading-4 text-(--color-text-muted)">{body}</p>
    </div>
  )
}

function SpecView({
  workspace,
  capability,
  onBack,
}: {
  workspace: string
  capability: string
  onBack: () => void
}) {
  const spec = useAsddSpecQuery(workspace, capability)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-start gap-2 border-b border-(--color-border) px-3 py-2.5">
        <Button type="button" variant="ghost" size="icon-sm" aria-label="Back" onClick={onBack}>
          <ChevronLeft />
        </Button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate font-mono text-sm font-semibold text-(--color-text)">
              {capability}
            </h2>
            {spec.data && (
              <span className="rounded-full bg-(--bg-key)/70 px-2 py-0.5 text-[10px] font-medium text-(--color-text-2)">
                {spec.data.requirements.length}{' '}
                {spec.data.requirements.length === 1 ? 'requirement' : 'requirements'}
              </span>
            )}
          </div>
          {spec.data && (
            <p className="mt-0.5 truncate font-mono text-[10px] text-(--color-text-subtle)">
              {spec.data.path}
            </p>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-3 py-3">
        {spec.isLoading && (
          <div className="flex justify-center py-10">
            <Loader2 size={15} className="animate-spin text-(--color-text-subtle)" />
          </div>
        )}
        {spec.isError && (
          <p role="alert" className="text-[11px] leading-4 text-(--color-danger)">
            {errorText(spec.error)}
          </p>
        )}
        {spec.data && (
          <div className="oa-prose text-xs">
            <LazyMarkdownBlock content={spec.data.body} />
          </div>
        )}
      </div>
    </div>
  )
}

export function AsddCatalogueView({
  workspace,
  capabilities,
  archived,
  repositories = [],
  onBack,
}: {
  workspace: string
  capabilities: string[]
  archived: string[]
  /**
   * Which repository holds which spec. The lists above are merged across the
   * whole scope, and a spec is a file in exactly one working tree — without
   * this a sibling's capability would be read from the wrong repository and
   * come back as "not found".
   */
  repositories?: AsddRepositoryListing[]
  onBack: () => void
}) {
  const [tab, setTab] = useState<CatalogueTab>('capabilities')
  const [openCapability, setOpenCapability] = useState<string | null>(null)

  const specOwner = useMemo(() => {
    const owner = new Map<string, string>()
    for (const repository of repositories) {
      for (const capability of repository.capabilities) {
        if (!owner.has(capability)) owner.set(capability, repository.path)
      }
    }
    return owner
  }, [repositories])

  if (openCapability) {
    return (
      <SpecView
        workspace={specOwner.get(openCapability) ?? workspace}
        capability={openCapability}
        onBack={() => setOpenCapability(null)}
      />
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-(--color-border) px-3 py-2.5">
        <Button type="button" variant="ghost" size="icon-sm" aria-label="Back" onClick={onBack}>
          <ChevronLeft />
        </Button>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-(--color-text)">Catalogue</h2>
          <p className="text-[10px] text-(--color-text-subtle)">
            What the repository contracts today, and the changes that got it there.
          </p>
        </div>
        <SegmentedControl
          value={tab}
          onChange={setTab}
          layoutId="asdd-catalogue-tab"
          ariaLabel="Catalogue section"
          options={TAB_OPTIONS}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {tab === 'capabilities' ? (
          capabilities.length === 0 ? (
            <Empty
              icon={Layers}
              title="No capability specs yet"
              body="A capability spec is written the first time a change that touches it is archived."
            />
          ) : (
            <ul className="flex flex-col gap-1.5">
              {capabilities.map((capability) => (
                <li key={capability}>
                  <button
                    type="button"
                    onClick={() => setOpenCapability(capability)}
                    className="flex w-full items-center gap-2.5 rounded-xl border border-(--color-border) bg-(--bg-surface) px-3 py-2.5 text-left transition-colors hover:border-(--color-accent)/50"
                  >
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-(--color-accent)/10 text-(--color-accent)">
                      <FileText size={14} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-mono text-xs font-medium text-(--color-text)">
                        {capability}
                      </span>
                      <span className="mt-0.5 block truncate font-mono text-[10px] text-(--color-text-subtle)">
                        specs/{capability}/spec.md
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : archived.length === 0 ? (
          <Empty
            icon={Archive}
            title="Nothing archived yet"
            body="Archiving folds a change's deltas into the capability specs and moves its folder under changes/archive/."
          />
        ) : (
          <ul className="flex flex-col gap-1.5">
            {archived.map((entry) => {
              const { date, slug } = splitArchiveEntry(entry)
              return (
                <li
                  key={entry}
                  className="flex items-center gap-2.5 rounded-xl border border-(--color-border) bg-(--bg-surface) px-3 py-2.5"
                >
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-(--color-success-subtle) text-(--color-success)">
                    <Archive size={13} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-xs font-medium text-(--color-text)">
                      {slug}
                    </span>
                    <span className={cn(
                      'mt-0.5 block truncate font-mono text-[10px] text-(--color-text-subtle)',
                    )}>
                      changes/archive/{entry}/
                    </span>
                  </span>
                  {date && (
                    <span className="shrink-0 text-[10px] text-(--color-text-subtle)">{date}</span>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
