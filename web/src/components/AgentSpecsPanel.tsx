import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Archive,
  ArrowRight,
  Bot,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FileText,
  FolderGit2,
  Layers,
  Loader2,
  PauseCircle,
  Play,
  Plus,
  Route,
  Search,
  Trash2,
  Wrench,
} from 'lucide-react'

import type {
  AsddApproveArtifact,
  AsddChange,
  AsddChangeDetail,
  AsddRepositorySetup,
  AsddRisk,
  AsddSetupResponse,
} from '@/api/types'
import {
  useApproveAsddArtifactMutation,
  useArchiveAsddChangeMutation,
  useAsddChangeQuery,
  useAsddChangesQuery,
  useAsddSetupQuery,
  useCreateAsddChangeMutation,
  useDeleteAsddChangeMutation,
  useInitializeAsddSetupMutation,
  useMarkAsddChangeReadyMutation,
  useSetAsddAutopilotMutation,
  useStartAsddActionMutation,
} from '@/queries'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { SelectControl } from '@/components/ui/select'
import { AsddActionRail } from '@/components/asdd/AsddActionRail'
import { AsddArtifactView } from '@/components/asdd/AsddArtifactView'
import { AsddCatalogueView } from '@/components/asdd/AsddCatalogueView'
import {
  RISK_HINTS,
  RISK_LABELS,
  designApplies,
  errorText,
  isAwaitingPerson,
  relativeTime,
  riskLabel,
  riskTone,
  statusLabel,
  statusTone,
} from '@/components/asdd/vocabulary'

/**
 * Matches `product` in `.evoflux/asdd/config.json`. The method is ASDD —
 * Agent Specification-Driven Development; the product surface is Agent Spec-Driven.
 */
const ASDD_DISPLAY_NAME = 'Agent Spec-Driven'

export interface AsddChatRequest {
  changeId: string
  skill: string
  prompt: string
  autoSend: boolean
}

interface AgentSpecsPanelProps {
  workspace: string
  projectId?: string | null
  active?: boolean
  onRunInChat?: (request: AsddChatRequest) => void
}

type ChangesView = 'board' | 'table' | 'list'

const VIEW_OPTIONS = [
  { value: 'board', label: 'Board' },
  { value: 'table', label: 'Table' },
  { value: 'list', label: 'List' },
] as const

/** Sentinel for "no repository filter" — the select speaks in strings. */
const ALL_REPOSITORIES = '__all__'

/** Board columns, each one phase of the cycle rather than one status. */
const BOARD_COLUMNS: { title: string; statuses: string[] }[] = [
  { title: 'Propose', statuses: ['drafting', 'proposed'] },
  { title: 'Specify', statuses: ['specifying', 'specified'] },
  { title: 'Plan', statuses: ['designing', 'designed', 'tasking', 'tasked'] },
  { title: 'Build', statuses: ['implementing', 'verifying'] },
  { title: 'Ready', statuses: ['ready'] },
]

const APPROVAL_LABELS: Record<AsddApproveArtifact, string> = {
  proposal: 'Proposal',
  specs: 'Specs',
  design: 'Design',
  tasks: 'Tasks',
}

const APPROVE_ACTIONS: Record<string, AsddApproveArtifact> = {
  approve_proposal: 'proposal',
  approve_specs: 'specs',
  approve_design: 'design',
  approve_tasks: 'tasks',
}

/** From the planning phase on, a change has a task list to show even if empty. */
const PLANNED_ONWARD: ReadonlySet<string> = new Set<string>([
  'tasking',
  'tasked',
  'implementing',
  'verifying',
  'ready',
  'archived',
])

/** From implementation on, evidence is something the reader is waiting to see. */
const BUILDING_ONWARD: ReadonlySet<string> = new Set<string>([
  'implementing',
  'verifying',
  'ready',
  'archived',
])

function loadView(): ChangesView {
  try {
    const stored = localStorage.getItem(STORAGE_KEYS.asdd.changesView)
    if (stored === 'board' || stored === 'table' || stored === 'list') return stored
  } catch {
    // A blocked storage API is a preference we cannot remember, not a failure.
  }
  return 'board'
}

// ── Setup ────────────────────────────────────────────────────────────────

function repositoryLabel(repository: AsddRepositorySetup): string {
  return repository.display_name || repository.name || repository.path
}

const REPO_STATUS_LABELS: Record<AsddRepositorySetup['status'], string> = {
  ready: 'Ready',
  invalid: 'Needs repair',
  upgrade_required: 'Upgrade available',
  not_initialized: 'Not initialized',
}

const ACTION_LABELS: Record<AsddRepositorySetup['status'], string> = {
  ready: 'Reinstall',
  invalid: 'Repair',
  upgrade_required: 'Upgrade',
  not_initialized: 'Install',
}

function statusSkin(status: AsddRepositorySetup['status']): string {
  if (status === 'ready') return 'bg-(--color-success-subtle) text-(--color-success)'
  if (status === 'invalid') return 'bg-(--color-error-subtle) text-(--color-error)'
  if (status === 'upgrade_required') return 'bg-(--color-accent)/12 text-(--color-accent)'
  return 'bg-(--bg-key) text-(--color-text-muted)'
}

function SetupView({
  workspace,
  projectId,
  setup,
}: {
  workspace: string
  projectId?: string | null
  setup: AsddSetupResponse
}) {
  const mutation = useInitializeAsddSetupMutation(workspace, projectId)
  const repositories = setup.repositories
  const remaining = repositories.filter((repository) => !repository.installed)
  const skillNames = repositories[0]?.skill_names ?? []
  const pendingPaths = mutation.variables?.repositoryPaths ?? []
  const [dataDirectory, setDataDirectory] = useState(
    remaining[0]?.data_directory ?? repositories[0]?.data_directory ?? 'documents/asdd',
  )
  const progress = setup.repository_count === 0
    ? 0
    : Math.round((setup.installed_count / setup.repository_count) * 100)

  const install = async (targets: AsddRepositorySetup[]) => {
    // Repair is isolated on purpose: one invalid repository must never make the
    // bulk action overwrite hand-edited Skills in an upgradeable sibling.
    const safe = targets.filter((repository) => repository.status !== 'invalid')
    const repairs = targets.filter((repository) => repository.status === 'invalid')
    if (safe.length > 0) {
      await mutation.mutateAsync({
        repositoryPaths: safe.map((repository) => repository.path),
        dataDirectory: dataDirectory.trim(),
        overwrite: false,
      })
    }
    if (repairs.length > 0) {
      await mutation.mutateAsync({
        repositoryPaths: repairs.map((repository) => repository.path),
        dataDirectory: dataDirectory.trim(),
        overwrite: true,
      })
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-3 @xl/asdd:p-5">
      <div className="flex items-center gap-2 px-1 text-[10px]" aria-label="Setup progress">
        <span className="flex items-center gap-1.5 font-medium text-(--color-accent)">
          <span className="flex size-5 items-center justify-center rounded-full bg-(--color-accent) text-[9px] font-semibold text-(--color-text-on-accent)">1</span>
          Set up repositories
        </span>
        <span className="h-px min-w-4 flex-1 bg-(--color-border)" />
        <span className="flex items-center gap-1.5 text-(--color-text-subtle)">
          <span className="flex size-5 items-center justify-center rounded-full border border-(--color-border) bg-(--bg-card) text-[9px] font-semibold">2</span>
          Create a change
        </span>
      </div>

      <section className="overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card)">
        <div className="border-b border-(--color-border) bg-gradient-to-br from-(--color-accent)/14 via-(--bg-card) to-(--bg-card) p-4 @xl/asdd:p-5">
          <div className="flex items-start gap-4">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-(--color-accent) text-(--color-text-on-accent) shadow-sm">
              <Route size={21} aria-hidden />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-(--color-accent)/12 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-(--color-accent)">ASDD</span>
                <span className="text-[10px] font-medium uppercase tracking-[0.16em] text-(--color-text-subtle)">One-time setup</span>
              </div>
              <h2 className="mt-2 text-base font-semibold leading-5 text-(--color-text)">
                Set up {ASDD_DISPLAY_NAME}
              </h2>
              <p className="mt-1.5 max-w-xl text-xs leading-5 text-(--color-text-muted)">
                Add a version-controlled spec catalogue and six Coding-only phase Skills to
                every repository. Everything setup writes is tracked, so a collaborator who
                clones the repository gets the method without running anything.
              </p>
            </div>
          </div>
          <div className="mt-5 flex items-center gap-3">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-(--bg-key)">
              <div
                className="h-full rounded-full bg-(--color-accent) transition-[width]"
                style={{ width: `${progress}%` }}
              />
            </div>
            <span className="shrink-0 text-xs font-medium text-(--color-text-2)">
              {setup.installed_count}/{setup.repository_count} ready
            </span>
          </div>
        </div>

        <div className="divide-y divide-(--color-border)">
          {remaining.length > 0 && (
            <div className="px-4 py-4 @xl/asdd:px-5">
              <label className="block text-xs font-medium text-(--color-text-2)">
                Spec catalogue folder
                <input
                  value={dataDirectory}
                  onChange={(event) => setDataDirectory(event.target.value)}
                  className="mt-1.5 h-10 w-full rounded-lg border border-(--color-border) bg-(--bg-page) px-3 font-mono text-xs text-(--color-text) outline-none focus:border-(--color-accent) focus:ring-2 focus:ring-(--color-accent)/10"
                  placeholder="documents/asdd"
                  spellCheck={false}
                />
              </label>
              <p className="mt-1.5 text-[10px] leading-4 text-(--color-text-subtle)">
                Repository-relative and version-controlled. It holds `project.md`, one
                `spec.md` per capability, and one folder per open change. Setup never moves
                or copies documentation the repository already owns.
              </p>
            </div>
          )}

          {repositories.map((repository) => {
            const busy = mutation.isPending && pendingPaths.includes(repository.path)
            return (
              <div
                key={repository.path}
                className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-2 px-4 py-3.5 @sm/asdd:grid-cols-[auto_minmax(0,1fr)_auto] @xl/asdd:px-5"
              >
                <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-xl', statusSkin(repository.status))}>
                  {repository.installed
                    ? <CheckCircle2 size={17} />
                    : repository.status === 'invalid' || repository.status === 'upgrade_required'
                      ? <Wrench size={16} />
                      : <FolderGit2 size={16} />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-medium text-(--color-text)">
                      {repositoryLabel(repository)}
                    </p>
                    <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-medium', statusSkin(repository.status))}>
                      {REPO_STATUS_LABELS[repository.status]}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate font-mono text-[10px] text-(--color-text-subtle)" title={repository.path}>
                    {repository.path}
                  </p>
                  <p className="mt-1 text-[10px] text-(--color-text-subtle)">
                    {repository.skill_names.length}{' '}
                    {repository.installed ? 'Coding skills' : 'required Coding skills'} ·{' '}
                    {repository.skills_path}
                  </p>
                  <p className="mt-0.5 truncate font-mono text-[10px] text-(--color-text-subtle)">
                    catalogue · {repository.data_directory}
                  </p>
                  {repository.missing_skills.length > 0 && (
                    <p className="mt-1 text-[10px] font-medium text-(--color-warning)">
                      Missing Skills: {repository.missing_skills.join(', ')}
                    </p>
                  )}
                  {repository.missing_catalogue_files.length > 0 && (
                    <p className="mt-1 text-[10px] font-medium text-(--color-warning)">
                      Missing catalogue files: {repository.missing_catalogue_files.join(', ')}
                    </p>
                  )}
                  {repository.issue && (
                    <p className={cn(
                      'mt-1 flex items-start gap-1 text-[11px] leading-4',
                      repository.status === 'invalid' ? 'text-(--color-error)' : 'text-(--color-text-muted)',
                    )}>
                      <AlertTriangle size={11} className="mt-0.5 shrink-0" />
                      {repository.issue}
                    </p>
                  )}
                </div>
                {!repository.installed && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="col-start-2 justify-self-start @sm/asdd:col-start-3 @sm/asdd:row-start-1"
                    disabled={mutation.isPending}
                    onClick={() => void install([repository])}
                  >
                    {busy && <Loader2 className="animate-spin" />}
                    {ACTION_LABELS[repository.status]}
                  </Button>
                )}
              </div>
            )
          })}
        </div>

        <footer className="flex flex-col gap-3 border-t border-(--color-border) bg-(--bg-page)/50 p-4 @2xl/asdd:flex-row @2xl/asdd:items-center @2xl/asdd:justify-between @xl/asdd:px-5">
          <div className="min-w-0">
            <p className="text-xs font-medium text-(--color-text-2)">Files added to each repository</p>
            <p className="mt-0.5 break-all font-mono text-[10px] text-(--color-text-subtle)">
              .evoflux/asdd/config.json · .evoflux/asdd/RULES.md ·{' '}
              {dataDirectory || 'documents/asdd'}/ · .evoflux/skills/asdd-*/
            </p>
            <p className="mt-1 text-[10px] text-(--color-text-subtle)">
              All of it is tracked. A change is a folder of Markdown you review with
              `git diff` — there is no database copy to reconcile.
            </p>
            <div className="mt-2 flex flex-wrap gap-1" aria-label="ASDD skill bundle">
              {skillNames.map((name) => (
                <span
                  key={name}
                  className="rounded-md border border-(--color-border) bg-(--bg-card) px-1.5 py-0.5 font-mono text-[9px] text-(--color-text-muted)"
                >
                  {name}
                </span>
              ))}
            </div>
          </div>
          {remaining.length > 0 && (
            <Button
              type="button"
              className="shrink-0"
              disabled={mutation.isPending}
              onClick={() => void install(remaining)}
            >
              {mutation.isPending && <Loader2 className="animate-spin" />}
              Set up {remaining.length === 1 ? 'repository' : `${remaining.length} repositories`}
              <ArrowRight />
            </Button>
          )}
        </footer>
      </section>

      {mutation.error && (
        <p role="alert" className="text-center text-xs text-(--color-error)">
          {errorText(mutation.error)}
        </p>
      )}
    </div>
  )
}

// ── New change ───────────────────────────────────────────────────────────

/**
 * The slug the server will derive from a title, shown before it commits to it.
 *
 * Mirrors `slugify` in `app/services/asdd_store.py`. A preview that disagreed
 * with the server would be worse than none, so it uses the same rule: fold the
 * accents, keep letters and digits, join the rest with hyphens. Vietnamese `đ`
 * is a letter rather than an accented `d`, so decomposition alone drops it.
 */
function previewSlug(title: string): string {
  return title
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
    .replace(/-+$/, '')
}

function NewChangeForm({
  workspace,
  projectId,
  repositories,
  onCreated,
  onCancel,
}: {
  workspace: string
  projectId?: string | null
  repositories: AsddRepositorySetup[]
  onCreated: (changeId: string, workspace: string) => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState('')
  const [problem, setProblem] = useState('')
  const [outcome, setOutcome] = useState('')
  // Everything the propose phase derives. Hidden until someone wants to
  // override it: asking a reader to tier a change before it has been read is
  // asking them to guess at whether it owes a design.
  const [advanced, setAdvanced] = useState(false)
  const [risk, setRisk] = useState<AsddRisk | ''>('')
  const [capabilities, setCapabilities] = useState('')
  const [changeId, setChangeId] = useState('')
  // A project can hold several repositories, and the panel only reaches this
  // form once every one of them is installed, so all of them are valid
  // targets. Defaults to whichever repository the panel is currently showing,
  // but a Coding Project lets the author redirect it.
  const [targetWorkspace, setTargetWorkspace] = useState(workspace)
  const create = useCreateAsddChangeMutation(targetWorkspace, projectId)
  const failure = errorText(create.error)

  const derived = previewSlug(title)
  const slug = changeId.trim() || derived
  // A title written in a script with no Latin form leaves nothing to derive
  // from, and the only way through is an id the author chooses.
  const needsId = title.trim().length > 0 && derived.length === 0

  const submit = () => {
    if (!title.trim() || !slug || create.isPending) return
    create.mutate(
      {
        title: title.trim(),
        problem: problem.trim(),
        outcome: outcome.trim(),
        // Each sent only when the author overrode it, so the server and the
        // propose phase stay the ones that decide.
        changeId: changeId.trim() || undefined,
        risk: risk || undefined,
        capabilities: capabilities
          .split(/[\s,]+/)
          .map((item) => item.trim())
          .filter(Boolean),
      },
      { onSuccess: (detail) => onCreated(detail.change.change_id, targetWorkspace) },
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 p-4">
      <div>
        <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-(--color-accent)">
          New change
        </p>
        <h2 className="mt-1 text-sm font-semibold text-(--color-text)">
          Say what you want; an agent drafts the proposal next
        </h2>
        <p className="mt-1 text-[11px] leading-4 text-(--color-text-muted)">
          The propose phase reads what you write here, then derives the slug, the
          capabilities and the risk tier. Nothing below is a decision you have to
          make now.
        </p>
      </div>

      {repositories.length > 1 && (
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-(--color-text-subtle)">
            Repository
          </span>
          <SelectControl
            value={targetWorkspace}
            ariaLabel="Target repository"
            onValueChange={setTargetWorkspace}
            options={repositories.map((repository) => ({
              value: repository.path,
              label: repositoryLabel(repository),
            }))}
          />
          <span className="text-[10px] leading-4 text-(--color-text-subtle)">
            This Coding Project has {repositories.length} repositories set up for
            Agent Spec-Driven. A change may edit any of them; the change folder itself
            is written to whichever one you pick here.
          </span>
        </label>
      )}

      <label className="flex flex-col gap-1">
        <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-(--color-text-subtle)">
          Title
        </span>
        <input
          autoFocus
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') submit()
          }}
          placeholder="Add user authentication"
          className="rounded-lg border border-(--color-border) bg-(--bg-surface) px-2.5 py-1.5 text-xs text-(--color-text) outline-none focus:border-(--color-accent)"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-(--color-text-subtle)">
          What is the problem?
        </span>
        <textarea
          value={problem}
          onChange={(event) => setProblem(event.target.value)}
          rows={3}
          placeholder="Readers can only share notes by copying the text out by hand."
          className="resize-y rounded-lg border border-(--color-border) bg-(--bg-surface) px-2.5 py-1.5 text-xs leading-5 text-(--color-text) outline-none focus:border-(--color-accent)"
        />
        <span className="text-[10px] leading-4 text-(--color-text-subtle)">
          Who cannot do what today, and what it costs them. This becomes the
          proposal's <code className="font-mono">## Why</code>.
        </span>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-(--color-text-subtle)">
          What should be true when it is done?
        </span>
        <textarea
          value={outcome}
          onChange={(event) => setOutcome(event.target.value)}
          rows={3}
          placeholder="One command writes every note into a PDF they can send."
          className="resize-y rounded-lg border border-(--color-border) bg-(--bg-surface) px-2.5 py-1.5 text-xs leading-5 text-(--color-text) outline-none focus:border-(--color-accent)"
        />
        <span className="text-[10px] leading-4 text-(--color-text-subtle)">
          The outcome, not the implementation. This becomes the proposal's{' '}
          <code className="font-mono">## What Changes</code>.
        </span>
      </label>

      <button
        type="button"
        onClick={() => setAdvanced((open) => !open)}
        aria-expanded={advanced}
        className="flex items-center gap-1.5 self-start text-[10px] font-medium text-(--color-text-muted) transition-colors hover:text-(--color-text)"
      >
        <ChevronRight
          size={11}
          className={cn('transition-transform', advanced && 'rotate-90')}
        />
        {advanced ? 'Hide' : 'Set'} the id, capabilities and risk tier yourself
      </button>

      {advanced && (
        <div className="flex flex-col gap-4 rounded-xl border border-(--color-border) bg-(--bg-surface)/50 p-3">
          <p className="text-[10px] leading-4 text-(--color-text-subtle)">
            Leave any of these blank and the propose phase decides it. The risk
            tier in particular is a judgment about whether the change owes a
            design and an independent review — the proposal gate refuses until
            something has set it.
          </p>

      <label className="flex flex-col gap-1">
        <span className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-[0.12em] text-(--color-text-subtle)">
          Change id
          {!needsId && !changeId.trim() && <span className="normal-case tracking-normal">derived from the title</span>}
        </span>
        <input
          value={changeId}
          onChange={(event) => setChangeId(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') submit()
          }}
          placeholder={derived || 'add-user-authentication'}
          className={cn(
            'rounded-lg border bg-(--bg-surface) px-2.5 py-1.5 font-mono text-xs text-(--color-text) outline-none focus:border-(--color-accent)',
            needsId ? 'border-(--color-warning)' : 'border-(--color-border)',
          )}
          spellCheck={false}
        />
        <span className="text-[10px] leading-4 text-(--color-text-subtle)">
          {needsId
            ? 'This title has no letters or digits to build an id from. Give the change an id of its own.'
            : <>The folder will be <code className="font-mono text-(--color-text-2)">changes/{slug || '…'}/</code>. Leave it blank to use the title.</>}
        </span>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-(--color-text-subtle)">
          Capabilities the change touches
        </span>
        <input
          value={capabilities}
          onChange={(event) => setCapabilities(event.target.value)}
          placeholder="user-auth session-binding"
          className="rounded-lg border border-(--color-border) bg-(--bg-surface) px-2.5 py-1.5 font-mono text-xs text-(--color-text) outline-none focus:border-(--color-accent)"
        />
        <span className="text-[10px] leading-4 text-(--color-text-subtle)">
          Optional — the proposal phase will confirm or correct these. Reuse an existing
          capability whenever the change alters behavior it already contracts.
        </span>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-(--color-text-subtle)">
          Risk tier
        </span>
        <SelectControl
          value={risk}
          ariaLabel="Risk tier"
          onValueChange={(value) => setRisk(value as AsddRisk | '')}
          options={[
            { value: '', label: 'Let the propose phase decide' },
            ...(Object.keys(RISK_LABELS) as AsddRisk[]).map((value) => ({
              value,
              label: RISK_LABELS[value],
            })),
          ]}
        />
        <span className="text-[10px] leading-4 text-(--color-text-subtle)">
          {risk ? RISK_HINTS[risk] : 'Not set — the propose phase will choose one.'}
        </span>
          </label>
        </div>
      )}

      {failure && (
        <p role="alert" className="text-[11px] text-(--color-danger)">
          {failure}
        </p>
      )}

      <div className="flex items-center justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="button" size="sm" disabled={!title.trim() || !slug || create.isPending} onClick={submit}>
          {create.isPending ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
          Create change
        </Button>
      </div>
    </div>
  )
}

// ── Overview ─────────────────────────────────────────────────────────────

function RepositoryBadge({ name }: { name: string }) {
  return (
    <span
      title={name}
      className="flex min-w-0 items-center gap-1 rounded-full bg-(--bg-key)/70 px-1.5 py-0.5 text-[10px] font-medium text-(--color-text-2)"
    >
      <FolderGit2 size={9} className="shrink-0" />
      <span className="truncate">{name}</span>
    </span>
  )
}

function ChangeCard({
  change,
  repository,
  onOpen,
}: {
  change: AsddChange
  /** Set only when the scope holds more than one repository. */
  repository?: string
  onOpen: () => void
}) {
  const waiting = isAwaitingPerson(change.status)
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        'w-full rounded-xl border bg-(--bg-surface) px-3 py-2.5 text-left transition-colors hover:border-(--color-accent)/50',
        // A change nobody can move without a person is the only thing on this
        // board that needs the reader now, so it is the only thing that is
        // allowed to draw the eye.
        waiting ? 'border-(--color-accent)/40' : 'border-(--color-border)',
      )}
    >
      <div className="flex items-center gap-2">
        <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-medium', statusTone(change.status))}>
          {statusLabel(change.status)}
        </span>
        {change.hold ? (
          <span
            title={change.hold.reason ?? undefined}
            className="flex items-center gap-1 rounded-full bg-(--color-accent)/12 px-1.5 py-0.5 text-[10px] font-medium text-(--color-accent)"
          >
            <PauseCircle size={9} /> Held
          </span>
        ) : change.autopilot ? (
          <span
            title="Autopilot is carrying this change through its gates"
            className="flex items-center gap-1 rounded-full bg-(--bg-key)/70 px-1.5 py-0.5 text-[10px] font-medium text-(--color-text-2)"
          >
            <Bot size={9} /> Auto
          </span>
        ) : null}
        <span className={cn('ml-auto text-[10px] font-medium', riskTone(change.risk))}>
          {riskLabel(change.risk)}
        </span>
      </div>
      <h3 className="mt-2 line-clamp-2 text-sm font-semibold leading-5 text-(--color-text)">
        {change.title}
      </h3>
      <div className="mt-1 flex min-w-0 items-center gap-2">
        <p className="min-w-0 flex-1 truncate font-mono text-[10px] text-(--color-text-subtle)">
          {change.change_id}
        </p>
        {repository ? <RepositoryBadge name={repository} /> : null}
      </div>
      {change.tasks_total > 0 && (
        <div className="mt-2 flex items-center gap-2">
          <div className="h-1 flex-1 overflow-hidden rounded-full bg-(--bg-key)">
            <div
              className="h-full rounded-full bg-(--color-accent) transition-[width]"
              style={{ width: `${Math.round((change.tasks_done / change.tasks_total) * 100)}%` }}
            />
          </div>
          <span className="shrink-0 text-[10px] tabular-nums text-(--color-text-muted)">
            {change.tasks_done}/{change.tasks_total}
          </span>
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-(--color-text-muted)">
        {change.capabilities.length > 0 && (
          <span className="truncate font-mono">{change.capabilities.join(', ')}</span>
        )}
        {change.evidence_count > 0 && <span>{change.evidence_count} evidence</span>}
        <span className="ml-auto">{relativeTime(change.created)}</span>
      </div>
    </button>
  )
}

function ChangesOverview({
  changes,
  archived,
  capabilities,
  repositories,
  repositoryFilter,
  onRepositoryFilterChange,
  pendingSetup,
  onOpenSetup,
  view,
  onViewChange,
  onOpen,
  onNew,
  onOpenCatalogue,
  query,
  onQueryChange,
}: {
  changes: AsddChange[]
  archived: string[]
  capabilities: string[]
  repositories: AsddRepositorySetup[]
  repositoryFilter: string | null
  onRepositoryFilterChange: (value: string | null) => void
  pendingSetup: number
  onOpenSetup: () => void
  view: ChangesView
  onViewChange: (value: ChangesView) => void
  onOpen: (change: AsddChange) => void
  onNew: () => void
  onOpenCatalogue: () => void
  query: string
  onQueryChange: (value: string) => void
}) {
  // Only worth showing when there is a choice to make. A single-repository
  // project is the common case and a select with one option in it is furniture.
  const multiRepo = repositories.length > 1
  const repositoryNames = useMemo(() => {
    const names = new Map<string, string>()
    for (const repository of repositories) {
      names.set(repository.path, repositoryLabel(repository))
    }
    return names
  }, [repositories])
  const repositoryName = useCallback(
    (path: string) => repositoryNames.get(path) ?? path.split(/[\\/]/).filter(Boolean).pop() ?? path,
    [repositoryNames],
  )

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const inScope = repositoryFilter
      ? changes.filter((change) => change.repository === repositoryFilter)
      : changes
    if (!needle) return inScope
    return inScope.filter(
      (change) =>
        change.title.toLowerCase().includes(needle)
        || change.change_id.includes(needle)
        || change.capabilities.some((item) => item.includes(needle)),
    )
  }, [changes, query, repositoryFilter])

  const waiting = changes.filter((change) => isAwaitingPerson(change.status)).length

  // `status` is hand-editable, so a change can carry one no column claims.
  // Without somewhere to put it the board simply dropped it — present in the
  // table and the list, absent here, with nothing saying why.
  const boardColumns = useMemo(() => {
    const known = new Set(BOARD_COLUMNS.flatMap((column) => column.statuses))
    const stray = filtered.filter((change) => !known.has(change.status))
    if (stray.length === 0) return BOARD_COLUMNS
    return [
      ...BOARD_COLUMNS,
      { title: 'Unrecognised', statuses: stray.map((change) => change.status) },
    ]
  }, [filtered])

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/*
        One wrapping row, not two that reflow. Every item is `shrink-0` and the
        search group is `w-full` until there is room for it, so the row breaks
        cleanly between groups instead of compressing whichever element happens
        to be flexible — which is what turned "1 waiting on you" into a
        four-line column squeezed beside the filter.
      */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-2 border-b border-(--color-border) px-3 py-2.5">
        <h2 className="shrink-0 text-sm font-semibold text-(--color-text)">Changes</h2>
        {waiting > 0 ? (
          <span className="shrink-0 whitespace-nowrap rounded-full bg-(--color-accent)/12 px-2 py-0.5 text-[10px] font-medium text-(--color-accent)">
            {waiting} waiting
          </span>
        ) : (
          <span className="shrink-0 whitespace-nowrap text-[10px] text-(--color-text-subtle)">
            {changes.length} open
          </span>
        )}

        <div className="order-2 ml-auto flex shrink-0 items-center gap-2 @2xl/asdd:order-3 @2xl/asdd:ml-0">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={onOpenCatalogue}
            title="Read the capability specs and the archive"
          >
            <Layers size={13} />
            <span className="whitespace-nowrap">
              {capabilities.length} · {archived.length}
            </span>
          </Button>
          <Button type="button" size="sm" onClick={onNew}>
            <Plus size={13} />
            <span className="whitespace-nowrap">New</span>
            <span className="hidden whitespace-nowrap @xl/asdd:inline">change</span>
          </Button>
        </div>

        <div className="order-3 flex w-full items-center gap-2 @2xl/asdd:order-2 @2xl/asdd:ml-auto @2xl/asdd:w-auto">
          {multiRepo ? (
            <SelectControl
              size="sm"
              value={repositoryFilter ?? ALL_REPOSITORIES}
              onValueChange={(value) =>
                onRepositoryFilterChange(value === ALL_REPOSITORIES ? null : value)
              }
              ariaLabel="Filter by repository"
              className="w-32 shrink-0"
              options={[
                { value: ALL_REPOSITORIES, label: 'All repositories' },
                ...repositories.map((repository) => ({
                  value: repository.path,
                  label: repositoryLabel(repository),
                })),
              ]}
            />
          ) : null}
          <div className="relative min-w-0 flex-1 @2xl/asdd:w-32 @2xl/asdd:flex-none">
            <Search
              size={12}
              className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-(--color-text-subtle)"
            />
            <input
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="Filter"
              className="w-full rounded-lg border border-(--color-border) bg-(--bg-surface) py-1 pl-6 pr-2 text-[11px] text-(--color-text) outline-none focus:border-(--color-accent)"
            />
          </div>
          <SegmentedControl
            value={view}
            onChange={onViewChange}
            layoutId="asdd-changes-view"
            ariaLabel="Change list layout"
            options={VIEW_OPTIONS}
          />
        </div>
      </div>

      {/*
        A repository still to set up is a banner, not a wall: the changes the
        other repositories already hold are real work, and hiding them behind
        this was how a project reported an empty board.
      */}
      {pendingSetup > 0 ? (
        <button
          type="button"
          onClick={onOpenSetup}
          className="flex w-full items-center gap-2 border-b border-(--color-border) bg-(--color-warning)/8 px-3 py-2 text-left text-[11px] text-(--color-text-muted) hover:bg-(--color-warning)/12"
        >
          <AlertTriangle size={13} className="shrink-0 text-(--color-warning)" />
          <span className="min-w-0 flex-1">
            {pendingSetup} {pendingSetup === 1 ? 'repository' : 'repositories'} in this project
            {' '}have no ASDD directory yet — changes filed there will not appear here.
          </span>
          <span className="shrink-0 font-medium text-(--color-accent)">Set up</span>
        </button>
      ) : null}

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {filtered.length === 0 ? (
          <div className="mx-auto mt-10 max-w-sm text-center">
            <FileText size={20} className="mx-auto text-(--color-text-subtle)" />
            <h3 className="mt-3 text-sm font-semibold text-(--color-text)">
              {changes.length === 0 ? 'No open changes' : 'Nothing matches that filter'}
            </h3>
            <p className="mt-1 text-[11px] leading-4 text-(--color-text-muted)">
              {changes.length === 0
                ? 'A change is a folder of Markdown in the repository. Start one and an agent drafts its proposal.'
                : 'Clear the filter to see every open change.'}
            </p>
          </div>
        ) : view === 'board' ? (
          <div className="grid grid-cols-1 gap-3 @2xl/asdd:grid-cols-3 @5xl/asdd:grid-cols-5">
            {boardColumns.map((column) => {
              const items = filtered.filter((change) => column.statuses.includes(change.status))
              return (
                <div
                  key={column.title}
                  className={cn(
                    'min-w-0',
                    // Stacked, an empty column is a heading over nothing — three
                    // of those between two cards read as noise. Side by side the
                    // gap is the information, so keep it.
                    items.length === 0 && 'hidden @2xl/asdd:block',
                  )}
                >
                  <div className="flex items-center justify-between px-1 pb-2">
                    <h3 className="text-xs font-semibold text-(--color-text)">{column.title}</h3>
                    <span className="text-[10px] text-(--color-text-subtle)">{items.length}</span>
                  </div>
                  <div className="flex flex-col gap-2">
                    {items.map((change) => (
                      <ChangeCard
                        key={change.change_id}
                        change={change}
                        repository={multiRepo ? repositoryName(change.repository) : undefined}
                        onOpen={() => onOpen(change)}
                      />
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        ) : view === 'table' ? (
          // Capabilities and Tasks are hidden rather than scrolled below `@xl`.
          // Five columns in a docked panel pushed Tasks off the right edge, so
          // the table had a horizontal scrollbar and the column a reader most
          // wanted was the one they could not see.
          <table className="w-full table-fixed text-left text-[11px]">
            <thead className="text-[10px] uppercase tracking-[0.1em] text-(--color-text-subtle)">
              <tr>
                <th className="px-2 py-1.5 font-medium">Change</th>
                <th className="w-24 px-2 py-1.5 font-medium">Status</th>
                <th className="w-16 px-2 py-1.5 font-medium">Risk</th>
                <th className="hidden w-40 px-2 py-1.5 font-medium @xl/asdd:table-cell">
                  Capabilities
                </th>
                <th className="hidden w-14 px-2 py-1.5 font-medium @xl/asdd:table-cell">
                  Tasks
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((change) => (
                <tr
                  key={change.change_id}
                  onClick={() => onOpen(change)}
                  className="cursor-pointer border-t border-(--color-border) align-top hover:bg-(--bg-key)/40"
                >
                  <td className="px-2 py-1.5">
                    <span className="block truncate font-medium text-(--color-text)">
                      {change.title}
                    </span>
                    <span className="block truncate font-mono text-[10px] text-(--color-text-subtle)">
                      {change.change_id}
                      {multiRepo ? ` · ${repositoryName(change.repository)}` : ''}
                    </span>
                  </td>
                  <td className="px-2 py-1.5">
                    <span className={cn(
                      'inline-block rounded-full px-1.5 py-0.5 text-[10px] font-medium',
                      statusTone(change.status),
                    )}>
                      {statusLabel(change.status)}
                    </span>
                  </td>
                  <td className={cn('px-2 py-1.5', riskTone(change.risk))}>
                    {riskLabel(change.risk)}
                  </td>
                  <td className="hidden truncate px-2 py-1.5 font-mono text-[10px] text-(--color-text-muted) @xl/asdd:table-cell">
                    {change.capabilities.join(', ') || '—'}
                  </td>
                  <td className="hidden px-2 py-1.5 tabular-nums text-(--color-text-muted) @xl/asdd:table-cell">
                    {change.tasks_total > 0 ? `${change.tasks_done}/${change.tasks_total}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="flex flex-col gap-2">
            {filtered.map((change) => (
              <ChangeCard
                key={change.change_id}
                change={change}
                repository={multiRepo ? repositoryName(change.repository) : undefined}
                onOpen={() => onOpen(change)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Detail ───────────────────────────────────────────────────────────────

/**
 * The approval gates, and who cleared each one.
 *
 * A gate autopilot passed is drawn differently from one a person signed. They
 * both let the change move, but only one is a signature, and a reader deciding
 * whether to archive needs to be able to tell at a glance which is which.
 */
function ApprovalStrip({ detail }: { detail: AsddChangeDetail }) {
  const required = detail.rail.required_approvals as AsddApproveArtifact[]
  const reserved = new Set(detail.rail.human_only_gates)
  return (
    <ul className="flex flex-wrap items-center gap-1.5">
      {required.map((artifact) => {
        const signed = detail.change.approvals[artifact]
        const auto = detail.change.auto_approvals?.[artifact]
        const title = signed
          ? `Approved by you ${relativeTime(signed)}`
          : auto
            ? `Cleared by autopilot ${relativeTime(auto)}`
            : reserved.has(artifact)
              ? 'Not approved yet — this tier needs you, not autopilot'
              : 'Not approved yet'
        return (
          <li
            key={artifact}
            title={title}
            className={cn(
              'flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium',
              signed && 'border-(--color-success)/40 bg-(--color-success-subtle) text-(--color-success)',
              !signed && auto && 'border-(--color-accent)/40 bg-(--color-accent)/10 text-(--color-accent)',
              !signed && !auto && 'border-(--color-border) text-(--color-text-subtle)',
            )}
          >
            {signed ? <Check size={9} /> : auto ? <Bot size={9} /> : null}
            {APPROVAL_LABELS[artifact]}
          </li>
        )
      })}
    </ul>
  )
}

function ChangeDetail({
  workspace,
  projectId,
  detail,
  onBack,
  onRunInChat,
  onDeleted,
  onArchived,
}: {
  workspace: string
  projectId?: string | null
  detail: AsddChangeDetail
  onBack: () => void
  onRunInChat?: (request: AsddChatRequest) => void
  onDeleted: () => void
  onArchived: () => void
}) {
  const changeId = detail.change.change_id
  const approve = useApproveAsddArtifactMutation(workspace, changeId, projectId)
  const startAction = useStartAsddActionMutation(workspace, changeId)
  const markReady = useMarkAsddChangeReadyMutation(workspace, changeId, projectId)
  const autopilot = useSetAsddAutopilotMutation(workspace, changeId, projectId)
  const archive = useArchiveAsddChangeMutation(workspace, changeId, projectId)
  const remove = useDeleteAsddChangeMutation(workspace, projectId)
  const [tab, setTab] = useState<'proposal' | 'specs' | 'design' | 'tasks' | 'evidence'>(
    'proposal',
  )

  const failure =
    errorText(approve.error)
    ?? errorText(startAction.error)
    ?? errorText(markReady.error)
    ?? errorText(autopilot.error)
    ?? errorText(archive.error)
    ?? errorText(remove.error)

  const run = useCallback(
    (action: string) => {
      startAction.mutate(action, {
        onSuccess: (result) =>
          onRunInChat?.({
            changeId,
            skill: result.skill,
            prompt: result.prompt,
            autoSend: false,
          }),
      })
    },
    [changeId, onRunInChat, startAction],
  )

  const perform = useCallback(
    (actionId: string) => {
      const artifact = APPROVE_ACTIONS[actionId]
      if (artifact) {
        approve.mutate({ artifact })
        return
      }
      if (actionId === 'mark_ready') {
        markReady.mutate()
        return
      }
      if (actionId === 'archive') {
        archive.mutate(undefined, { onSuccess: onArchived })
        return
      }
      if (actionId === 'cancel') {
        remove.mutate(changeId, { onSuccess: onDeleted })
        return
      }
      run(actionId)
    },
    [approve, archive, changeId, markReady, onArchived, onDeleted, remove, run],
  )

  const busy =
    approve.isPending
    || startAction.isPending
    || markReady.isPending
    || autopilot.isPending
    || archive.isPending
    || remove.isPending

  const { status, risk, tasks_total: tasksTotal, tasks_done: tasksDone } = detail.change

  // An artifact's tab has to exist while the rail is asking for it. Keying
  // availability off "the file is already written" hid the Design tab from
  // exactly the change whose rail said it needed a design, and hid Evidence
  // from the change being verified.
  const tabs = [
    { id: 'proposal' as const, label: 'Proposal', available: true },
    { id: 'specs' as const, label: `Specs (${detail.deltas.length})`, available: true },
    {
      id: 'design' as const,
      label: 'Design',
      available: detail.design !== null || designApplies(risk, status),
    },
    {
      id: 'tasks' as const,
      label: tasksTotal > 0 ? `Tasks (${tasksDone}/${tasksTotal})` : 'Tasks',
      available: detail.tasks !== null || PLANNED_ONWARD.has(status),
    },
    {
      id: 'evidence' as const,
      label: `Evidence (${detail.evidence.length})`,
      available: detail.evidence.length > 0 || BUILDING_ONWARD.has(status),
    },
  ].filter((item) => item.available)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-start gap-2 border-b border-(--color-border) px-3 py-2.5">
        <Button type="button" variant="ghost" size="icon-sm" aria-label="Back" onClick={onBack}>
          <ChevronLeft />
        </Button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-sm font-semibold text-(--color-text)">
              {detail.change.title}
            </h2>
            <span
              className={cn(
                'rounded-full px-2 py-0.5 text-[10px] font-medium',
                statusTone(status),
              )}
            >
              {statusLabel(status)}
            </span>
            <span className={cn('text-[10px] font-medium', riskTone(risk))}>
              {riskLabel(risk)}
            </span>
            {tasksTotal > 0 && (
              <span className="text-[10px] tabular-nums text-(--color-text-muted)">
                {tasksDone}/{tasksTotal} tasks
              </span>
            )}
            <button
              type="button"
              disabled={autopilot.isPending || status === 'archived'}
              onClick={() => autopilot.mutate(!detail.rail.autopilot)}
              aria-pressed={detail.rail.autopilot}
              title={
                detail.rail.autopilot
                  ? 'Autopilot is carrying this change through its gates. Click to take it back.'
                  : 'Let the agent decide which gates need you. Click to turn on.'
              }
              className={cn(
                'ml-auto flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors disabled:opacity-50',
                detail.rail.autopilot
                  ? 'border-(--color-accent)/40 bg-(--color-accent)/10 text-(--color-accent)'
                  : 'border-(--color-border) text-(--color-text-subtle) hover:text-(--color-text)',
              )}
            >
              {autopilot.isPending ? (
                <Loader2 size={9} className="animate-spin" />
              ) : (
                <Bot size={10} />
              )}
              Autopilot {detail.rail.autopilot ? 'on' : 'off'}
            </button>
          </div>
          <p className="mt-0.5 truncate font-mono text-[10px] text-(--color-text-subtle)">
            {detail.change.path}
          </p>
          <div className="mt-1.5">
            <ApprovalStrip detail={detail} />
          </div>
        </div>
      </div>

      <div className="flex items-center gap-1 border-b border-(--color-border) px-3 py-1.5">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            className={cn(
              'rounded-md px-2 py-1 text-[11px] font-medium transition-colors',
              tab === item.id
                ? 'bg-(--color-accent)/10 text-(--color-accent)'
                : 'text-(--color-text-muted) hover:text-(--color-text)',
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-3 py-3">
        <AsddArtifactView detail={detail} tab={tab} />
      </div>

      {failure && (
        <p role="alert" className="border-t border-(--color-border) px-3 py-2 text-[11px] text-(--color-danger)">
          {failure}
        </p>
      )}

      <AsddActionRail
        status={status}
        risk={risk}
        rail={detail.rail}
        actions={detail.rail.actions.map((action) => {
          const primary = action.id === detail.rail.primary_action
          const destructive = action.id === 'cancel'
          return (
            <Button
              key={action.id}
              type="button"
              size="sm"
              variant={primary ? 'default' : destructive ? 'ghost' : 'outline'}
              disabled={busy || action.state === 'blocked'}
              // The rail spells out the *primary* action's blockers below. A
              // blocked secondary would otherwise be a greyed button with no
              // stated reason, which is the same dead end in miniature.
              title={action.blockers[0]?.message}
              onClick={() => perform(action.id)}
            >
              {busy && primary ? (
                <Loader2 size={13} className="animate-spin" />
              ) : action.id === 'autopilot_continue' ? (
                <Bot size={13} />
              ) : action.id === 'archive' ? (
                <Archive size={13} />
              ) : destructive ? (
                <Trash2 size={13} />
              ) : APPROVE_ACTIONS[action.id] ? (
                <Check size={13} />
              ) : action.id.startsWith('start_') ? (
                <Play size={13} />
              ) : (
                <ArrowRight size={13} />
              )}
              {action.label}
            </Button>
          )
        })}
      />
    </div>
  )
}

// ── Panel ────────────────────────────────────────────────────────────────

export function AgentSpecsPanel({
  workspace,
  projectId,
  active = true,
  onRunInChat,
}: AgentSpecsPanelProps) {
  const [view, setView] = useState<ChangesView>(loadView)
  const [query, setQuery] = useState('')
  // A change is opened by identity *and* by the repository it lives in. The
  // board spans every repository in the project, so the session's own
  // workspace says nothing about where the change being read is.
  const [openChange, setOpenChange] = useState<{ id: string; repository: string } | null>(null)
  const [creating, setCreating] = useState(false)
  const [catalogue, setCatalogue] = useState(false)
  const [repositoryFilter, setRepositoryFilter] = useState<string | null>(null)
  const [setupOpen, setSetupOpen] = useState(false)
  // Normally just `workspace`. Creating a change against a sibling repository
  // (a Coding Project can hold several) redirects the panel to follow it, so
  // the overview and detail queries below read the repository the change
  // actually landed in rather than the one the session happened to open on.
  const [activeWorkspace, setActiveWorkspace] = useState(workspace)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.asdd.changesView, view)
    } catch {
      // Remembering the view is a convenience, never a requirement.
    }
  }, [view])

  useEffect(() => {
    setActiveWorkspace(workspace)
    setRepositoryFilter(null)
  }, [workspace])

  const setup = useAsddSetupQuery(activeWorkspace, projectId, active)
  // Every repository in scope, not just the one this session opened on. A
  // change in a Coding Project routinely edits siblings, and the new-change
  // form can only offer a repository that is already set up.
  //
  // What the board needs is one *installed* repository, not a whole project.
  // Gating it on the project being complete hid every change a set-up
  // repository already had behind the setup screen for the one that was not:
  // work that existed, was being edited, and reported an empty board.
  const installedCount = setup.data?.installed_count ?? 0
  const ready = setup.data?.ready ?? false
  const hasCatalogue = installedCount > 0
  const changes = useAsddChangesQuery(activeWorkspace, projectId, active && hasCatalogue)
  const detail = useAsddChangeQuery(
    openChange?.repository ?? activeWorkspace,
    openChange?.id ?? null,
    active && hasCatalogue,
  )

  if (!active) return null

  if (setup.isLoading || !setup.data) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 size={16} className="animate-spin text-(--color-text-subtle)" />
      </div>
    )
  }

  // Nothing to show is the only reason to take the screen: with one
  // repository installed there is a board, and the repositories still to set
  // up are a banner on it rather than a wall in front of it.
  if (!hasCatalogue || setupOpen) {
    return (
      <div className="@container/asdd h-full overflow-auto">
        {setupOpen && hasCatalogue ? (
          <div className="px-3 pt-3">
            <Button type="button" size="sm" variant="ghost" onClick={() => setSetupOpen(false)}>
              <ChevronLeft size={13} />
              Back to changes
            </Button>
          </div>
        ) : null}
        <SetupView workspace={activeWorkspace} projectId={projectId} setup={setup.data} />
      </div>
    )
  }

  if (catalogue) {
    return (
      <div className="@container/asdd h-full">
        <AsddCatalogueView
          workspace={activeWorkspace}
          capabilities={changes.data?.capabilities ?? []}
          archived={changes.data?.archived ?? []}
          repositories={changes.data?.repositories ?? []}
          onBack={() => setCatalogue(false)}
        />
      </div>
    )
  }

  if (creating) {
    return (
      <div className="@container/asdd h-full overflow-auto">
        <NewChangeForm
          workspace={activeWorkspace}
          projectId={projectId}
          repositories={setup.data.repositories}
          onCancel={() => setCreating(false)}
          onCreated={(changeId, changeWorkspace) => {
            setActiveWorkspace(changeWorkspace)
            setCreating(false)
            setOpenChange({ id: changeId, repository: changeWorkspace })
          }}
        />
      </div>
    )
  }

  if (openChange && detail.data) {
    return (
      <div className="@container/asdd h-full">
        <ChangeDetail
          workspace={openChange.repository}
          projectId={projectId}
          detail={detail.data}
          onBack={() => setOpenChange(null)}
          onRunInChat={onRunInChat}
          onDeleted={() => setOpenChange(null)}
          onArchived={() => setOpenChange(null)}
        />
      </div>
    )
  }

  if (openChange && detail.isError) {
    return (
      <div className="@container/asdd flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <AlertTriangle size={18} className="text-(--color-warning)" />
        <p className="max-w-sm text-[11px] leading-4 text-(--color-text-muted)">
          {errorText(detail.error)}
        </p>
        <Button type="button" size="sm" variant="ghost" onClick={() => setOpenChange(null)}>
          Back to changes
        </Button>
      </div>
    )
  }

  return (
    <div className="@container/asdd h-full">
      <ChangesOverview
        changes={changes.data?.changes ?? []}
        archived={changes.data?.archived ?? []}
        capabilities={changes.data?.capabilities ?? []}
        repositories={setup.data.repositories}
        repositoryFilter={repositoryFilter}
        onRepositoryFilterChange={setRepositoryFilter}
        pendingSetup={ready ? 0 : setup.data.repository_count - installedCount}
        onOpenSetup={() => setSetupOpen(true)}
        view={view}
        onViewChange={setView}
        onOpen={(change) =>
          setOpenChange({ id: change.change_id, repository: change.repository })
        }
        onNew={() => setCreating(true)}
        onOpenCatalogue={() => setCatalogue(true)}
        query={query}
        onQueryChange={setQuery}
      />
    </div>
  )
}
