/**
 * /settings/sandbox — user-editable deny-list of glob patterns the agent
 * cannot access (system-level files like ``.env``, ``db/``, etc).
 */
import { useMemo, useState } from 'react'
import { ChevronDown, Plus, Save, Shield, Trash2 } from 'lucide-react'

import {
  useSandboxSettingsQuery,
  useUpdateSandboxSettingsMutation,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { SettingsGroup, SettingsPage } from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SegmentedControl } from '@/components/ui/segmented-control'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export function SandboxSettingsPage() {
  const { data, isLoading, error, refetch } = useSandboxSettingsQuery()
  const updateMut = useUpdateSandboxSettingsMutation()
  const push = useToastStore((s) => s.push)

  // Local working copy of the deny-list. Rebases onto each fresh server
  // snapshot via the snapshot identity (no effect needed).
  const [draft, setDraft] = useState<{
    source: readonly string[]
    patterns: string[]
    sourceWorktreeLocation: 'repository' | 'user_data'
    worktreeLocation: 'repository' | 'user_data'
  }>({
    source: [],
    patterns: [],
    sourceWorktreeLocation: 'repository',
    worktreeLocation: 'repository',
  })

  const serverPatterns = data?.denied_patterns
  if (
    serverPatterns
    && (
      serverPatterns !== draft.source
      || data.worktree_location !== draft.sourceWorktreeLocation
    )
  ) {
    setDraft({
      source: serverPatterns,
      patterns: serverPatterns,
      sourceWorktreeLocation: data.worktree_location,
      worktreeLocation: data.worktree_location,
    })
  }
  const patterns = draft.patterns
  const setPatterns = (next: string[] | ((prev: string[]) => string[])) =>
    setDraft((d) => ({
      ...d,
      patterns: typeof next === 'function' ? next(d.patterns) : next,
    }))

  const dirty = useMemo(() => {
    const a = draft.source
    if (a.length !== patterns.length) return true
    if (a.some((p, i) => p !== patterns[i])) return true
    return draft.sourceWorktreeLocation !== draft.worktreeLocation
  }, [
    draft.source,
    draft.sourceWorktreeLocation,
    draft.worktreeLocation,
    patterns,
  ])

  const updateAt = (idx: number, value: string) =>
    setPatterns((prev) => prev.map((p, i) => (i === idx ? value : p)))

  const removeAt = (idx: number) =>
    setPatterns((prev) => prev.filter((_, i) => i !== idx))

  const addRow = () => setPatterns((prev) => [...prev, ''])

  const handleSave = async () => {
    const cleaned = patterns.map((p) => p.trim()).filter(Boolean)
    try {
      await updateMut.mutateAsync({
        denied_patterns: cleaned,
        worktree_location: draft.worktreeLocation,
      })
      setPatterns(cleaned)
      push({
        tone: 'success',
        title: 'Sandbox saved',
        description: `${cleaned.length} pattern${cleaned.length === 1 ? '' : 's'} active.`,
      })
    } catch (err) {
      push({
        tone: 'error',
        title: 'Save failed',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  return (
    <SettingsPage
      icon={Shield}
      title="Sandbox"
      lede={
        <>
          Agents can access only the active workspace, explicitly attached repositories,
          read-only roots, and session artifacts. Sensitive glob patterns are enforced
          inside those roots too. Use{' '}
          <code className="rounded bg-(--bg-key) px-1 py-0.5 font-mono text-xs">**</code> for any depth
          and <code className="rounded bg-(--bg-key) px-1 py-0.5 font-mono text-xs">*</code> for one
          segment. <SandboxHelpPopover />
        </>
      }
      actions={
        <div className="flex items-center gap-2">
          {dirty && (
            <span className="text-xs text-(--color-text-muted)" aria-live="polite">
              Unsaved
            </span>
          )}
          <Button
            size="sm"
            className="min-h-11 md:min-h-0"
            onClick={handleSave}
            disabled={!dirty || updateMut.isPending}
          >
            <Save size={12} aria-hidden="true" />
            {updateMut.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      }
    >
      <SettingsAsyncBoundary
        loading={isLoading}
        hasData={Boolean(data)}
        error={error}
        variant="detail"
        loadingLabel="Loading sandbox settings"
        errorTitle="Failed to load sandbox settings"
        onRetry={() => void refetch()}
      >
      {data && (
        <SettingsGroup
          title="Managed worktrees"
          description="Choose where EvoFlux creates isolated Git worktrees. Existing worktrees in either location remain recognized and removable."
        >
          <div className="space-y-3 px-3 py-3">
            <SegmentedControl
              options={[
                { value: 'repository', label: 'Inside repository' },
                { value: 'user_data', label: 'User data directory' },
              ]}
              value={draft.worktreeLocation}
              onChange={(worktreeLocation) =>
                setDraft((current) => ({ ...current, worktreeLocation }))
              }
              layoutId="sandbox-worktree-location"
              ariaLabel="Managed worktree location"
            />
            <p className="text-xs leading-relaxed text-(--color-text-muted)">
              {draft.worktreeLocation === 'repository' ? (
                <>
                  New worktrees are stored at{' '}
                  <code className="font-mono">&lt;repository&gt;/.evoflux/worktrees</code>.
                  EvoFlux adds this directory to the repository-local Git exclude file,
                  without modifying <code className="font-mono">.gitignore</code>.
                </>
              ) : (
                <>
                  New worktrees are stored under the EvoFlux data directory in your user
                  profile. This keeps repository folders smaller but makes worktrees less
                  discoverable beside their source.
                </>
              )}
            </p>
          </div>
        </SettingsGroup>
      )}

      {data && patterns.length === 0 && (
        <SettingsGroup title="Denied patterns" bare>
          <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-(--color-border) p-10 text-center">
            <p className="text-sm font-medium text-(--color-text)">Nothing is blocked yet</p>
            <p className="max-w-sm text-xs leading-relaxed text-(--color-text-muted)">
              Workspace allowlists remain active. Add a pattern to additionally block files like{' '}
              <code className="font-mono">.env</code> or folders like{' '}
              <code className="font-mono">secrets/</code>.
            </p>
            <Button size="sm" className="min-h-11 md:min-h-0" onClick={addRow}>
              <Plus size={12} aria-hidden="true" />
              Add pattern
            </Button>
          </div>
        </SettingsGroup>
      )}

      {data && patterns.length > 0 && (
        <SettingsGroup
          title="Denied patterns"
          description={`${patterns.length} ${patterns.length === 1 ? 'pattern is' : 'patterns are'} matched with logical OR. One match blocks access.`}
          actions={
            <Button size="sm" variant="outline" className="min-h-11 md:min-h-0" onClick={addRow}>
              <Plus size={12} aria-hidden="true" />
              Add
            </Button>
          }
        >
          <ul>
            {patterns.map((pattern, idx) => (
              <li
                key={idx}
                className="flex items-center gap-2 px-3 py-2 not-last:border-b not-last:border-(--color-border-subtle)"
              >
                <Input
                  value={pattern}
                  onChange={(e) => updateAt(idx, e.target.value)}
                  placeholder="**/.env"
                  aria-label={`Pattern ${idx + 1}`}
                  className="h-9 border-transparent bg-transparent font-mono text-sm focus-visible:border-(--color-border)"
                />
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        className="size-11 shrink-0 md:size-7"
                        onClick={() => removeAt(idx)}
                        aria-label={`Remove pattern ${idx + 1}`}
                      >
                        <Trash2 size={13} />
                      </Button>
                    }
                  />
                  <TooltipContent>Remove</TooltipContent>
                </Tooltip>
              </li>
            ))}
          </ul>
        </SettingsGroup>
      )}
      </SettingsAsyncBoundary>
    </SettingsPage>
  )
}

// ─── Help popover ──────────────────────────────────────────────────────────

interface PatternExample {
  pattern: string
  description: string
}

const EXAMPLES: readonly PatternExample[] = [
  { pattern: '**/.env', description: 'Any file named .env, at any depth' },
  { pattern: '**/.env.*', description: 'Variants like .env.local, .env.prod' },
  { pattern: 'secrets/**', description: 'Everything under a secrets/ folder' },
  { pattern: '**/*.pem', description: 'PEM keys anywhere in the tree' },
  { pattern: '**/id_rsa*', description: 'SSH private keys (and .pub if you wish)' },
  { pattern: 'db/**', description: 'Local database files in db/' },
]

/**
 * Inline help: glob primer + concrete examples. Read-only reference.
 * Triggered by a text-link "See examples" button at the end of the
 * helper paragraph. Controlled state so the chevron can flip while open.
 */
function SandboxHelpPopover() {
  const [open, setOpen] = useState(false)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            className="inline-flex min-h-11 items-center gap-0.5 rounded text-(--color-text) underline-offset-2 hover:underline focus-visible:ring-3 focus-visible:ring-(--focus-ring)/40 focus-visible:outline-none md:min-h-0"
          >
            See examples
            <ChevronDown
              size={12}
              aria-hidden="true"
              className={cn('transition-transform', open && 'rotate-180')}
            />
          </button>
        }
      />
      <PopoverContent className="w-[min(20rem,calc(100vw-1rem))] gap-3 p-3" align="start">
        <ul className="flex flex-col gap-1.5">
          {EXAMPLES.map((ex) => (
            <li key={ex.pattern} className="flex flex-col gap-0.5">
              <code className="self-start rounded bg-(--bg-key) px-1.5 py-0.5 font-mono text-xs text-(--color-text)">
                {ex.pattern}
              </code>
              <span className="text-xs leading-snug text-(--color-text-muted)">{ex.description}</span>
            </li>
          ))}
        </ul>

        <p className="border-t border-(--color-border) pt-2 text-xs leading-snug text-(--color-text-muted)">
          Built-in database, state and cache paths are always denied. Patterns also
          apply inside active workspaces.
        </p>
      </PopoverContent>
    </Popover>
  )
}
