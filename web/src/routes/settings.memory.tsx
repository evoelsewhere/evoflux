import {
  ArrowRight,
  BookOpenText,
  BrainCircuit,
  Database,
  FileStack,
  Inbox,
  Moon,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'

import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { DreamSettingsPanel } from '@/routes/settings.dream'
import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { Button } from '@/components/ui/button'
import { useWikiTreeQuery } from '@/queries'
import { useUIStore } from '@/stores/useUIStore'

function MemoryMetric({
  icon: Icon,
  label,
  value,
  tone = 'neutral',
}: {
  icon: LucideIcon
  label: string
  value: number
  tone?: 'accent' | 'neutral' | 'warning'
}) {
  const toneClass = {
    accent: 'bg-(--color-accent-soft) text-(--color-accent)',
    neutral: 'bg-(--bg-key) text-(--color-text-muted)',
    warning: 'bg-(--color-warning-subtle) text-(--color-warning)',
  }[tone]

  return (
    <div className="rounded-xl border border-(--color-border) bg-(--bg-card) p-4 shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
      <div className={`flex size-8 items-center justify-center rounded-lg ${toneClass}`}>
        <Icon size={15} aria-hidden="true" />
      </div>
      <p className="mt-4 font-mono text-2xl font-semibold tabular-nums tracking-[-0.04em] text-(--color-text)">
        {value}
      </p>
      <p className="mt-1 text-xs text-(--color-text-muted)">{label}</p>
    </div>
  )
}

export function MemorySettingsPage() {
  const treeQ = useWikiTreeQuery(true)
  const tree = treeQ.data

  const curatedCount = tree
    ? tree.wiki.length
      + tree.topics.length
      + tree.entities.length
      + tree.sources.length
      + tree.comparisons.length
    : 0
  const pendingCount = tree?.notes.length ?? 0

  const openMemory = () => {
    const ui = useUIStore.getState()
    ui.closeSettings()
    ui.openWorkbenchTool('wiki')
  }

  const focusDreamSettings = () => {
    document
      .getElementById('dream-settings')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <SettingsPage
      icon={BrainCircuit}
      title="Memory"
      size="wide"
      lede="Long-term knowledge that agents can recall across conversations. Raw material stays separate until Dream synthesizes it into curated pages."
      actions={
        <Button size="sm" onClick={openMemory}>
          <BookOpenText size={13} aria-hidden="true" />
          Open Memory
        </Button>
      }
    >
      <div>
        <SettingsAsyncBoundary
          loading={treeQ.isLoading}
          hasData={Boolean(tree)}
          error={treeQ.error}
          variant="cards"
          loadingLabel="Loading Memory overview"
          errorTitle="Failed to load Memory"
          onRetry={() => void treeQ.refetch()}
        >
          {tree && (
            <div className="space-y-7">
              <section
                aria-label="Memory overview"
                className="grid grid-cols-2 gap-3 lg:grid-cols-4"
              >
                <MemoryMetric
                  icon={Sparkles}
                  label="Curated pages"
                  value={curatedCount}
                  tone="accent"
                />
                <MemoryMetric
                  icon={Inbox}
                  label="Pending notes"
                  value={pendingCount}
                  tone={pendingCount > 0 ? 'warning' : 'neutral'}
                />
                <MemoryMetric
                  icon={FileStack}
                  label="Imported sources"
                  value={tree.imports.length}
                />
                <MemoryMetric
                  icon={Database}
                  label="System documents"
                  value={tree.system.length}
                />
              </section>

              <SettingsGroup
                title="How Memory works"
                description="A three-stage flow keeps raw evidence separate from durable knowledge."
              >
                <SettingsRow
                  label="1. Capture"
                  description="Conversations, agent notes and imported documents arrive in the Memory inbox without overwriting curated knowledge."
                  control={
                    <span className="rounded-full bg-(--bg-key) px-2.5 py-1 text-[11px] font-medium text-(--color-text-muted)">
                      {pendingCount} pending
                    </span>
                  }
                />
                <SettingsRow
                  label="2. Synthesize"
                  description="Dream reviews pending material, resolves repetition and writes structured pages with source references."
                  control={
                    <Button size="sm" variant="outline" onClick={focusDreamSettings}>
                      Configure Dream
                      <ArrowRight size={12} aria-hidden="true" />
                    </Button>
                  }
                />
                <SettingsRow
                  label="3. Recall"
                  description="Agents search the curated knowledge base during future work, while source and confidence metadata remain available for review."
                />
              </SettingsGroup>

              <SettingsCallout icon={Moon}>
                Curated pages are editable. Notes and imports remain read-only so the original
                evidence is preserved during synthesis.
              </SettingsCallout>
            </div>
          )}
        </SettingsAsyncBoundary>
      </div>

      <DreamSettingsPanel embedded />
    </SettingsPage>
  )
}
