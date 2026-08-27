import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronLeft,
  FileCheck2,
  FolderGit2,
  Loader2,
  MessageSquareText,
  Play,
  Plus,
  Route,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  RefreshCw,
  X,
  Wrench,
} from 'lucide-react'

import { EasdConvergenceApiError, resolveTeamSession } from '@/api/client'
import type {
  EasdAppendableEvidenceKind,
  EasdActionId,
  EasdCriterionState,
  EasdEvidenceResult,
  EasdEvidenceKind,
  EasdAuthoringMetadata,
  EasdGenerateResponse,
  EasdGenerationTarget,
  EasdImpactTarget,
  EasdConstraint,
  EasdCriterionInput,
  EasdDeliveryMode,
  EasdRepositorySetup,
  EasdRiskTier,
  EasdRun,
  EasdRunDetail,
  EasdSetupResponse,
  EasdSpecificationInput,
} from '@/api/types'
import {
  useAcceptEasdPlanRevisionMutation,
  useAcceptEasdRevisionMutation,
  useAddEasdDeviationMutation,
  useAddEasdEvidenceMutation,
  useConvergeEasdRunMutation,
  useCreateEasdRunMutation,
  useCreateEasdRevisionMutation,
  useEasdRunQuery,
  useEasdRunsQuery,
  useEasdSetupQuery,
  useGenerateEasdScopeAndProofMutation,
  useInitializeEasdSetupMutation,
  useRetryEasdPlanningMutation,
  useRetryEasdSpecAuthoringMutation,
  useStartEasdRunInChatMutation,
  useStartEasdPlanningMutation,
  useStartEasdReviewMutation,
  useStartEasdSpecAuthoringMutation,
  useStartEasdVerificationMutation,
  useCodingWorkspaceSessionsQuery,
  useProjectSessionsQuery,
} from '@/queries'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Combobox } from '@/components/ui/combobox'
import { SelectControl } from '@/components/ui/select'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { SpecificationDiff } from '@/components/easd/SpecificationDiff'
import { EasdActionRail } from '@/components/easd/EasdActionRail'
import {
  EasdActionConfirmationDialog,
  type EasdConfirmableAction,
} from '@/components/easd/EasdActionConfirmationDialog'
import { useUIStore } from '@/stores/useUIStore'

interface EvoAgentSpecsPanelProps {
  workspace: string
  projectId?: string | null
  sessionId?: string | null
  active?: boolean
  onRunInChat?: (request: EasdRunChatRequest) => void
}

export interface EasdRunChatRequest {
  sessionId: string
  workspace: string
  projectId: string | null
  prompt: string | null
  autoSend: boolean
  phase: 'authoring' | 'planning' | 'implementation' | 'review' | 'verification'
}

type RunsView = 'board' | 'table' | 'list'

const EASD_DISPLAY_NAME = 'Agent Specification-Driven Development'

const RUN_VIEW_OPTIONS = [
  { value: 'board', label: 'Board' },
  { value: 'table', label: 'Table' },
  { value: 'list', label: 'List' },
] as const

const RISK_LABELS: Record<EasdRiskTier, string> = {
  trivial: 'Trivial',
  standard: 'Standard',
  cross_layer: 'Cross-layer',
  critical: 'Critical',
}

const BOARD_COLUMNS: Array<{
  id: string
  title: string
  description: string
  statuses: EasdRun['status'][]
}> = [
  {
    id: 'planning',
    title: 'Planning',
    description: 'Intent, spec approval, plan drafting and plan approval',
    statuses: ['intent', 'authoring', 'draft', 'accepted', 'planning', 'plan_review', 'planned'],
  },
  {
    id: 'execution',
    title: 'In progress',
    description: 'Implementation, review and verification',
    statuses: ['active', 'reviewing', 'verifying'],
  },
  {
    id: 'done',
    title: 'Completed',
    description: 'Converged runs',
    statuses: ['converged'],
  },
  {
    id: 'attention',
    title: 'Needs attention',
    description: 'Failed or cancelled',
    statuses: ['failed', 'cancelled'],
  },
]

function lines(value: string): string[] {
  return value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

function formatImpactTargets(items: EasdImpactTarget[]): string {
  return items.map((item) => `${item.repository}:${item.path} :: ${item.module ?? ''} :: ${item.reason}`).join('\n')
}

function parseImpactTargets(value: string, repository: string): EasdImpactTarget[] {
  return lines(value).map((line) => {
    const [location = '', module = '', reason = 'Generated or user-selected impact target'] = line.split('::').map((item) => item.trim())
    const separator = location.indexOf(':')
    return {
      repository: separator > 0 ? location.slice(0, separator).trim() : repository,
      path: separator > 0 ? location.slice(separator + 1).trim() : location,
      module: module || null,
      reason: reason || 'Generated or user-selected impact target',
    }
  }).filter((item) => item.path)
}

function formatConstraints(items: EasdConstraint[]): string {
  return items.map((item) => `[${item.kind}] ${item.statement}${item.source_refs.length ? ` :: ${item.source_refs.join(', ')}` : ''}`).join('\n')
}

function parseConstraints(value: string): EasdConstraint[] {
  return lines(value).map((line) => {
    const match = line.match(/^\[([^\]]+)\]\s*(.*)$/)
    const body = match?.[2] ?? line
    const [statement = '', refs = ''] = body.split('::').map((item) => item.trim())
    const rawKind = match?.[1]
    const kind = ['architecture', 'compatibility', 'security', 'operational', 'product'].includes(rawKind ?? '')
      ? rawKind as EasdConstraint['kind']
      : 'operational'
    return { kind, statement, source_refs: refs ? refs.split(',').map((item) => item.trim()).filter(Boolean) : [] }
  }).filter((item) => item.statement)
}

function formatCriteria(items: EasdCriterionInput[]): string {
  return items.map((item) => (
    `${item.id}: ${item.statement}\n`
    + `  evidence=${item.evidence_policy.allowed_kinds.join(',')}; `
    + `machine_required=${item.evidence_policy.machine_required}; `
    + `minimum_passes=${item.evidence_policy.minimum_passes}`
  )).join('\n')
}

function deliveryFlowForProof(proof: NonNullable<EasdGenerateResponse['proof']>) {
  return proof.delivery_flow ?? {
    mode: 'planned' as const,
    rationale: 'Plan is required by default until direct eligibility is proven.',
    confidence: 1,
    required_by: [] as string[],
  }
}

function errorText(error: unknown): string | null {
  return error instanceof Error ? error.message : null
}

function repositoryLabel(repository: EasdRepositorySetup): string {
  return repository.display_name || repository.name
}

function workspaceName(path: string): string {
  const parts = path.replace(/\/$/, '').split('/')
  return parts.at(-1) || path
}

function relativeTime(value: string): string {
  const timestamp = new Date(value).getTime()
  const elapsed = Math.max(0, Date.now() - timestamp)
  const minutes = Math.floor(elapsed / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function statusTone(status: EasdRun['status']): string {
  if (status === 'converged') return 'bg-(--color-success-subtle) text-(--color-success)'
  if (status === 'failed' || status === 'cancelled') {
    return 'bg-(--color-error-subtle) text-(--color-error)'
  }
  if (status === 'planning' || status === 'active' || status === 'reviewing' || status === 'verifying') {
    return 'bg-(--color-accent)/10 text-(--color-accent)'
  }
  return 'bg-(--bg-key) text-(--color-text-muted)'
}

function riskTone(risk: EasdRiskTier): string {
  if (risk === 'critical') return 'text-(--color-error)'
  if (risk === 'cross_layer') return 'text-(--color-warning)'
  return 'text-(--color-text-muted)'
}

function criterionTone(status: EasdCriterionState['status']): string {
  if (status === 'passed' || status === 'waived') return 'text-(--color-success)'
  if (status === 'failed') return 'text-(--color-error)'
  if (status === 'in_progress') return 'text-(--color-accent)'
  return 'text-(--color-text-muted)'
}

function planningPrompt(detail: EasdRunDetail): string {
  return `$easd-plan\n\nPlan EASD run “${detail.run.title}” from accepted spec hash ${detail.active_spec?.content_hash ?? 'missing'}. This is planning only: do not edit product files, delegate implementation, approve the plan, activate implementation, review, verify, or converge. Build a complete provider-neutral acyclic mission graph with stable IDs, implementation ownership for every required AC, repository/path scope inside the accepted impact targets, dependencies, expected outputs, constraints, safe verification commands, isolation, integration ownership, a review mission for every run (independent when required by risk), and a verification mission owning every accepted Proof command. When the plan is implementable and self-reviewed, call easd_submit_plan with run ID ${detail.run.id}, the full typed plan, coverage/dependency summary, and honest confidence. Stop after persistence and ask the user to review and Approve plan.`
}

function implementationPrompt(detail: EasdRunDetail, resume: boolean): string {
  const action = resume ? 'Resume' : 'Execute'
  const contract = detail.active_plan
    ? `accepted plan hash ${detail.active_plan.content_hash}. Execute only approved plan missions and their AC/path/dependency/evidence contracts.`
    : 'the user-approved direct flow. Stay inside the accepted Spec/AC/path/evidence contract; no Plan artifact exists for this run.'
  return `$easd-implement\n\n${action} implementation for EASD run “${detail.run.title}” using accepted spec hash ${detail.active_spec?.content_hash ?? 'from context'} and ${contract} Persist real machine evidence and deviations through existing typed runtime flows. Do not start independent Review, final Verify, or Converge; the user advances those phases explicitly.`
}

function reviewPrompt(detail: EasdRunDetail): string {
  const independent = detail.active_plan?.plan.review_required
    ? 'The approved plan requires independence: delegate the review mission to a specialist who did not implement the reviewed ACs and require that reviewer to call easd_submit_review with its delegation task ID.'
    : detail.active_plan
      ? 'Perform or delegate the approved review mission and call easd_submit_review with cited per-AC results.'
      : 'Perform or delegate the mandatory direct-flow Review and call easd_submit_review with cited per-AC results; do not invent Plan identity.'
  const flowContract = detail.active_plan
    ? `accepted plan hash ${detail.active_plan.content_hash}`
    : 'the accepted direct-flow Spec (no Plan artifact)'
  return `$easd-review\n\nReview EASD run “${detail.run.title}” against accepted spec hash ${detail.active_spec?.content_hash ?? 'from context'} and ${flowContract}. Review is read-only for product files. ${independent} Inspect the integrated revision rather than handoff prose, cite repository paths/sources, report passed/failed/inconclusive for every assigned AC, and persist the exact reviewed revision. Do not fix findings, start Verify, or Converge; the user controls the next phase.`
}

function verificationPrompt(detail: EasdRunDetail): string {
  const flowContract = detail.active_plan
    ? `accepted plan hash ${detail.active_plan.content_hash}`
    : 'the accepted direct-flow Spec without a Plan artifact'
  return `$easd-verify\n\nRun final verification for EASD run “${detail.run.title}” against accepted spec hash ${detail.active_spec?.content_hash ?? 'from context'} and ${flowContract}. Re-read repository state, the AC matrix, missions, machine/review evidence, deviations, approved commands, integration state, and docs. Execute approved verification work through an EASD-bound delegation so the runtime records a fresh, revision-bound CompletionContract even though Verify is read-only. Report ready for convergence, rework required, or manual verification required with exact gaps. Do not fabricate evidence or invoke Converge; the user triggers the server gate separately.`
}

function specificationAuthoringPrompt(detail: EasdRunDetail): string {
  const intent = detail.run.intent
  return `$easd-specify\n\nDraft the specification for EASD run ${detail.run.id}. This is specification authoring only: do not implement, edit product files, approve the specification, activate implementation, or converge the run. Persisted Intent — title: “${intent?.title ?? detail.run.title}”; problem: ${intent?.problem ?? 'not recorded'}; optional intended outcome: ${intent?.outcome || 'not supplied — propose an observable outcome from repository evidence'}. Read .evoflux/easd/config.json, RULES.md, the configured repository data store, every authorized project repository's AGENTS.md, current docs, relevant source, configuration and tests. Ask clarifying questions before choosing behavior when evidence is ambiguous. Produce a complete provider-neutral EASD specification with goals, non-goals, grounded source references, repository-qualified impact targets, constraints/security/compatibility boundaries, risk tier, observable ACs with evidence policy, safe verification commands, and a reasoned direct|planned delivery_flow recommendation. Verification commands are one non-shell argv-style command per line; do not use python -c snippets or &&, ||, ;, |, >, or <. Prefer canonical commands such as python -m pytest tests/test_feature.py. Direct is only for low-risk single-boundary work; cite every condition that forces Plan. When complete, call easd_submit_specification with this exact run ID, the full specification, grounding summary and confidence. Stop after repository persistence and tell the user the draft and driven flow are ready for review.`
}

function loadRunsView(): RunsView {
  try {
    const stored = localStorage.getItem(STORAGE_KEYS.easd.runsView)
    if (stored === 'board' || stored === 'table' || stored === 'list') return stored
  } catch {
    // Storage is optional in restricted webviews.
  }
  return 'board'
}

function SetupView({
  setup,
  workspace,
  projectId,
  onReady,
}: {
  setup: EasdSetupResponse
  workspace: string
  projectId?: string | null
  onReady: () => void
}) {
  const mutation = useInitializeEasdSetupMutation(workspace, projectId)
  const pendingPaths = mutation.variables?.repositoryPaths ?? []
  const remaining = setup.repositories.filter((repository) => !repository.installed)
  const skillNames = setup.repositories[0]?.skill_names ?? []
  const [dataDirectory, setDataDirectory] = useState(
    setup.repositories.find((repository) => !repository.installed)?.data_directory
      ?? setup.repositories[0]?.data_directory
      ?? 'documents/easd',
  )
  const progress = setup.repository_count === 0
    ? 0
    : Math.round((setup.installed_count / setup.repository_count) * 100)

  const initialize = async (repositories: EasdRepositorySetup[]) => {
    // Repair is intentionally isolated: one invalid repository must never make
    // the bulk action overwrite valid edited Skills in an upgradeable sibling.
    const safe = repositories.filter((repository) => repository.status !== 'invalid')
    const repairs = repositories.filter((repository) => repository.status === 'invalid')
    let result: EasdSetupResponse | undefined
    if (safe.length > 0) {
      result = await mutation.mutateAsync({
        repositoryPaths: safe.map((repository) => repository.path),
        dataDirectory: dataDirectory.trim(),
        overwrite: false,
      })
    }
    if (repairs.length > 0) {
      result = await mutation.mutateAsync({
        repositoryPaths: repairs.map((repository) => repository.path),
        dataDirectory: dataDirectory.trim(),
        overwrite: true,
      })
    }
    if (result?.ready) onReady()
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-3 @xl/easd:p-5">
      <div className="flex items-center gap-2 px-1 text-[10px]" aria-label="Setup progress">
        <span className="flex items-center gap-1.5 font-medium text-(--color-accent)"><span className="flex size-5 items-center justify-center rounded-full bg-(--color-accent) text-[9px] font-semibold text-(--color-text-on-accent)">1</span> Set up repositories</span>
        <span className="h-px min-w-4 flex-1 bg-(--color-border)" />
        <span className="flex items-center gap-1.5 text-(--color-text-subtle)"><span className="flex size-5 items-center justify-center rounded-full border border-(--color-border) bg-(--bg-card) text-[9px] font-semibold">2</span> Create a run</span>
      </div>
      <section className="overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card)">
        <div className="border-b border-(--color-border) bg-gradient-to-br from-(--color-accent)/14 via-(--bg-card) to-(--bg-card) p-4 @xl/easd:p-5">
          <div className="flex items-start gap-4">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-(--color-accent) text-(--color-text-on-accent) shadow-sm">
              <Route size={21} aria-hidden />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-(--color-accent)/12 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-(--color-accent)">EASD</span>
                <span className="text-[10px] font-medium uppercase tracking-[0.16em] text-(--color-text-subtle)">One-time setup</span>
              </div>
              <h2 className="mt-2 text-base font-semibold leading-5 text-(--color-text)">Set up {EASD_DISPLAY_NAME}</h2>
              <p className="mt-1.5 max-w-xl text-xs leading-5 text-(--color-text-muted)">
                Add a version-controlled EASD knowledge base and five Coding-only project skills to every repository. Existing project docs stay in place; Runs become available when the whole scope is ready.
              </p>
            </div>
          </div>
          <div className="mt-5 flex items-center gap-3">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-(--bg-key)">
              <div className="h-full rounded-full bg-(--color-accent) transition-[width]" style={{ width: `${progress}%` }} />
            </div>
            <span className="shrink-0 text-xs font-medium text-(--color-text-2)">
              {setup.installed_count}/{setup.repository_count} ready
            </span>
          </div>
        </div>

        <div className="divide-y divide-(--color-border)">
          {remaining.length > 0 && (
            <div className="px-4 py-4 @xl/easd:px-5">
              <label className="block text-xs font-medium text-(--color-text-2)">
                EASD knowledge-base folder
                <input
                  value={dataDirectory}
                  onChange={(event) => setDataDirectory(event.target.value)}
                  className="mt-1.5 h-10 w-full rounded-lg border border-(--color-border) bg-(--bg-page) px-3 font-mono text-xs text-(--color-text) outline-none focus:border-(--color-accent) focus:ring-2 focus:ring-(--color-accent)/10"
                  placeholder="documents/easd"
                  spellCheck={false}
                />
              </label>
              <p className="mt-1.5 text-[10px] leading-4 text-(--color-text-subtle)">Repository-relative and version-controlled. It contains common Specs, optional living knowledge sections, templates, and Run evidence. Initialization never moves or copies existing project documentation.</p>
            </div>
          )}
          {setup.repositories.map((repository) => {
            const busy = mutation.isPending && pendingPaths.includes(repository.path)
            return (
              <div key={repository.path} className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-2 px-4 py-3.5 @sm/easd:grid-cols-[auto_minmax(0,1fr)_auto] @xl/easd:px-5">
                <span className={cn(
                  'flex size-9 shrink-0 items-center justify-center rounded-xl',
                  repository.installed
                    ? 'bg-(--color-success-subtle) text-(--color-success)'
                    : repository.status === 'invalid'
                      ? 'bg-(--color-error-subtle) text-(--color-error)'
                      : repository.status === 'upgrade_required'
                        ? 'bg-(--color-accent)/12 text-(--color-accent)'
                      : 'bg-(--bg-key) text-(--color-text-muted)',
                )}>
                  {repository.installed
                    ? <CheckCircle2 size={17} />
                    : repository.status === 'invalid' || repository.status === 'upgrade_required'
                      ? <Wrench size={16} />
                      : <FolderGit2 size={16} />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-medium text-(--color-text)">{repositoryLabel(repository)}</p>
                    <span className={cn(
                      'rounded-full px-2 py-0.5 text-[10px] font-medium',
                      repository.installed
                        ? 'bg-(--color-success-subtle) text-(--color-success)'
                        : repository.status === 'invalid'
                          ? 'bg-(--color-error-subtle) text-(--color-error)'
                          : repository.status === 'upgrade_required'
                            ? 'bg-(--color-accent)/12 text-(--color-accent)'
                          : 'bg-(--bg-key) text-(--color-text-muted)',
                    )}>
                      {repository.installed
                        ? 'Ready'
                        : repository.status === 'invalid'
                          ? 'Needs repair'
                          : repository.status === 'upgrade_required'
                            ? 'Upgrade available'
                            : 'Not initialized'}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate font-mono text-[10px] text-(--color-text-subtle)" title={repository.path}>{repository.path}</p>
                  <p className="mt-1 text-[10px] text-(--color-text-subtle)">
                    {repository.skill_names.length} {repository.installed ? 'Coding skills' : 'required Coding skills'} · {repository.skills_path}
                  </p>
                  <p className="mt-0.5 truncate font-mono text-[10px] text-(--color-text-subtle)">data · {repository.data_directory}</p>
                  {repository.issue && (
                    <p className={cn('mt-1 text-[11px]', repository.status === 'invalid' ? 'text-(--color-error)' : 'text-(--color-text-muted)')}>
                      {repository.issue}
                    </p>
                  )}
                </div>
                {!repository.installed && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="col-start-2 justify-self-start @sm/easd:col-start-3 @sm/easd:row-start-1"
                    disabled={mutation.isPending}
                    onClick={() => void initialize([repository])}
                  >
                    {busy && <Loader2 className="animate-spin" />}
                    {repository.status === 'invalid'
                      ? 'Repair'
                      : repository.status === 'upgrade_required'
                        ? 'Upgrade'
                        : 'Initialize'}
                  </Button>
                )}
              </div>
            )
          })}
        </div>

        <footer className="flex flex-col gap-3 border-t border-(--color-border) bg-(--bg-page)/50 p-4 @2xl/easd:flex-row @2xl/easd:items-center @2xl/easd:justify-between @xl/easd:px-5">
          <div>
            <p className="text-xs font-medium text-(--color-text-2)">Files added to each repository</p>
            <p className="mt-0.5 break-all font-mono text-[10px] text-(--color-text-subtle)">.evoflux/easd/config.json · .evoflux/easd/RULES.md · {dataDirectory || 'documents/easd'}/ · .evoflux/skills/easd-*/</p>
            <p className="mt-1 text-[10px] text-(--color-text-subtle)">Repository files are the shared source of truth; setup preserves existing docs, and Skills are Coding-only and never approve a specification.</p>
            <div className="mt-2 flex flex-wrap gap-1" aria-label="EASD skill bundle">
              {skillNames.map((name) => (
                <span key={name} className="rounded-md border border-(--color-border) bg-(--bg-card) px-1.5 py-0.5 font-mono text-[9px] text-(--color-text-muted)">
                  {name}
                </span>
              ))}
            </div>
          </div>
          {remaining.length > 0 ? (
            <Button type="button" disabled={mutation.isPending} onClick={() => void initialize(remaining)}>
              {mutation.isPending && <Loader2 className="animate-spin" />}
              Set up {remaining.length === 1 ? 'repository' : `${remaining.length} repositories`}
            </Button>
          ) : (
            <Button type="button" onClick={onReady}>Continue to runs <ArrowRight /></Button>
          )}
        </footer>
      </section>
      {mutation.error && <p role="alert" className="text-center text-xs text-(--color-error)">{errorText(mutation.error)}</p>}
    </div>
  )
}

function CreateIntentForm({
  setup,
  projectId,
  sessionId,
  initialWorkspace,
  onCreated,
  onCancel,
}: {
  setup: EasdSetupResponse
  projectId?: string | null
  sessionId?: string | null
  initialWorkspace: string
  onCreated: (runId: string) => void
  onCancel: () => void
}) {
  const firstWorkspace = setup.repositories.find((item) => item.path === initialWorkspace)?.path
    ?? setup.repositories[0]?.path
    ?? initialWorkspace
  const [targetWorkspace, setTargetWorkspace] = useState(firstWorkspace)
  const [title, setTitle] = useState('')
  const [problem, setProblem] = useState('')
  const [outcome, setOutcome] = useState('')
  const mutation = useCreateEasdRunMutation(targetWorkspace, projectId)
  const canCreate = Boolean(title.trim() && problem.trim())

  const submit = async () => {
    if (!canCreate) return
    const detail = await mutation.mutateAsync({
      sessionId,
      intent: {
        title: title.trim(),
        problem: problem.trim(),
        outcome: outcome.trim() || undefined,
      },
    })
    onCreated(detail.run.id)
  }

  return (
    <div className="@container/easd flex h-full min-h-0 flex-col bg-(--bg-page)">
      <header className="flex min-h-16 shrink-0 items-center gap-3 border-b border-(--color-border) px-3 @xl/easd:px-4">
        <Button type="button" variant="ghost" size="icon-sm" onClick={onCancel} aria-label="Back to runs"><ChevronLeft /></Button>
        <div className="min-w-0 flex-1"><p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-(--color-accent)">New EASD run</p><h2 className="mt-1 text-sm font-semibold text-(--color-text)">Start with Intent</h2></div>
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-3 @xl/easd:p-5">
        <section className="mx-auto max-w-3xl rounded-2xl border border-(--color-border) bg-(--bg-card) p-4 @xl/easd:p-5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-(--color-accent)">01 · Intent</p>
          <h3 className="mt-1 text-sm font-semibold text-(--color-text)">Describe the problem; agents draft the specification next</h3>
          <p className="mt-1 text-xs leading-5 text-(--color-text-muted)">Creating this run does not create or approve a specification. The next action opens a Coding chat where the lead inspects authorized repositories, asks clarifying questions, and submits a reviewable draft.</p>
          <div className="mt-5 grid gap-4 @3xl/easd:grid-cols-2">
            {setup.repositories.length > 1 && (
              <label className="block text-xs font-medium text-(--color-text-2) @3xl/easd:col-span-2">
                Owning repository
                <Combobox
                  value={targetWorkspace}
                  onValueChange={(value) => { if (value) setTargetWorkspace(value) }}
                  items={setup.repositories.map((repository) => ({ value: repository.path, label: repositoryLabel(repository), description: repository.path, keywords: `${repository.name} ${repository.display_name ?? ''}` }))}
                  ariaLabel="Owning repository"
                  placeholder="Choose an owning repository"
                  searchPlaceholder="Search repositories or paths…"
                  emptyText="No repository matches."
                  clearable={false}
                  className="mt-1.5 h-10"
                />
              </label>
            )}
            <label className="block text-xs font-medium text-(--color-text-2) @3xl/easd:col-span-2">Run title<input value={title} onChange={(event) => setTitle(event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-(--color-border) bg-(--bg-page) px-3 text-sm text-(--color-text) outline-none focus:border-(--color-accent) focus:ring-2 focus:ring-(--color-accent)/10" placeholder="Add deterministic rate limiting" autoFocus /></label>
            <label className="block text-xs font-medium text-(--color-text-2)">Problem<textarea value={problem} onChange={(event) => setProblem(event.target.value)} className="mt-1.5 min-h-32 w-full resize-y rounded-lg border border-(--color-border) bg-(--bg-page) p-3 text-sm text-(--color-text) outline-none focus:border-(--color-accent) focus:ring-2 focus:ring-(--color-accent)/10" placeholder="What is wrong today, and why does it matter?" /></label>
            <label className="block text-xs font-medium text-(--color-text-2)">Intended outcome <span className="font-normal text-(--color-text-subtle)">· optional</span><textarea value={outcome} onChange={(event) => setOutcome(event.target.value)} className="mt-1.5 min-h-32 w-full resize-y rounded-lg border border-(--color-border) bg-(--bg-page) p-3 text-sm text-(--color-text) outline-none focus:border-(--color-accent) focus:ring-2 focus:ring-(--color-accent)/10" placeholder="Leave blank for the drafting agent to propose an observable outcome." /></label>
          </div>
          {mutation.error && <p role="alert" className="mt-3 text-xs text-(--color-error)">{errorText(mutation.error)}</p>}
        </section>
      </div>
      <footer className="flex shrink-0 items-center justify-between gap-3 border-t border-(--color-border) bg-(--bg-card)/70 p-3 @xl/easd:px-5"><p className="text-[10px] text-(--color-text-subtle)">{canCreate ? 'Intent ready · specification is not drafted yet' : 'Run title and Problem are required'}</p><div className="flex gap-2"><Button type="button" variant="outline" onClick={onCancel}>Cancel</Button><Button type="button" disabled={!canCreate || mutation.isPending} onClick={() => void submit()}>{mutation.isPending && <Loader2 className="animate-spin" />}Create run</Button></div></footer>
    </div>
  )
}

function SpecificationEditorForm({
  setup,
  runId,
  initialSpecification,
  projectId,
  sessionId,
  initialWorkspace,
  onSaved,
  onCancel,
}: {
  setup: EasdSetupResponse
  runId: string
  initialSpecification: EasdSpecificationInput
  projectId?: string | null
  sessionId?: string | null
  initialWorkspace: string
  onSaved: () => void
  onCancel: () => void
}) {
  const firstWorkspace = setup.repositories.find((item) => item.path === initialWorkspace)?.path
    ?? setup.repositories[0]?.path
    ?? initialWorkspace
  const [targetWorkspace] = useState(firstWorkspace)
  const [title, setTitle] = useState(initialSpecification.title)
  const [problem, setProblem] = useState(initialSpecification.problem)
  const [outcome, setOutcome] = useState(initialSpecification.outcome)
  const [goals, setGoals] = useState(initialSpecification.goals.join('\n'))
  const [nonGoals, setNonGoals] = useState(initialSpecification.non_goals.join('\n'))
  const [sourceRefs, setSourceRefs] = useState(initialSpecification.source_refs.join('\n'))
  const [impactTargets, setImpactTargets] = useState(formatImpactTargets(initialSpecification.impact_targets ?? []))
  const [constraints, setConstraints] = useState(formatConstraints(initialSpecification.constraints ?? []))
  const [criteria, setCriteria] = useState(initialSpecification.criteria.map((item) => item.statement).join('\n'))
  const [verificationCommands, setVerificationCommands] = useState((initialSpecification.verification_commands ?? []).join('\n'))
  const [riskTier, setRiskTier] = useState<EasdRiskTier>(initialSpecification.risk_tier)
  const initialFlow = initialSpecification.delivery_flow ?? {
    mode: 'planned' as const,
    rationale: 'Plan is required by default until direct eligibility is proven.',
    confidence: 1,
    required_by: [],
  }
  const [deliveryMode, setDeliveryMode] = useState<EasdDeliveryMode>(initialFlow.mode)
  const [deliveryRationale, setDeliveryRationale] = useState(initialFlow.rationale)
  const [deliveryConfidence, setDeliveryConfidence] = useState(initialFlow.confidence)
  const [deliveryRequiredBy, setDeliveryRequiredBy] = useState(initialFlow.required_by)
  const [generatedCriteria, setGeneratedCriteria] = useState<EasdCriterionInput[] | null>(initialSpecification.criteria)
  const [proposal, setProposal] = useState<EasdGenerateResponse | null>(null)
  const [clarification, setClarification] = useState<EasdGenerateResponse | null>(null)
  const [proposalBase, setProposalBase] = useState<{
    scope?: { intent: string; section: string }
    proof?: { intent: string; section: string }
  }>({})
  const [generationHistory, setGenerationHistory] = useState<EasdGenerateResponse[]>([])
  const [sectionGeneration, setSectionGeneration] = useState<{ scope?: string; proof?: string }>({})
  const [appliedGeneration, setAppliedGeneration] = useState<{ scope?: string; proof?: string }>({})
  const [appliedSnapshots, setAppliedSnapshots] = useState<{ scope?: string; proof?: string }>({})
  const [clarificationAnswers, setClarificationAnswers] = useState<Record<string, string>>({})
  const [replaceConfirmed, setReplaceConfirmed] = useState<{ scope: boolean; proof: boolean }>({ scope: false, proof: false })
  const [lastGenerationTarget, setLastGenerationTarget] = useState<EasdGenerationTarget>('both')
  const mutation = useCreateEasdRevisionMutation(runId)
  const generation = useGenerateEasdScopeAndProofMutation()
  const generationAbort = useRef<AbortController | null>(null)
  const criterionLines = lines(criteria)
  const canSubmit = Boolean(title.trim() && problem.trim() && outcome.trim() && criterionLines.length)
  const canGenerate = Boolean(sessionId && title.trim() && problem.trim())
  const repositoryName = setup.repositories.find((item) => item.path === targetWorkspace)
    ?.display_name ?? workspaceName(targetWorkspace)

  const scopeSnapshot = () => JSON.stringify({ outcome, goals, nonGoals, sourceRefs, impactTargets, constraints })
  const proofSnapshot = () => JSON.stringify({ criteria, verificationCommands, riskTier, deliveryMode, deliveryRationale, deliveryRequiredBy })
  const intentSnapshot = () => JSON.stringify({ title, problem, outcome, targetWorkspace })

  const currentCriteria = (): EasdCriterionInput[] => {
    if (
      generatedCriteria
      && generatedCriteria.map((item) => item.statement).join('\n') === criterionLines.join('\n')
    ) return generatedCriteria
    return criterionLines.map((statement, index) => ({
      id: `AC-${index + 1}`,
      statement,
      required: true,
      evidence_policy: {
        allowed_kinds: ['machine', 'review', 'manual'],
        machine_required: riskTier !== 'trivial',
        minimum_passes: 1,
      },
    }))
  }

  const generate = async (
    target: EasdGenerationTarget,
    answers: Record<string, string> = clarificationAnswers,
  ) => {
    if (!canGenerate || !sessionId) return
    generationAbort.current?.abort()
    const controller = new AbortController()
    generationAbort.current = controller
    setLastGenerationTarget(target)
    setReplaceConfirmed({ scope: false, proof: false })
    const base = { intent: intentSnapshot(), scope: scopeSnapshot(), proof: proofSnapshot() }
    try {
      const result = await generation.mutateAsync({
        signal: controller.signal,
        request: {
          workspace: targetWorkspace,
          project_id: projectId,
          session_id: sessionId,
          target,
          intent: {
            title: title.trim(),
            problem: problem.trim(),
            outcome: outcome.trim() || undefined,
          },
          current_draft: {
            goals: lines(goals),
            non_goals: lines(nonGoals),
            source_refs: lines(sourceRefs),
            impact_targets: parseImpactTargets(impactTargets, repositoryName),
            constraints: parseConstraints(constraints),
            risk_tier: riskTier,
            delivery_flow: {
              mode: deliveryMode,
              rationale: deliveryRationale,
              confidence: deliveryConfidence,
              required_by: deliveryRequiredBy,
            },
            criteria: currentCriteria(),
            verification_commands: lines(verificationCommands),
          },
          clarifications: (clarification?.questions ?? [])
            .filter((question) => (answers[question.id] ?? '').trim())
            .map((question) => ({
              question: question.question,
              answer: answers[question.id].trim(),
            })),
        },
      })
      if (result.status === 'needs_clarification') {
        setClarification(result)
      } else {
        setClarification(null)
        setClarificationAnswers({})
        setGenerationHistory((items) => [...items.filter((item) => item.generation_id !== result.generation_id), result])
        setSectionGeneration((value) => ({
          ...value,
          ...(result.scope ? { scope: result.generation_id } : {}),
          ...(result.proof ? { proof: result.generation_id } : {}),
        }))
        setProposalBase((value) => ({
          ...value,
          ...(result.scope ? { scope: { intent: base.intent, section: base.scope } } : {}),
          ...(result.proof ? { proof: { intent: base.intent, section: base.proof } } : {}),
        }))
        setProposal((previous) => {
          if (!previous || previous.status !== 'ready') return result
          const provenance = new Map(
            [...previous.provenance, ...result.provenance].map((item) => [
              `${item.repository}:${item.path}`,
              item,
            ]),
          )
          return {
            ...result,
            outcome: result.outcome ?? previous.outcome,
            scope: result.scope ?? previous.scope,
            proof: result.proof ?? previous.proof,
            provenance: [...provenance.values()],
          }
        })
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') generation.reset()
    } finally {
      if (generationAbort.current === controller) generationAbort.current = null
    }
  }

  const applyScope = () => {
    if (!proposal?.scope || !proposal.outcome || !proposalBase.scope) return
    if (
      (intentSnapshot() !== proposalBase.scope.intent || scopeSnapshot() !== proposalBase.scope.section)
      && !replaceConfirmed.scope
    ) {
      setReplaceConfirmed((value) => ({ ...value, scope: true }))
      return
    }
    setOutcome(proposal.outcome)
    setGoals(proposal.scope.goals.join('\n'))
    setNonGoals(proposal.scope.non_goals.join('\n'))
    setSourceRefs(proposal.scope.source_refs.join('\n'))
    setImpactTargets(formatImpactTargets(proposal.scope.impact_targets))
    setConstraints(formatConstraints(proposal.scope.constraints))
    setAppliedSnapshots({
      ...appliedSnapshots,
      scope: JSON.stringify({
        outcome: proposal.outcome,
        goals: proposal.scope.goals.join('\n'),
        nonGoals: proposal.scope.non_goals.join('\n'),
        sourceRefs: proposal.scope.source_refs.join('\n'),
        impactTargets: formatImpactTargets(proposal.scope.impact_targets),
        constraints: formatConstraints(proposal.scope.constraints),
      }),
    })
    setAppliedGeneration({ ...appliedGeneration, scope: sectionGeneration.scope })
    setReplaceConfirmed((value) => ({ ...value, scope: false }))
  }

  const applyProof = () => {
    if (!proposal?.proof || !proposalBase.proof) return
    if (
      (intentSnapshot() !== proposalBase.proof.intent || proofSnapshot() !== proposalBase.proof.section)
      && !replaceConfirmed.proof
    ) {
      setReplaceConfirmed((value) => ({ ...value, proof: true }))
      return
    }
    const proposedFlow = deliveryFlowForProof(proposal.proof)
    setCriteria(proposal.proof.criteria.map((item) => item.statement).join('\n'))
    setGeneratedCriteria(proposal.proof.criteria)
    setVerificationCommands(proposal.proof.verification_commands.join('\n'))
    setRiskTier(proposal.proof.risk_tier)
    setDeliveryMode(proposedFlow.mode)
    setDeliveryRationale(proposedFlow.rationale)
    setDeliveryConfidence(proposedFlow.confidence)
    setDeliveryRequiredBy(proposedFlow.required_by)
    setAppliedSnapshots({
      ...appliedSnapshots,
      proof: JSON.stringify({
        criteria: proposal.proof.criteria.map((item) => item.statement).join('\n'),
        verificationCommands: proposal.proof.verification_commands.join('\n'),
        riskTier: proposal.proof.risk_tier,
        deliveryMode: proposedFlow.mode,
        deliveryRationale: proposedFlow.rationale,
        deliveryRequiredBy: proposedFlow.required_by,
      }),
    })
    setAppliedGeneration({ ...appliedGeneration, proof: sectionGeneration.proof })
    setReplaceConfirmed((value) => ({ ...value, proof: false }))
  }

  const authoringMetadata = (): EasdAuthoringMetadata | null => {
    const generations = generationHistory.flatMap((item) => {
      const appliedSections = (['scope', 'proof'] as const).filter(
        (section) => appliedGeneration[section] === item.generation_id,
      )
      if (!appliedSections.length) return []
      const editedSections = appliedSections.filter((section) => (
        section === 'scope'
          ? appliedSnapshots.scope !== scopeSnapshot()
          : appliedSnapshots.proof !== proofSnapshot()
      ))
      return [{
        generation_id: item.generation_id,
        generated_at: item.generated_at,
        provider: item.provider,
        model: item.model,
        confidence: item.confidence,
        rationale: item.rationale,
        context_fingerprint: item.context_fingerprint,
        base_fingerprint: item.base_fingerprint,
        applied_sections: appliedSections,
        edited_sections: editedSections,
        sources: item.provenance.filter((source) => source.used_for.some((section) => appliedSections.includes(section))),
        usage: item.usage,
      }]
    })
    return generations.length ? { generations } : null
  }

  const submit = async () => {
    if (!canSubmit) return
    const specification: EasdSpecificationInput = {
      title: title.trim(),
      problem: problem.trim(),
      outcome: outcome.trim(),
      goals: lines(goals),
      non_goals: lines(nonGoals),
      source_refs: lines(sourceRefs),
      impact_targets: parseImpactTargets(impactTargets, repositoryName),
      constraints: parseConstraints(constraints),
      verification_commands: lines(verificationCommands),
      risk_tier: riskTier,
      delivery_flow: {
        mode: deliveryMode,
        rationale: deliveryRationale.trim() || 'User-selected EASD delivery flow.',
        confidence: deliveryConfidence,
        required_by: deliveryRequiredBy,
      },
      criteria: currentCriteria(),
    }
    await mutation.mutateAsync({
      specification,
      authoring: authoringMetadata(),
    })
    onSaved()
  }

  return (
    <div className="@container/easd flex h-full min-h-0 flex-col bg-(--bg-page)">
      <header className="flex min-h-16 shrink-0 items-center gap-3 border-b border-(--color-border) px-3 @xl/easd:px-4">
        <Button type="button" variant="ghost" size="icon-sm" onClick={onCancel} aria-label="Back to runs">
          <ChevronLeft aria-hidden />
        </Button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-(--color-accent)/10 px-2 py-0.5 text-[9px] font-semibold tracking-wide text-(--color-accent)">EASD</span>
            <span className="text-[10px] text-(--color-text-subtle)">New draft</span>
          </div>
          <h2 className="mt-1 text-sm font-semibold text-(--color-text)">Edit specification draft</h2>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-3 @xl/easd:p-5">
        <div className="mx-auto max-w-4xl space-y-4">
          <section className="rounded-2xl border border-(--color-border) bg-(--bg-card) p-4">
            <div className="mb-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-(--color-accent)">01 · Intent</p>
              <h3 className="mt-1 text-sm font-semibold text-(--color-text)">Describe the change before agents act</h3>
            </div>
            <div className="grid gap-4 @3xl/easd:grid-cols-2">
              <div className="rounded-lg border border-(--color-border) bg-(--bg-key)/35 p-3 text-xs text-(--color-text-muted) @3xl/easd:col-span-2"><span className="font-medium text-(--color-text-2)">Owning repository</span><span className="ml-2 font-mono text-[10px]">{repositoryName} · {targetWorkspace}</span></div>
              <label className="block text-xs font-medium text-(--color-text-2) @3xl/easd:col-span-2">
                Run title
                <input value={title} onChange={(event) => setTitle(event.target.value)} className="mt-1.5 h-10 w-full rounded-lg border border-(--color-border) bg-(--bg-page) px-3 text-sm text-(--color-text) outline-none focus:border-(--color-accent) focus:ring-2 focus:ring-(--color-accent)/10" placeholder="Add deterministic rate limiting" autoFocus />
              </label>
              <label className="block text-xs font-medium text-(--color-text-2)">
                Problem
                <textarea value={problem} onChange={(event) => setProblem(event.target.value)} className="mt-1.5 min-h-28 w-full resize-y rounded-lg border border-(--color-border) bg-(--bg-page) p-3 text-sm text-(--color-text) outline-none focus:border-(--color-accent) focus:ring-2 focus:ring-(--color-accent)/10" placeholder="What is wrong today, and why does it matter?" />
              </label>
              <label className="block text-xs font-medium text-(--color-text-2)">
                Intended outcome <span className="font-normal text-(--color-text-subtle)">· optional, AI can draft this</span>
                <textarea value={outcome} onChange={(event) => setOutcome(event.target.value)} className="mt-1.5 min-h-28 w-full resize-y rounded-lg border border-(--color-border) bg-(--bg-page) p-3 text-sm text-(--color-text) outline-none focus:border-(--color-accent) focus:ring-2 focus:ring-(--color-accent)/10" placeholder="What observable state proves success?" />
              </label>
            </div>
            <div className="mt-4 flex flex-col gap-2 border-t border-(--color-border) pt-4 @sm/easd:flex-row @sm/easd:items-center @sm/easd:justify-between">
              <p className="max-w-xl text-[10px] leading-4 text-(--color-text-subtle)">
                The agent reads authorized project instructions, docs, code, and tests. Generated content stays a reviewable draft.
              </p>
              {generation.isPending ? (
                <span className="flex shrink-0 items-center gap-2">
                  <Button type="button" variant="outline" size="sm" onClick={() => generationAbort.current?.abort()}><X /> Cancel</Button>
                  <Button type="button" size="sm" disabled><Loader2 className="animate-spin" /> Generating…</Button>
                </span>
              ) : (
                <Button type="button" size="sm" disabled={!canGenerate} onClick={() => void generate('both')}><Sparkles /> Generate Outcome, Scope &amp; Proof</Button>
              )}
            </div>
            {!sessionId && <p className="mt-2 text-[10px] text-(--color-warning)">Open a Coding chat first so generation can use its authorized model and project context.</p>}
          </section>

          {generation.error && !generation.isPending && (
            <section role="alert" className="flex flex-col gap-3 rounded-xl border border-(--color-error)/35 bg-(--color-error-subtle) p-3 @sm/easd:flex-row @sm/easd:items-center @sm/easd:justify-between">
              <div><p className="text-xs font-semibold text-(--color-error)">Generation failed</p><p className="mt-1 text-[10px] text-(--color-text-muted)">{errorText(generation.error)}</p></div>
              <Button type="button" variant="outline" size="sm" onClick={() => void generate(lastGenerationTarget)}><RefreshCw /> Retry</Button>
            </section>
          )}

          {clarification && (
            <section className="rounded-2xl border border-(--color-warning)/35 bg-(--color-warning)/8 p-4">
              <div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 shrink-0 text-(--color-warning)" size={17} /><div><h3 className="text-sm font-semibold text-(--color-text)">Clarify intent before generation</h3><p className="mt-1 text-[11px] leading-4 text-(--color-text-muted)">{clarification.rationale}</p></div></div>
              <div className="mt-4 space-y-3">
                {clarification.questions.map((question) => (
                  <label key={question.id} className="block text-xs font-medium text-(--color-text-2)">
                    {question.question}
                    <span className="mt-0.5 block text-[10px] font-normal text-(--color-text-subtle)">{question.reason}</span>
                    <textarea value={clarificationAnswers[question.id] ?? ''} onChange={(event) => setClarificationAnswers((value) => ({ ...value, [question.id]: event.target.value }))} className="mt-1.5 min-h-20 w-full rounded-lg border border-(--color-border) bg-(--bg-page) p-3 text-xs text-(--color-text) outline-none focus:border-(--color-accent)" />
                  </label>
                ))}
              </div>
              <div className="mt-3 flex justify-end"><Button type="button" size="sm" disabled={!canGenerate || clarification.questions.some((item) => item.required && !(clarificationAnswers[item.id] ?? '').trim())} onClick={() => void generate(lastGenerationTarget, clarificationAnswers)}><Sparkles /> Generate with answers</Button></div>
            </section>
          )}

          {proposal && (
            <section className="overflow-hidden rounded-2xl border border-(--color-accent)/30 bg-(--bg-card)">
              <div className="border-b border-(--color-border) bg-(--color-accent)/7 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-(--color-accent)">Generated draft · review required</p><h3 className="mt-1 text-sm font-semibold text-(--color-text)">Outcome, Scope &amp; Proof proposal</h3></div><span className="rounded-full bg-(--bg-page) px-2.5 py-1 text-[10px] font-medium text-(--color-text-2)">{Math.round(proposal.confidence * 100)}% confidence</span></div>
                <p className="mt-2 text-[11px] leading-4 text-(--color-text-muted)">{proposal.rationale}</p>
              </div>
              <div className="grid divide-y divide-(--color-border) @4xl/easd:grid-cols-2 @4xl/easd:divide-x @4xl/easd:divide-y-0">
                {proposal.scope && (
                  <div className="p-4">
                    <div className="flex items-center justify-between gap-2"><h4 className="text-xs font-semibold text-(--color-text)">01–02 · Outcome &amp; Scope changes</h4><Button type="button" variant="ghost" size="sm" onClick={() => void generate('scope')}><RefreshCw /> Regenerate</Button></div>
                    <SpecificationDiff className="mt-3" fields={[
                      { label: 'Intended outcome', current: outcome, proposed: proposal.outcome ?? '' },
                      { label: 'Goals', current: goals, proposed: proposal.scope.goals.join('\n') },
                      { label: 'Non-goals', current: nonGoals, proposed: proposal.scope.non_goals.join('\n') },
                      { label: 'Source references', current: sourceRefs, proposed: proposal.scope.source_refs.join('\n') },
                      { label: 'Impact targets', current: impactTargets, proposed: formatImpactTargets(proposal.scope.impact_targets) },
                      { label: 'Constraints', current: constraints, proposed: formatConstraints(proposal.scope.constraints) },
                    ]} />
                    {replaceConfirmed.scope && <p className="mt-2 text-[10px] text-(--color-warning)">Outcome or Scope changed after generation. Click again to confirm replacing your edits.</p>}
                    <Button type="button" className="mt-3 w-full" variant={replaceConfirmed.scope ? 'destructive' : 'outline'} size="sm" onClick={applyScope}>{replaceConfirmed.scope ? 'Replace edited Outcome & Scope' : 'Apply Outcome & Scope draft'}</Button>
                  </div>
                )}
                {proposal.proof && (
                  <div className="p-4">
                    <div className="flex items-center justify-between gap-2"><h4 className="text-xs font-semibold text-(--color-text)">03 · Proof changes</h4><Button type="button" variant="ghost" size="sm" onClick={() => void generate('proof')}><RefreshCw /> Regenerate</Button></div>
                    <SpecificationDiff className="mt-3" fields={[
                      { label: 'Acceptance criteria and evidence policy', current: formatCriteria(currentCriteria()), proposed: formatCriteria(proposal.proof.criteria) },
                      { label: 'Risk tier', current: RISK_LABELS[riskTier], proposed: RISK_LABELS[proposal.proof.risk_tier] },
                      { label: 'Driven flow', current: `${deliveryMode} — ${deliveryRationale}`, proposed: `${deliveryFlowForProof(proposal.proof).mode} — ${deliveryFlowForProof(proposal.proof).rationale}` },
                      { label: 'Verification commands', current: verificationCommands, proposed: proposal.proof.verification_commands.join('\n') },
                      { label: 'Independent review', current: riskTier === 'cross_layer' || riskTier === 'critical' ? 'Required' : 'Not required', proposed: proposal.proof.independent_review_required ? 'Required' : 'Not required' },
                    ]} />
                    {proposal.proof.independent_review_required && <p className="mt-2 text-[10px] font-medium text-(--color-warning)">Independent review required</p>}
                    {replaceConfirmed.proof && <p className="mt-2 text-[10px] text-(--color-warning)">Proof changed after generation. Click again to confirm replacing your edits.</p>}
                    <Button type="button" className="mt-3 w-full" variant={replaceConfirmed.proof ? 'destructive' : 'outline'} size="sm" onClick={applyProof}>{replaceConfirmed.proof ? 'Replace edited Proof' : 'Apply Proof draft'}</Button>
                  </div>
                )}
              </div>
              <details className="border-t border-(--color-border) px-4 py-3 text-[10px] text-(--color-text-muted)"><summary className="cursor-pointer font-medium text-(--color-text-2)">Provenance · {proposal.provenance.length} context sources</summary><div className="mt-2 grid gap-1 @3xl/easd:grid-cols-2">{proposal.provenance.filter((item) => item.used_for.length).map((item) => <p key={`${item.repository}:${item.path}`} className="truncate font-mono" title={`${item.repository}:${item.path}`}>{item.repository}:{item.path} · {item.used_for.join('/')}{item.truncated ? ' · truncated' : ''}</p>)}</div></details>
            </section>
          )}

          <section className="rounded-2xl border border-(--color-border) bg-(--bg-card) p-4">
            <div className="mb-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-(--color-accent)">02 · Scope</p>
              <h3 className="mt-1 text-sm font-semibold text-(--color-text)">Set boundaries and source context</h3>
            </div>
            <div className="grid gap-4 @3xl/easd:grid-cols-2">
              <label className="block text-xs font-medium text-(--color-text-2)">
                Goals <span className="font-normal text-(--color-text-subtle)">· one per line</span>
                <textarea value={goals} onChange={(event) => setGoals(event.target.value)} className="mt-1.5 min-h-24 w-full resize-y rounded-lg border border-(--color-border) bg-(--bg-page) p-3 text-xs text-(--color-text) outline-none focus:border-(--color-accent)" placeholder="What must this run deliver?" />
              </label>
              <label className="block text-xs font-medium text-(--color-text-2)">
                Non-goals <span className="font-normal text-(--color-text-subtle)">· one per line</span>
                <textarea value={nonGoals} onChange={(event) => setNonGoals(event.target.value)} className="mt-1.5 min-h-24 w-full resize-y rounded-lg border border-(--color-border) bg-(--bg-page) p-3 text-xs text-(--color-text) outline-none focus:border-(--color-accent)" placeholder="What should agents leave unchanged?" />
              </label>
              <label className="block text-xs font-medium text-(--color-text-2) @3xl/easd:col-span-2">
                Source references <span className="font-normal text-(--color-text-subtle)">· one per line</span>
                <textarea value={sourceRefs} onChange={(event) => setSourceRefs(event.target.value)} className="mt-1.5 min-h-20 w-full resize-y rounded-lg border border-(--color-border) bg-(--bg-page) p-3 font-mono text-xs text-(--color-text) outline-none focus:border-(--color-accent)" placeholder="documents/plans/feature.md" />
              </label>
              <label className="block text-xs font-medium text-(--color-text-2) @3xl/easd:col-span-2">
                Affected repositories, files, and modules <span className="font-normal text-(--color-text-subtle)">· repository:path :: module :: reason</span>
                <textarea value={impactTargets} onChange={(event) => setImpactTargets(event.target.value)} className="mt-1.5 min-h-24 w-full resize-y rounded-lg border border-(--color-border) bg-(--bg-page) p-3 font-mono text-[11px] text-(--color-text) outline-none focus:border-(--color-accent)" placeholder="backend:app/api/routes.py :: API :: Adds the public endpoint" />
              </label>
              <label className="block text-xs font-medium text-(--color-text-2) @3xl/easd:col-span-2">
                Constraints and boundaries <span className="font-normal text-(--color-text-subtle)">· [kind] statement :: sources</span>
                <textarea value={constraints} onChange={(event) => setConstraints(event.target.value)} className="mt-1.5 min-h-24 w-full resize-y rounded-lg border border-(--color-border) bg-(--bg-page) p-3 text-xs text-(--color-text) outline-none focus:border-(--color-accent)" placeholder="[compatibility] Preserve the existing response shape :: documents/reference/http-api.md" />
              </label>
            </div>
          </section>

          <section className="rounded-2xl border border-(--color-border) bg-(--bg-card) p-4">
            <div className="mb-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-(--color-accent)">03 · Proof</p>
              <h3 className="mt-1 text-sm font-semibold text-(--color-text)">Define observable acceptance</h3>
            </div>
            <div className="grid gap-4 @3xl/easd:grid-cols-[minmax(0,1fr)_14rem]">
              <div className="block text-xs font-medium text-(--color-text-2)">
                <label htmlFor="easd-acceptance-criteria">Acceptance criteria <span className="font-normal text-(--color-text-subtle)">· one per line</span></label>
                <textarea id="easd-acceptance-criteria" value={criteria} onChange={(event) => { setCriteria(event.target.value); setGeneratedCriteria(null) }} className="mt-1.5 min-h-32 w-full resize-y rounded-lg border border-(--color-border) bg-(--bg-page) p-3 text-sm text-(--color-text) outline-none focus:border-(--color-accent) focus:ring-2 focus:ring-(--color-accent)/10" placeholder={'The API rejects stale revisions\nEvery required criterion has machine evidence'} />
                <span className="mt-1 block text-[10px] font-normal text-(--color-text-subtle)">{criterionLines.length} acceptance {criterionLines.length === 1 ? 'criterion' : 'criteria'}</span>
                {generatedCriteria && generatedCriteria.map((item) => item.statement).join('\n') === criterionLines.join('\n') && (
                  <div className="mt-3 space-y-2 rounded-lg border border-(--color-border) bg-(--bg-key)/35 p-2.5">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">Evidence policy per AC</p>
                    {generatedCriteria.map((item, index) => (
                      <div key={item.id} className="grid gap-2 rounded-lg bg-(--bg-card) p-2 @2xl/easd:grid-cols-[3rem_minmax(0,1fr)_auto_5rem] @2xl/easd:items-center">
                        <span className="font-mono text-[10px] font-semibold text-(--color-accent)">{item.id}</span>
                        <input aria-label={`${item.id} allowed evidence kinds`} value={item.evidence_policy.allowed_kinds.join(', ')} onChange={(event) => { const allowed = event.target.value.split(',').map((value) => value.trim()).filter((value): value is EasdEvidenceKind => ['machine', 'review', 'manual', 'waiver'].includes(value)); if (allowed.length) setGeneratedCriteria((items) => items?.map((entry, itemIndex) => itemIndex === index ? { ...entry, evidence_policy: { ...entry.evidence_policy, allowed_kinds: [...new Set(allowed)] } } : entry) ?? null) }} className="h-8 min-w-0 rounded-md border border-(--color-border) bg-(--bg-page) px-2 text-[10px] text-(--color-text)" />
                        <label className="flex items-center gap-1.5 text-[10px] font-normal text-(--color-text-muted)"><input type="checkbox" checked={item.evidence_policy.machine_required} onChange={(event) => setGeneratedCriteria((items) => items?.map((entry, itemIndex) => itemIndex === index ? { ...entry, evidence_policy: { ...entry.evidence_policy, machine_required: event.target.checked } } : entry) ?? null)} /> machine</label>
                        <input aria-label={`${item.id} minimum passes`} type="number" min={1} max={20} value={item.evidence_policy.minimum_passes} onChange={(event) => setGeneratedCriteria((items) => items?.map((entry, itemIndex) => itemIndex === index ? { ...entry, evidence_policy: { ...entry.evidence_policy, minimum_passes: Math.min(20, Math.max(1, Number(event.target.value) || 1)) } } : entry) ?? null)} className="h-8 rounded-md border border-(--color-border) bg-(--bg-page) px-2 text-[10px] text-(--color-text)" />
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <label className="block text-xs font-medium text-(--color-text-2)">
                Risk tier
                <SelectControl
                  value={riskTier}
                  onValueChange={(value) => setRiskTier(value as EasdRiskTier)}
                  options={Object.entries(RISK_LABELS).map(([value, label]) => ({ value, label }))}
                  ariaLabel="Risk tier"
                  className="mt-1.5 h-10"
                />
                <p className="mt-2 rounded-lg bg-(--bg-key)/60 p-2.5 text-[10px] leading-4 text-(--color-text-subtle)">Cross-layer and critical runs require independent review before convergence.</p>
              </label>
              <div className="rounded-xl border border-(--color-border) bg-(--bg-key)/35 p-3 text-xs text-(--color-text-2) @3xl/easd:col-span-2">
                <div className="flex flex-col gap-3 @2xl/easd:flex-row @2xl/easd:items-start">
                  <label className="min-w-48 font-medium">
                    Suggested driven flow
                    <SelectControl
                      value={deliveryMode}
                      onValueChange={(value) => setDeliveryMode(value as EasdDeliveryMode)}
                      options={[
                        { value: 'direct', label: 'Direct · skip Plan' },
                        { value: 'planned', label: 'Planned · approve Plan' },
                      ]}
                      ariaLabel="Suggested driven flow"
                      className="mt-1.5 h-10"
                    />
                  </label>
                  <label className="min-w-0 flex-1 font-medium">
                    Flow rationale
                    <textarea value={deliveryRationale} onChange={(event) => { setDeliveryRationale(event.target.value); setDeliveryConfidence(1) }} className="mt-1.5 min-h-20 w-full resize-y rounded-lg border border-(--color-border) bg-(--bg-page) p-2.5 text-xs font-normal text-(--color-text) outline-none focus:border-(--color-accent)" />
                  </label>
                </div>
                <p className="mt-2 text-[10px] leading-4 text-(--color-text-subtle)">{deliveryMode === 'direct' ? 'Approving this Spec skips Plan, but Review → Verify → Converge remain mandatory. Server validation rejects direct for multi-repo, cross-layer, security, migration/operational, architecture, or compatibility boundaries.' : 'Approving this Spec keeps the explicit Run plan → Approve plan gate.'}{deliveryRequiredBy.length ? ` Required by: ${deliveryRequiredBy.join(', ')}.` : ''}</p>
              </div>
              <label className="block text-xs font-medium text-(--color-text-2) @3xl/easd:col-span-2">
                Planned verification commands <span className="font-normal text-(--color-text-subtle)">· one per line</span>
                <textarea value={verificationCommands} onChange={(event) => setVerificationCommands(event.target.value)} className="mt-1.5 min-h-20 w-full resize-y rounded-lg border border-(--color-border) bg-(--bg-page) p-3 font-mono text-[11px] text-(--color-text) outline-none focus:border-(--color-accent)" placeholder="uv run pytest --no-cov -q tests/api/routes/test_feature.py" />
              </label>
            </div>
          </section>
          {mutation.error && <p role="alert" className="text-xs text-(--color-error)">{errorText(mutation.error)}</p>}
        </div>
      </div>
      <footer className="flex shrink-0 flex-col gap-2 border-t border-(--color-border) bg-(--bg-card)/70 p-3 @sm/easd:flex-row @sm/easd:items-center @sm/easd:justify-between @xl/easd:px-5">
        <p className="text-[10px] text-(--color-text-subtle)">
          {canSubmit ? `${criterionLines.length} criteria ready for review` : 'Title, problem, outcome, and one criterion are required'}
        </p>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>
          <Button type="button" disabled={!canSubmit || mutation.isPending} onClick={() => void submit()}>
            {mutation.isPending && <Loader2 className="animate-spin" aria-hidden />}
            Save draft revision
          </Button>
        </div>
      </footer>
    </div>
  )
}

function RunStatus({ status }: { status: EasdRun['status'] }) {
  return <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-medium capitalize', statusTone(status))}>{status.replace('_', ' ')}</span>
}

function RunCard({ run, onOpen }: { run: EasdRun; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen} className="group w-full rounded-xl border border-(--color-border) bg-(--bg-card) p-3 text-left transition-[border-color,transform,box-shadow] hover:-translate-y-px hover:border-(--color-border-strong) hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)/40">
      <div className="flex items-start justify-between gap-2">
        <RunStatus status={run.status} />
        <span className={cn('text-[10px] font-medium', riskTone(run.risk_tier))}>{RISK_LABELS[run.risk_tier]}</span>
      </div>
      <h3 className="mt-3 line-clamp-2 text-sm font-semibold leading-5 text-(--color-text)">{run.title}</h3>
      <div className="mt-3 flex items-center justify-between gap-2 text-[10px] text-(--color-text-subtle)">
        <span className="flex min-w-0 items-center gap-1"><FolderGit2 size={11} /><span className="truncate">{workspaceName(run.workspace)}</span></span>
        <span className="shrink-0">{relativeTime(run.updated_at)}</span>
      </div>
    </button>
  )
}

function RunsOverview({
  runs,
  setup,
  view,
  search,
  onSearch,
  onView,
  onOpen,
  onCreate,
}: {
  runs: EasdRun[]
  setup: EasdSetupResponse
  view: RunsView
  search: string
  onSearch: (value: string) => void
  onView: (view: RunsView) => void
  onOpen: (runId: string) => void
  onCreate: () => void
}) {
  const normalizedSearch = search.trim().toLowerCase()
  const filtered = normalizedSearch
    ? runs.filter((run) => [run.title, run.status, run.risk_tier, run.workspace].some((value) => value.toLowerCase().includes(normalizedSearch)))
    : runs
  const activeCount = runs.filter((run) => run.status === 'active' || run.status === 'reviewing' || run.status === 'verifying').length
  const convergedCount = runs.filter((run) => run.status === 'converged').length

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 p-3 @xl/easd:p-5">
        <section className="overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card)">
          <div className="flex flex-wrap items-start justify-between gap-3 px-4 pb-3 pt-4">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-(--color-text)">Specification runs</h2>
                <span className="rounded-full bg-(--color-success-subtle) px-2 py-0.5 text-[9px] font-semibold text-(--color-success)">Ready</span>
              </div>
              <p className="mt-1 text-[11px] leading-4 text-(--color-text-muted)">Track intent, agent work, and proof across this {setup.scope}.</p>
            </div>
            <p className="flex items-center gap-1.5 rounded-full border border-(--color-border) bg-(--bg-page) px-2.5 py-1 text-[10px] text-(--color-text-muted)">
              <FolderGit2 size={11} /> {setup.repository_count} {setup.repository_count === 1 ? 'repository' : 'repositories'}
            </p>
          </div>
          <div className="grid grid-cols-3 border-t border-(--color-border) bg-(--bg-page)/45">
            <div className="px-4 py-2.5">
              <p className="text-base font-semibold tabular-nums text-(--color-text)">{runs.length}</p>
              <p className="text-[9px] font-medium uppercase tracking-wide text-(--color-text-subtle)">Total</p>
            </div>
            <div className="border-x border-(--color-border) px-4 py-2.5">
              <p className="text-base font-semibold tabular-nums text-(--color-accent)">{activeCount}</p>
              <p className="text-[9px] font-medium uppercase tracking-wide text-(--color-text-subtle)">In progress</p>
            </div>
            <div className="px-4 py-2.5">
              <p className="text-base font-semibold tabular-nums text-(--color-success)">{convergedCount}</p>
              <p className="text-[9px] font-medium uppercase tracking-wide text-(--color-text-subtle)">Converged</p>
            </div>
          </div>
        </section>

        <div className="flex flex-col gap-2 @2xl/easd:flex-row @2xl/easd:items-center @2xl/easd:justify-between">
          <div className="relative min-w-0 flex-1 sm:max-w-sm">
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-(--color-text-subtle)" />
            <input value={search} onChange={(event) => onSearch(event.target.value)} className="h-9 w-full rounded-lg border border-(--color-border) bg-(--bg-card) pl-8 pr-3 text-xs text-(--color-text) outline-none focus:border-(--color-accent) focus:ring-2 focus:ring-(--color-accent)/10" placeholder="Search runs, status, or repository" />
          </div>
          <SegmentedControl className="self-end @2xl/easd:self-auto" options={RUN_VIEW_OPTIONS} value={view} onChange={onView} layoutId="easd-runs-view" ariaLabel="Runs view" />
        </div>

        {runs.length === 0 ? (
          <section className="flex min-h-72 flex-col items-center justify-center rounded-2xl border border-dashed border-(--color-border) bg-(--bg-card)/50 p-8 text-center">
            <span className="flex size-12 items-center justify-center rounded-2xl bg-(--color-accent)/10 text-(--color-accent)"><Route size={22} /></span>
            <h2 className="mt-4 text-sm font-semibold text-(--color-text)">Your repositories are ready</h2>
            <p className="mt-1 max-w-sm text-xs leading-5 text-(--color-text-muted)">Create the first EASD run to turn an accepted specification into accountable missions, evidence, and convergence.</p>
            <Button type="button" className="mt-4" onClick={onCreate}><Plus /> Create first run</Button>
          </section>
        ) : filtered.length === 0 ? (
          <p className="rounded-xl border border-dashed border-(--color-border) p-6 text-center text-xs text-(--color-text-muted)">No runs match “{search}”.</p>
        ) : view === 'board' ? (
          <div className="grid gap-3 @4xl/easd:grid-cols-2 @7xl/easd:grid-cols-4">
              {BOARD_COLUMNS.map((column) => {
                const columnRuns = filtered.filter((run) => column.statuses.includes(run.status))
                return (
                  <section key={column.id} className="overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-key)/35">
                    <div className="flex items-start justify-between gap-2 border-b border-(--color-border) px-3 py-2.5">
                      <div className="flex min-w-0 items-start gap-2">
                        <span className={cn(
                          'mt-1 size-2 shrink-0 rounded-full',
                          column.id === 'execution' && 'bg-(--color-accent)',
                          column.id === 'done' && 'bg-(--color-success)',
                          column.id === 'attention' && 'bg-(--color-error)',
                          column.id === 'planning' && 'bg-(--color-text-subtle)',
                        )} />
                        <div>
                          <h2 className="text-xs font-semibold text-(--color-text)">{column.title}</h2>
                        <p className="mt-0.5 text-[10px] text-(--color-text-subtle)">{column.description}</p>
                        </div>
                      </div>
                      <span className="rounded-full bg-(--bg-card) px-2 py-0.5 text-[10px] text-(--color-text-muted)">{columnRuns.length}</span>
                    </div>
                    {columnRuns.length > 0 && <div className="space-y-2 p-2.5">{columnRuns.map((run) => <RunCard key={run.id} run={run} onOpen={() => onOpen(run.id)} />)}</div>}
                  </section>
                )
              })}
          </div>
        ) : view === 'table' ? (
          <div className="overflow-x-auto rounded-xl border border-(--color-border) bg-(--bg-card)">
            <table className="w-full border-collapse text-left">
              <thead className="border-b border-(--color-border) bg-(--bg-key)/50 text-[10px] uppercase tracking-wide text-(--color-text-subtle)">
                <tr><th className="px-3 py-2.5 font-semibold">Run</th><th className="hidden px-3 py-2.5 font-semibold @2xl/easd:table-cell">Repository</th><th className="px-3 py-2.5 font-semibold">Status</th><th className="hidden px-3 py-2.5 text-right font-semibold @sm/easd:table-cell">Updated</th></tr>
              </thead>
              <tbody className="divide-y divide-(--color-border)">
                {filtered.map((run) => (
                  <tr key={run.id} className="text-xs transition-colors hover:bg-(--bg-key)/45">
                    <td className="max-w-xs p-0 font-medium text-(--color-text)"><button type="button" onClick={() => onOpen(run.id)} className="w-full px-3 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-(--focus-ring)/40"><span className="line-clamp-1">{run.title}</span><span className={cn('mt-0.5 block text-[10px] font-normal', riskTone(run.risk_tier))}>{workspaceName(run.workspace)} · {RISK_LABELS[run.risk_tier]}</span></button></td>
                    <td className="hidden px-3 py-3 text-(--color-text-muted) @2xl/easd:table-cell">{workspaceName(run.workspace)}</td>
                    <td className="px-3 py-3"><RunStatus status={run.status} /></td>
                    <td className="hidden px-3 py-3 text-right text-(--color-text-subtle) @sm/easd:table-cell">{relativeTime(run.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="space-y-2">
            {filtered.map((run) => (
              <button key={run.id} type="button" onClick={() => onOpen(run.id)} className="group grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-(--color-border) bg-(--bg-card) px-3 py-3 text-left transition-[border-color,background-color] hover:border-(--color-border-strong) hover:bg-(--bg-key)/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)/40">
                <span className={cn('h-9 w-1 rounded-full', run.status === 'converged' ? 'bg-(--color-success)' : run.status === 'active' || run.status === 'reviewing' || run.status === 'verifying' ? 'bg-(--color-accent)' : run.status === 'failed' ? 'bg-(--color-error)' : 'bg-(--color-text-subtle)')} />
                <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium text-(--color-text)">{run.title}</p><p className="mt-1 truncate text-[10px] text-(--color-text-subtle)">{workspaceName(run.workspace)} · {RISK_LABELS[run.risk_tier]} · {relativeTime(run.updated_at)}</p></div>
                <span className="flex items-center gap-2"><RunStatus status={run.status} /><ArrowRight size={13} className="text-(--color-text-subtle) transition-transform group-hover:translate-x-0.5" /></span>
              </button>
            ))}
          </div>
        )}

        {setup.repository_count > 1 && <p className="text-center text-[10px] text-(--color-text-subtle)">Showing runs across {setup.repository_count} initialized project repositories.</p>}
      </div>
    </div>
  )
}

function RunDetail({
  runId,
  setup,
  onBack,
  onRunInChat,
}: {
  runId: string
  setup: EasdSetupResponse
  onBack: () => void
  onRunInChat?: (request: EasdRunChatRequest) => void
}) {
  const detailQuery = useEasdRunQuery(runId)
  const detail = detailQuery.data
  const [showChatPicker, setShowChatPicker] = useState(false)
  const [creatingChat, setCreatingChat] = useState(false)
  const [chatSearch, setChatSearch] = useState('')
  const [chatActionError, setChatActionError] = useState<string | null>(null)
  const [editingDraft, setEditingDraft] = useState(false)
  const [confirmingAction, setConfirmingAction] = useState<EasdConfirmableAction | null>(null)
  const draft = detail
    ? [...detail.revisions]
      .filter((item) => item.status === 'draft')
      .sort((left, right) => right.version - left.version)[0] ?? null
    : null
  const planDraft = detail
    ? [...detail.plan_revisions]
      .filter((item) => item.status === 'draft')
      .sort((left, right) => right.version - left.version)[0] ?? null
    : null
  const displayedPlan = planDraft ?? detail?.active_plan ?? null
  const deliveryMode = detail?.active_spec?.spec.delivery_flow?.mode ?? 'planned'
  const ownerDataDirectory = setup.repositories.find(
    (repository) => repository.path === detail?.run.workspace,
  )?.data_directory ?? 'documents/easd'
  const agentAuthoring = draft?.authoring && 'mode' in draft.authoring
    ? draft.authoring
    : null
  const acceptMutation = useAcceptEasdRevisionMutation(runId, draft?.id ?? '', draft?.content_hash ?? '')
  const acceptPlanMutation = useAcceptEasdPlanRevisionMutation(runId, planDraft?.id ?? '', planDraft?.content_hash ?? '')
  const startInChatMutation = useStartEasdRunInChatMutation(runId)
  const startAuthoringMutation = useStartEasdSpecAuthoringMutation(runId)
  const startPlanningMutation = useStartEasdPlanningMutation(runId)
  const retryAuthoringMutation = useRetryEasdSpecAuthoringMutation(runId)
  const retryPlanningMutation = useRetryEasdPlanningMutation(runId)
  const startReviewMutation = useStartEasdReviewMutation(runId)
  const startVerificationMutation = useStartEasdVerificationMutation(runId)
  const convergeMutation = useConvergeEasdRunMutation(runId)
  const evidenceMutation = useAddEasdEvidenceMutation(runId)
  const deviationMutation = useAddEasdDeviationMutation(runId)
  const [evidenceCriterion, setEvidenceCriterion] = useState('')
  const [evidenceSummary, setEvidenceSummary] = useState('')
  const [evidenceKind, setEvidenceKind] = useState<EasdAppendableEvidenceKind>('manual')
  const [evidenceResult, setEvidenceResult] = useState<EasdEvidenceResult>('passed')
  const [deviationCriterion, setDeviationCriterion] = useState('')
  const [deviationDescription, setDeviationDescription] = useState('')
  const projectSessionsQuery = useProjectSessionsQuery(
    detail?.run.project_id ?? '',
    showChatPicker && Boolean(detail?.run.project_id),
  )
  const workspaceSessionsQuery = useCodingWorkspaceSessionsQuery(
    detail?.run.workspace ?? '',
    showChatPicker && Boolean(detail && !detail.run.project_id),
  )
  const chatSessions = useMemo(() => {
    const pages = detail?.run.project_id
      ? projectSessionsQuery.data?.pages
      : workspaceSessionsQuery.data?.pages
    const rows = pages?.flatMap((page) => page.data) ?? []
    return [...new Map(rows.map((session) => [session.id, session])).values()]
  }, [detail?.run.project_id, projectSessionsQuery.data?.pages, workspaceSessionsQuery.data?.pages])
  const activeSessionsQuery = detail?.run.project_id
    ? projectSessionsQuery
    : workspaceSessionsQuery
  const filteredChatSessions = useMemo(() => {
    const term = chatSearch.trim().toLowerCase()
    if (!term) return chatSessions
    return chatSessions.filter((session) => (
      (session.title || 'Untitled Coding chat').toLowerCase().includes(term)
    ))
  }, [chatSearch, chatSessions])
  const convergenceReasons = convergeMutation.error instanceof EasdConvergenceApiError
    ? convergeMutation.error.reasons
    : []
  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const item of detail?.criteria ?? []) counts[item.status] = (counts[item.status] ?? 0) + 1
    return counts
  }, [detail?.criteria])
  const acceptedCriteria = (statusCounts.passed ?? 0) + (statusCounts.waived ?? 0)
  const acceptanceProgress = detail?.criteria.length
    ? Math.round((acceptedCriteria / detail.criteria.length) * 100)
    : 0
  const actionIsBlocked = (actionId: EasdActionId) => (
    detail?.action_rail?.actions.find((action) => action.id === actionId)?.state === 'blocked'
  )
  const confirmationBusy = confirmingAction === 'approve_specification'
    ? acceptMutation.isPending
    : confirmingAction === 'approve_plan'
      ? acceptPlanMutation.isPending
      : confirmingAction === 'converge'
        ? convergeMutation.isPending
        : false
  const confirmationError = confirmingAction === 'approve_specification'
    ? errorText(acceptMutation.error)
    : confirmingAction === 'approve_plan'
      ? errorText(acceptPlanMutation.error)
      : confirmingAction === 'converge'
        ? errorText(convergeMutation.error)
        : null

  const confirmLifecycleAction = async () => {
    try {
      if (confirmingAction === 'approve_specification') {
        await acceptMutation.mutateAsync()
      } else if (confirmingAction === 'approve_plan') {
        await acceptPlanMutation.mutateAsync()
      } else if (confirmingAction === 'converge') {
        await convergeMutation.mutateAsync()
      } else {
        return
      }
      setConfirmingAction(null)
    } catch {
      // The mutation exposes its error in the Run header while the dialog stays open.
    }
  }

  const addEvidence = async () => {
    if (!detail?.active_spec || !evidenceCriterion || !evidenceSummary.trim()) return
    await evidenceMutation.mutateAsync({
      spec_hash: detail.active_spec.content_hash,
      criterion_ids: [evidenceCriterion],
      producer: 'human',
      kind: evidenceKind,
      result: evidenceKind === 'waiver' ? 'waived' : evidenceResult,
      summary: evidenceSummary.trim(),
    })
    setEvidenceSummary('')
  }

  const addDeviation = async () => {
    if (!deviationDescription.trim()) return
    await deviationMutation.mutateAsync({
      description: deviationDescription.trim(),
      criterion_id: deviationCriterion || null,
    })
    setDeviationDescription('')
  }

  const handoffToChat = async (
    sessionId: string,
    phase: EasdRunChatRequest['phase'],
    autoSend: boolean,
  ): Promise<boolean> => {
    if (!detail || !onRunInChat) return false
    setChatActionError(null)
    try {
      if (phase === 'authoring' && detail.run.status === 'intent') {
        await startAuthoringMutation.mutateAsync(sessionId)
      }
      if (
        autoSend
        && phase === 'authoring'
        && (detail.run.status === 'authoring' || detail.run.status === 'draft')
      ) {
        await retryAuthoringMutation.mutateAsync(sessionId)
      }
      if (phase === 'planning' && detail.run.status === 'accepted') {
        await startPlanningMutation.mutateAsync(sessionId)
      }
      if (
        autoSend
        && phase === 'planning'
        && (detail.run.status === 'planning' || detail.run.status === 'plan_review')
      ) {
        await retryPlanningMutation.mutateAsync(sessionId)
      }
      if (phase === 'implementation' && (detail.run.status === 'planned' || (detail.run.status === 'accepted' && deliveryMode === 'direct'))) {
        await startInChatMutation.mutateAsync(sessionId)
      }
      if (phase === 'review' && detail.run.status === 'active') {
        await startReviewMutation.mutateAsync(sessionId)
      }
      if (phase === 'verification' && detail.run.status === 'reviewing') {
        await startVerificationMutation.mutateAsync(sessionId)
      }
      const linkedDetail = detail.run.session_id
        ? detail
        : { ...detail, run: { ...detail.run, session_id: sessionId } }
      onRunInChat({
        sessionId,
        workspace: detail.run.workspace,
        projectId: detail.run.project_id,
        prompt: detail.run.status === 'converged'
          ? null
          : phase === 'authoring'
          ? autoSend && ['intent', 'authoring', 'draft'].includes(detail.run.status)
            ? specificationAuthoringPrompt(linkedDetail)
            : null
          : phase === 'planning'
            ? autoSend && ['accepted', 'planning', 'plan_review'].includes(detail.run.status)
              ? planningPrompt(linkedDetail)
              : null
            : phase === 'implementation'
              ? implementationPrompt(linkedDetail, detail.run.status === 'active')
              : phase === 'review'
                ? reviewPrompt(linkedDetail)
                : verificationPrompt(linkedDetail),
        autoSend,
        phase,
      })
      setShowChatPicker(false)
      return true
    } catch (error) {
      setChatActionError(errorText(error) ?? 'Could not start this EASD run in chat.')
      return false
    }
  }

  const openRunChat = async (
    phase: EasdRunChatRequest['phase'],
    autoSend: boolean,
  ) => {
    if (!detail?.run.session_id) return
    await handoffToChat(detail.run.session_id, phase, autoSend)
  }

  const createAndRunInChat = async () => {
    if (!detail) return
    setCreatingChat(true)
    setChatActionError(null)
    try {
      const session = await resolveTeamSession({
        mode: 'coding',
        workspace: detail.run.project_id ? undefined : detail.run.workspace,
        project_id: detail.run.project_id,
        create: true,
      })
      await handoffToChat(
        session.id,
        detail.run.status === 'intent'
          ? 'authoring'
          : detail.run.status === 'accepted'
            ? deliveryMode === 'direct' ? 'implementation' : 'planning'
            : 'implementation',
        true,
      )
    } catch (error) {
      setChatActionError(errorText(error) ?? 'Could not create a Coding chat.')
    } finally {
      setCreatingChat(false)
    }
  }

  if (detailQuery.isLoading) {
    return <div className="flex h-full items-center justify-center"><Loader2 className="animate-spin text-(--color-accent)" /></div>
  }
  if (!detail) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <AlertTriangle className="text-(--color-error)" />
        <p className="text-sm font-medium text-(--color-text)">Could not load this specification run</p>
        <p className="text-xs text-(--color-error)">{errorText(detailQuery.error)}</p>
        <div className="flex gap-2"><Button type="button" variant="outline" onClick={onBack}>Back</Button><Button type="button" onClick={() => void detailQuery.refetch()}>Try again</Button></div>
      </div>
    )
  }
  if (editingDraft && draft) {
    return (
      <SpecificationEditorForm
        setup={setup}
        runId={runId}
        initialSpecification={draft.spec}
        projectId={detail.run.project_id}
        sessionId={detail.run.session_id}
        initialWorkspace={detail.run.workspace}
        onSaved={() => {
          setEditingDraft(false)
          void detailQuery.refetch()
        }}
        onCancel={() => setEditingDraft(false)}
      />
    )
  }

  return (
    <div className="@container/easd flex h-full min-h-0 flex-col bg-(--bg-page)">
      <EasdActionConfirmationDialog
        action={confirmingAction}
        detail={detail}
        draft={draft}
        planDraft={planDraft}
        busy={confirmationBusy}
        error={confirmationError}
        onCancel={() => setConfirmingAction(null)}
        onConfirm={() => void confirmLifecycleAction()}
      />
      <header className="shrink-0 border-b border-(--color-border) bg-(--bg-card)/45">
        <div className="flex min-h-16 items-center gap-3 px-3 @xl/easd:px-4">
          <Button type="button" variant="ghost" size="icon-sm" onClick={onBack} aria-label="Back to runs"><ChevronLeft /></Button>
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex items-center gap-2"><span className="text-[9px] font-semibold uppercase tracking-[0.14em] text-(--color-accent)">Specification run</span><span className="text-[9px] text-(--color-text-subtle)">· {workspaceName(detail.run.workspace)}</span></div>
            <h1 className="truncate text-sm font-semibold text-(--color-text)">{detail.run.title}</h1>
            <p className="mt-0.5 truncate text-[10px] text-(--color-text-subtle)">{RISK_LABELS[detail.run.risk_tier]} risk · {ownerDataDirectory}/runs{detail.run.store_generation ? ` · repo gen ${detail.run.store_generation}` : ''}</p>
          </div>
          <RunStatus status={detail.run.status} />
          {detail.run.status === 'converged' && detail.run.session_id && onRunInChat && (
            <Button type="button" variant="outline" size="sm" onClick={() => void openRunChat('implementation', false)}><MessageSquareText /> View chat</Button>
          )}
        </div>
        <EasdActionRail
          status={detail.run.status}
          deliveryMode={deliveryMode}
          rail={detail.action_rail}
          actions={<>
            {detail.run.status === 'intent' && (
              detail.run.session_id && onRunInChat
                ? <Button type="button" size="sm" disabled={startAuthoringMutation.isPending} onClick={() => void openRunChat('authoring', true)}><Sparkles /> Draft specification in chat</Button>
                : onRunInChat
                  ? <Button type="button" size="sm" onClick={() => setShowChatPicker((value) => !value)}><MessageSquareText /> Choose drafting chat</Button>
                  : null
            )}
            {detail.run.status === 'authoring' && detail.run.session_id && onRunInChat && <span className="flex flex-wrap items-center justify-end gap-2"><Button type="button" variant="outline" size="sm" onClick={() => void openRunChat('authoring', false)}><MessageSquareText /> Open drafting chat</Button><Button type="button" size="sm" disabled={retryAuthoringMutation.isPending} onClick={() => void openRunChat('authoring', true)}><RefreshCw /> Retry drafting</Button></span>}
            {detail.run.status === 'draft' && draft && <span className="flex flex-wrap items-center justify-end gap-2">{detail.run.session_id && onRunInChat && <Button type="button" variant="outline" size="sm" disabled={retryAuthoringMutation.isPending} onClick={() => void openRunChat('authoring', true)}><RefreshCw /> Redraft in chat</Button>}<Button type="button" variant="outline" size="sm" onClick={() => setEditingDraft(true)}>Edit specification</Button><Button type="button" size="sm" disabled={acceptMutation.isPending} onClick={() => setConfirmingAction('approve_specification')}><FileCheck2 /> Approve specification</Button></span>}
            {detail.run.status === 'accepted' && (
              detail.run.session_id && onRunInChat
                ? deliveryMode === 'direct'
                  ? <Button type="button" size="sm" disabled={startInChatMutation.isPending} onClick={() => void openRunChat('implementation', true)}><Play /> Run implementation in chat</Button>
                  : <Button type="button" size="sm" disabled={startPlanningMutation.isPending} onClick={() => void openRunChat('planning', true)}><Play /> Run plan in chat</Button>
                : onRunInChat
                  ? <Button type="button" size="sm" onClick={() => setShowChatPicker((value) => !value)}><MessageSquareText /> Choose {deliveryMode === 'direct' ? 'implementation' : 'planning'} chat</Button>
                  : null
            )}
            {detail.run.status === 'planning' && detail.run.session_id && onRunInChat && <span className="flex flex-wrap items-center justify-end gap-2"><Button type="button" variant="outline" size="sm" onClick={() => void openRunChat('planning', false)}><MessageSquareText /> Open planning chat</Button><Button type="button" size="sm" disabled={retryPlanningMutation.isPending} onClick={() => void openRunChat('planning', true)}><RefreshCw /> Retry planning</Button></span>}
            {detail.run.status === 'plan_review' && planDraft && (
              <span className="flex flex-wrap items-center justify-end gap-2">
                {detail.run.session_id && onRunInChat && <Button type="button" variant="outline" size="sm" onClick={() => void openRunChat('planning', false)}><MessageSquareText /> Open planning chat</Button>}
                {detail.run.session_id && onRunInChat && <Button type="button" variant="outline" size="sm" disabled={retryPlanningMutation.isPending} onClick={() => void openRunChat('planning', true)}><RefreshCw /> Replan in chat</Button>}
                <Button type="button" size="sm" disabled={acceptPlanMutation.isPending} onClick={() => setConfirmingAction('approve_plan')}><FileCheck2 /> Approve plan</Button>
              </span>
            )}
            {detail.run.status === 'planned' && (
              detail.run.session_id && onRunInChat
                ? <Button type="button" size="sm" disabled={startInChatMutation.isPending} onClick={() => void openRunChat('implementation', true)}><Play /> Run implementation in chat</Button>
                : onRunInChat
                  ? <Button type="button" size="sm" onClick={() => setShowChatPicker((value) => !value)}><MessageSquareText /> Choose implementation chat</Button>
                  : null
            )}
            {detail.run.status === 'active' && (
              <span className="flex shrink-0 items-center gap-2">
                {detail.run.session_id && onRunInChat && <Button type="button" variant="outline" size="sm" onClick={() => void openRunChat('implementation', false)}><MessageSquareText /> Open implementation chat</Button>}
                {detail.run.session_id && onRunInChat && <Button type="button" size="sm" disabled={startReviewMutation.isPending || actionIsBlocked('start_review')} onClick={() => void openRunChat('review', true)}><ShieldCheck /> Run review in chat</Button>}
              </span>
            )}
            {detail.run.status === 'reviewing' && (
              <span className="flex shrink-0 items-center gap-2">
                {detail.run.session_id && onRunInChat && <Button type="button" variant="outline" size="sm" onClick={() => void openRunChat('review', false)}><MessageSquareText /> Open review chat</Button>}
                {detail.run.session_id && onRunInChat && <Button type="button" size="sm" disabled={startVerificationMutation.isPending || actionIsBlocked('start_verification')} onClick={() => void openRunChat('verification', true)}><ShieldCheck /> Run verify in chat</Button>}
              </span>
            )}
            {detail.run.status === 'verifying' && (
              <span className="flex shrink-0 items-center gap-2">
                {detail.run.session_id && onRunInChat && <Button type="button" variant="outline" size="sm" onClick={() => void openRunChat('verification', false)}><MessageSquareText /> Open verification chat</Button>}
                <Button type="button" size="sm" disabled={convergeMutation.isPending || actionIsBlocked('converge')} onClick={() => setConfirmingAction('converge')}><ShieldCheck /> Converge</Button>
              </span>
            )}
          </>}
        />
        {(acceptMutation.error || acceptPlanMutation.error || startAuthoringMutation.error || retryAuthoringMutation.error || startPlanningMutation.error || retryPlanningMutation.error || startInChatMutation.error || startReviewMutation.error || startVerificationMutation.error || (convergeMutation.error && !(convergeMutation.error instanceof EasdConvergenceApiError))) && (
          <p role="alert" className="border-t border-(--color-border) px-3 py-2 text-[10px] text-(--color-error) @xl/easd:px-4">
            {errorText(acceptMutation.error) ?? errorText(acceptPlanMutation.error) ?? errorText(startAuthoringMutation.error) ?? errorText(retryAuthoringMutation.error) ?? errorText(startPlanningMutation.error) ?? errorText(retryPlanningMutation.error) ?? errorText(startInChatMutation.error) ?? errorText(startReviewMutation.error) ?? errorText(startVerificationMutation.error) ?? errorText(convergeMutation.error)}
          </p>
        )}
      </header>

      {showChatPicker && ['intent', 'accepted', 'planned'].includes(detail.run.status) && !detail.run.session_id && (
        <section className="shrink-0 border-b border-(--color-border) bg-(--bg-card) p-3 @xl/easd:p-4">
          <div className="mx-auto max-w-5xl">
            <div className="flex items-start justify-between gap-3"><div><h2 className="text-xs font-semibold text-(--color-text)">Choose a Coding chat</h2><p className="mt-1 text-[10px] text-(--color-text-muted)">{detail.run.status === 'intent' ? 'The Intent will be linked for specification drafting; implementation remains blocked.' : detail.run.status === 'accepted' ? deliveryMode === 'direct' ? 'The accepted direct-flow specification will be linked and implementation will start without a Plan artifact.' : 'The accepted specification will be linked for planning; implementation remains blocked until plan approval.' : 'The accepted specification and plan will be linked and activated for implementation.'}</p></div><Button type="button" variant="ghost" size="icon-sm" aria-label="Close chat picker" onClick={() => setShowChatPicker(false)}><X /></Button></div>
            <label className="relative mt-3 block">
              <span className="sr-only">Search Coding chats</span>
              <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-(--color-text-subtle)" />
              <input value={chatSearch} onChange={(event) => setChatSearch(event.target.value)} className="h-9 w-full rounded-lg border border-(--color-border) bg-(--bg-page) pl-8 pr-3 text-xs text-(--color-text) outline-none focus:border-(--color-accent)" placeholder="Search loaded chats" />
            </label>
            <div className="mt-3 grid gap-2 @3xl/easd:grid-cols-2">
              {filteredChatSessions.map((session) => <button key={session.id} type="button" disabled={session.running || startInChatMutation.isPending || startAuthoringMutation.isPending || startPlanningMutation.isPending} onClick={() => void handoffToChat(session.id, detail.run.status === 'intent' ? 'authoring' : detail.run.status === 'accepted' ? deliveryMode === 'direct' ? 'implementation' : 'planning' : 'implementation', true)} className="rounded-lg border border-(--color-border) bg-(--bg-page) p-2.5 text-left hover:border-(--color-border-strong) disabled:cursor-not-allowed disabled:opacity-50"><p className="truncate text-xs font-medium text-(--color-text)">{session.title || 'Untitled Coding chat'}</p><p className="mt-1 text-[10px] text-(--color-text-subtle)">{session.running ? 'Running · finish the current turn first' : detail.run.status === 'intent' ? 'Idle · specification drafting will start automatically' : detail.run.status === 'accepted' ? deliveryMode === 'direct' ? 'Idle · direct implementation will start automatically' : 'Idle · planning will start automatically' : 'Idle · implementation will start automatically'}</p></button>)}
              {filteredChatSessions.length === 0 && !activeSessionsQuery.isLoading && <p className="rounded-lg border border-dashed border-(--color-border) p-3 text-[10px] text-(--color-text-muted)">{chatSearch.trim() ? 'No loaded chats match your search.' : 'No existing Coding chat in this scope.'}</p>}
              <Button type="button" variant="outline" disabled={creatingChat || startInChatMutation.isPending || startAuthoringMutation.isPending || startPlanningMutation.isPending} onClick={() => void createAndRunInChat()}>{creatingChat && <Loader2 className="animate-spin" />}<Plus /> New Coding chat</Button>
            </div>
            {activeSessionsQuery.hasNextPage && <div className="mt-2 flex justify-center"><Button type="button" variant="ghost" size="sm" disabled={activeSessionsQuery.isFetchingNextPage} onClick={() => void activeSessionsQuery.fetchNextPage()}>{activeSessionsQuery.isFetchingNextPage && <Loader2 className="animate-spin" />}Load more chats</Button></div>}
            {(chatActionError || startInChatMutation.error || startAuthoringMutation.error || startPlanningMutation.error || activeSessionsQuery.error) && <p role="alert" className="mt-2 text-[10px] text-(--color-error)">{chatActionError ?? errorText(startInChatMutation.error) ?? errorText(startAuthoringMutation.error) ?? errorText(startPlanningMutation.error) ?? errorText(activeSessionsQuery.error)}</p>}
          </div>
        </section>
      )}

      <div className="min-h-0 flex-1 overflow-auto p-3 @xl/easd:p-5">
        <div className="mx-auto max-w-5xl space-y-4">
          {(detail.run.status === 'intent' || detail.run.status === 'authoring') && (
            <section className="rounded-2xl border border-(--color-border) bg-(--bg-card) p-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-(--color-accent)">01 · Intent</p>
              <h2 className="mt-1 text-sm font-semibold text-(--color-text)">{detail.run.intent?.title ?? detail.run.title}</h2>
              <div className="mt-3 grid gap-3 @3xl/easd:grid-cols-2"><div className="rounded-xl bg-(--bg-key)/45 p-3"><p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">Problem</p><p className="mt-1 text-xs leading-5 text-(--color-text-2)">{detail.run.intent?.problem}</p></div><div className="rounded-xl bg-(--bg-key)/45 p-3"><p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">Intended outcome</p><p className="mt-1 text-xs leading-5 text-(--color-text-2)">{detail.run.intent?.outcome || 'Not supplied · the drafting agent must propose an observable outcome.'}</p></div></div>
              <div className="mt-4 grid grid-cols-3 overflow-hidden rounded-xl border border-(--color-border) text-[10px]"><div className="bg-(--color-success-subtle) px-3 py-2 text-(--color-success)"><strong className="block">1 · Intent</strong>Persisted</div><div className={cn('border-x border-(--color-border) px-3 py-2', detail.run.status === 'authoring' ? 'bg-(--color-accent)/10 text-(--color-accent)' : 'text-(--color-text-subtle)')}><strong className="block">2 · Draft</strong>{detail.run.status === 'authoring' ? 'Agent working' : 'Not started'}</div><div className="px-3 py-2 text-(--color-text-subtle)"><strong className="block">3 · Approve</strong>Human only</div></div>
            </section>
          )}

          {detail.run.status === 'draft' && draft && (
            <section className="overflow-hidden rounded-2xl border border-(--color-accent)/30 bg-(--bg-card)">
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-(--color-border) bg-(--color-accent)/7 p-4"><div><p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-(--color-accent)">Specification draft · v{draft.version}</p><h2 className="mt-1 text-sm font-semibold text-(--color-text)">Review before approval</h2><p className="mt-1 font-mono text-[9px] text-(--color-text-subtle)">{draft.content_hash}</p></div><span className="rounded-full bg-(--bg-page) px-2.5 py-1 text-[10px] text-(--color-text-muted)">{agentAuthoring ? `Agent draft · ${Math.round(agentAuthoring.confidence * 100)}% confidence` : 'User-authored draft'}</span></div>
              <div className="space-y-4 p-4">
                {agentAuthoring?.summary && <p className="rounded-lg bg-(--bg-key)/45 p-3 text-xs leading-5 text-(--color-text-2)">{agentAuthoring.summary}</p>}
                <div className="grid gap-3 @3xl/easd:grid-cols-2"><div><p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">Problem</p><p className="mt-1 text-xs leading-5 text-(--color-text-2)">{draft.spec.problem}</p></div><div><p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">Intended outcome</p><p className="mt-1 text-xs leading-5 text-(--color-text-2)">{draft.spec.outcome}</p></div></div>
                <div className="rounded-xl border border-(--color-border) bg-(--bg-key)/35 p-3"><p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">Suggested driven flow</p><p className="mt-1 text-xs font-semibold capitalize text-(--color-accent)">{draft.spec.delivery_flow?.mode ?? 'planned'}{draft.spec.delivery_flow?.mode === 'direct' ? ' · skip Plan' : ' · approve Plan'}</p><p className="mt-1 text-[10px] leading-4 text-(--color-text-muted)">{draft.spec.delivery_flow?.rationale ?? 'Plan is required by default.'}</p></div>
                <div className="grid gap-3 @3xl/easd:grid-cols-2"><div><p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">Goals</p><ul className="mt-1 space-y-1 text-xs text-(--color-text-2)">{draft.spec.goals.map((item) => <li key={item}>• {item}</li>)}</ul></div><div><p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">Non-goals</p><ul className="mt-1 space-y-1 text-xs text-(--color-text-2)">{draft.spec.non_goals.map((item) => <li key={item}>• {item}</li>)}</ul></div></div>
                <div><p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">Impact targets</p><div className="mt-1 space-y-1">{(draft.spec.impact_targets ?? []).map((item) => <p key={`${item.repository}:${item.path}`} className="font-mono text-[10px] text-(--color-text-2)">{item.repository}:{item.path} · {item.reason}</p>)}</div></div>
                <div><p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">Acceptance criteria &amp; evidence policy</p><div className="mt-2 grid gap-2 @4xl/easd:grid-cols-2">{draft.spec.criteria.map((criterion) => <article key={criterion.id} className="rounded-xl border border-(--color-border) bg-(--bg-page) p-3"><p className="font-mono text-[10px] font-semibold text-(--color-accent)">{criterion.id}</p><p className="mt-1 text-xs leading-5 text-(--color-text-2)">{criterion.statement}</p><p className="mt-1 text-[9px] text-(--color-text-subtle)">{criterion.evidence_policy.allowed_kinds.join(', ')} · machine={String(criterion.evidence_policy.machine_required)} · min={criterion.evidence_policy.minimum_passes}</p></article>)}</div></div>
                {(draft.spec.verification_commands ?? []).length > 0 && <div><p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">Planned verification</p><pre className="mt-1 whitespace-pre-wrap rounded-lg bg-(--bg-key)/45 p-3 font-mono text-[10px] text-(--color-text-2)">{draft.spec.verification_commands?.join('\n')}</pre></div>}
              </div>
            </section>
          )}

          {detail.active_spec && ['accepted', 'planning', 'plan_review', 'planned'].includes(detail.run.status) && (
            <section className="rounded-2xl border border-(--color-border) bg-(--bg-card) p-4">
              <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-(--color-success)">Approved specification · v{detail.active_spec.version}</p><h2 className="mt-1 text-sm font-semibold text-(--color-text)">{detail.active_spec.spec.outcome}</h2></div><p className="font-mono text-[9px] text-(--color-text-subtle)">{detail.active_spec.content_hash}</p></div>
              <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-(--color-text-muted)"><span>{detail.active_spec.spec.criteria.length} ACs</span><span>·</span><span>{detail.active_spec.spec.impact_targets?.length ?? 0} impact targets</span><span>·</span><span>{detail.active_spec.spec.verification_commands?.length ?? 0} verification commands</span><span>·</span><span className="font-medium capitalize text-(--color-accent)">{deliveryMode} flow</span></div>
            </section>
          )}

          {displayedPlan && (
            <section className="overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card)">
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-(--color-border) bg-(--bg-page)/55 p-4">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-(--color-accent)">Implementation plan · v{displayedPlan.version}</p>
                  <h2 className="mt-1 text-sm font-semibold text-(--color-text)">{displayedPlan.status === 'draft' ? 'Review before approval' : 'Approved execution contract'}</h2>
                  <p className="mt-1 font-mono text-[9px] text-(--color-text-subtle)">{displayedPlan.content_hash}</p>
                </div>
                <div className="text-right text-[10px] text-(--color-text-muted)">
                  <p>{displayedPlan.plan.missions.length} missions · spec {displayedPlan.spec_hash.slice(0, 8)}</p>
                  <p className="mt-1">{displayedPlan.plan.review_required ? 'Independent review required' : 'Standard review required'}</p>
                </div>
              </div>
              {displayedPlan.authoring?.summary && <p className="mx-4 mt-4 rounded-lg bg-(--bg-key)/45 p-3 text-xs leading-5 text-(--color-text-2)">{displayedPlan.authoring.summary}</p>}
              <div className="grid gap-2 p-4 @4xl/easd:grid-cols-2">
                {displayedPlan.plan.missions.map((mission) => (
                  <article key={mission.id} className="rounded-xl border border-(--color-border) bg-(--bg-page) p-3">
                    <div className="flex items-start justify-between gap-2"><div><p className="font-mono text-[10px] font-semibold text-(--color-accent)">{mission.id} · {mission.kind}</p><h3 className="mt-1 text-xs font-medium text-(--color-text)">{mission.title}</h3></div><span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-[9px] text-(--color-text-muted)">{mission.isolation}</span></div>
                    <p className="mt-2 text-[11px] leading-4 text-(--color-text-2)">{mission.goal}</p>
                    <p className="mt-2 font-mono text-[9px] text-(--color-text-subtle)">ACs {mission.acceptance_criteria.join(', ')} · depends {mission.depends_on.join(', ') || 'none'}</p>
                    <p className="mt-1 break-all font-mono text-[9px] text-(--color-text-subtle)">{mission.target_repositories.join(', ') || 'all accepted repos'} · {mission.target_paths.join(', ') || 'read-only scope'}</p>
                    <p className="mt-2 text-[10px] text-(--color-text-muted)"><span className="font-medium">Output:</span> {mission.expected_output}</p>
                    {mission.constraints.length > 0 && <p className="mt-1 text-[10px] text-(--color-text-muted)"><span className="font-medium">Constraints:</span> {mission.constraints.join(' · ')}</p>}
                    {mission.verification_commands.length > 0 && <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-(--bg-key)/55 p-2 font-mono text-[9px] text-(--color-text-2)">{mission.verification_commands.join('\n')}</pre>}
                  </article>
                ))}
              </div>
            </section>
          )}

          {!(['intent', 'authoring', 'draft', 'accepted', 'planning', 'plan_review', 'planned'] as string[]).includes(detail.run.status) && <>
          <section className="overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card)">
            <div className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div><p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-(--color-text-subtle)">Acceptance coverage</p><p className="mt-1 text-sm font-semibold text-(--color-text)">{acceptedCriteria} of {detail.criteria.length} criteria satisfied</p></div>
                <span className="text-lg font-semibold tabular-nums text-(--color-accent)">{acceptanceProgress}%</span>
              </div>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-(--bg-key)"><div className="h-full rounded-full bg-(--color-accent) transition-[width]" style={{ width: `${acceptanceProgress}%` }} /></div>
            </div>
            <div className="grid grid-cols-3 border-t border-(--color-border) bg-(--bg-page)/45 text-[10px]">
              <div className="px-3 py-2.5"><p className="uppercase tracking-wide text-(--color-text-subtle)">Spec</p><p className="mt-0.5 truncate font-mono text-(--color-text-2)">{detail.active_spec ? `v${detail.active_spec.version} · ${detail.active_spec.content_hash.slice(0, 8)}` : 'Draft'}</p></div>
              <div className="border-x border-(--color-border) px-3 py-2.5"><p className="uppercase tracking-wide text-(--color-text-subtle)">Missions</p><p className="mt-0.5 font-medium text-(--color-text-2)">{detail.missions.length} assigned</p></div>
              <div className="px-3 py-2.5"><p className="uppercase tracking-wide text-(--color-text-subtle)">Evidence</p><p className="mt-0.5 font-medium text-(--color-text-2)">{detail.evidence.length} records</p></div>
            </div>
            {detail.run.status === 'converged' && <p className="flex items-center gap-1.5 border-t border-(--color-border) px-4 py-3 text-xs font-medium text-(--color-success)"><Check size={13} /> Converged at {detail.run.converged_at ? new Date(detail.run.converged_at).toLocaleString() : 'recorded revision'}</p>}
          </section>

          {convergenceReasons.length > 0 && (
            <section role="alert" className="rounded-xl border border-(--color-warning)/40 bg-(--color-warning)/8 p-3">
              <h2 className="flex items-center gap-1.5 text-xs font-semibold text-(--color-warning)"><AlertTriangle size={13} /> Convergence blocked</h2>
              <ul className="mt-2 space-y-1 text-xs text-(--color-text-2)">{convergenceReasons.map((reason, index) => <li key={`${reason.code}-${index}`}>• {reason.code}{reason.criterion_id ? ` · ${reason.criterion_id}` : ''}{reason.status ? ` · ${reason.status}` : ''}{reason.commands?.length ? ` · ${reason.commands.join(', ')}` : ''}</li>)}</ul>
            </section>
          )}

          <section>
            <div className="mb-2 flex items-center justify-between"><h2 className="text-xs font-semibold uppercase tracking-wide text-(--color-text-muted)">Acceptance matrix</h2><span className="text-[10px] text-(--color-text-subtle)">{statusCounts.passed ?? 0} passed · {detail.criteria.length} total</span></div>
            <div className="grid gap-2 @4xl/easd:grid-cols-2">
              {detail.criteria.length === 0 && <p className="rounded-lg border border-dashed border-(--color-border) p-3 text-xs text-(--color-text-muted) @4xl/easd:col-span-2">Accept the draft specification to start EASD.</p>}
              {detail.criteria.map((criterion) => (
                <article key={criterion.id} className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3">
                  <div className="flex items-start gap-2"><span className={cn('mt-0.5 font-mono text-[11px] font-semibold', criterionTone(criterion.status))}>{criterion.id}</span><p className="min-w-0 flex-1 text-xs leading-5 text-(--color-text-2)">{criterion.statement}</p><span className={cn('shrink-0 rounded-full bg-(--bg-key) px-2 py-0.5 text-[10px]', criterionTone(criterion.status))}>{criterion.status}</span></div>
                  <p className="mt-1 pl-12 text-[10px] text-(--color-text-subtle)">{criterion.mission_ids.length} missions · {criterion.evidence_ids.length} evidence</p>
                </article>
              ))}
            </div>
          </section>

          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-(--color-text-muted)">Missions</h2>
            <div className="grid gap-2 @4xl/easd:grid-cols-2">
              {detail.missions.length === 0 && <p className="text-xs text-(--color-text-subtle) @4xl/easd:col-span-2">No EASD-bound delegation yet.</p>}
              {detail.missions.map((mission) => (
                <article key={mission.id} className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3 text-xs">
                  <div className="flex items-center justify-between gap-2"><span className="font-medium text-(--color-text)">{mission.recipient}</span><span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-[10px] text-(--color-text-muted)">{mission.status}</span></div>
                  <p className="mt-1 line-clamp-2 text-(--color-text-2)">{String(mission.spec.goal ?? 'Mission')}</p>
                  <p className="mt-1 font-mono text-[10px] text-(--color-text-subtle)">{Array.isArray(mission.spec.acceptance_criteria) ? mission.spec.acceptance_criteria.join(', ') : ''} · attempt {mission.attempt}</p>
                </article>
              ))}
            </div>
          </section>

          {detail.active_spec && detail.run.status !== 'converged' && (
            <section className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3">
              <h2 className="text-xs font-semibold text-(--color-text)">Add evidence</h2>
              <div className="mt-2 grid gap-2 @3xl/easd:grid-cols-2">
                <SelectControl value={evidenceCriterion} onValueChange={setEvidenceCriterion} ariaLabel="Evidence criterion" className="text-xs" options={[{ value: '', label: 'Criterion…' }, ...detail.criteria.map((criterion) => ({ value: criterion.id, label: criterion.id }))]} />
                <SelectControl value={evidenceKind} onValueChange={(value) => setEvidenceKind(value as EasdAppendableEvidenceKind)} ariaLabel="Evidence kind" className="text-xs" options={[{ value: 'manual', label: 'Manual observation' }, { value: 'review', label: 'Independent review' }, { value: 'waiver', label: 'Waiver' }]} />
                {evidenceKind !== 'waiver' && <SelectControl value={evidenceResult} onValueChange={(value) => setEvidenceResult(value as EasdEvidenceResult)} ariaLabel="Evidence result" className="text-xs" options={[{ value: 'passed', label: 'Passed' }, { value: 'failed', label: 'Failed' }, { value: 'inconclusive', label: 'Inconclusive' }]} />}
                <input value={evidenceSummary} onChange={(event) => setEvidenceSummary(event.target.value)} className="h-9 rounded-lg border border-(--color-border) bg-(--bg-page) px-3 text-xs text-(--color-text)" placeholder="Evidence summary" />
              </div>
              <div className="mt-2 flex justify-end"><Button type="button" size="sm" disabled={!evidenceCriterion || !evidenceSummary.trim() || evidenceMutation.isPending} onClick={() => void addEvidence()}>Add evidence</Button></div>
              {evidenceMutation.error && <p className="mt-2 text-xs text-(--color-error)">{errorText(evidenceMutation.error)}</p>}
            </section>
          )}

          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-(--color-text-muted)">Evidence ledger</h2>
            <div className="grid gap-2 @4xl/easd:grid-cols-2">
              {detail.evidence.length === 0 && <p className="text-xs text-(--color-text-subtle) @4xl/easd:col-span-2">No evidence yet.</p>}
              {detail.evidence.map((item) => (
                <article key={item.id} className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3 text-xs">
                  <div className="flex items-center justify-between gap-2"><span className="font-medium text-(--color-text)">{item.kind} · {item.result}</span><span className="font-mono text-[10px] text-(--color-text-subtle)">{item.criterion_ids.join(', ')}</span></div>
                  <p className="mt-1 text-(--color-text-2)">{item.summary}</p>
                  <p className="mt-1 truncate font-mono text-[10px] text-(--color-text-subtle)">{item.artifact_hash ? `artifact ${item.artifact_hash.slice(0, 12)}` : item.producer}</p>
                </article>
              ))}
            </div>
          </section>

          {detail.active_spec && detail.run.status !== 'converged' && (
            <section className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3">
              <h2 className="text-xs font-semibold text-(--color-text)">Record deviation</h2>
              <div className="mt-2 flex flex-col gap-2 @2xl/easd:flex-row">
                <SelectControl value={deviationCriterion} onValueChange={setDeviationCriterion} ariaLabel="Deviation criterion" className="text-xs @2xl/easd:w-28" options={[{ value: '', label: 'General' }, ...detail.criteria.map((criterion) => ({ value: criterion.id, label: criterion.id }))]} />
                <input value={deviationDescription} onChange={(event) => setDeviationDescription(event.target.value)} className="h-9 min-w-0 flex-1 rounded-lg border border-(--color-border) bg-(--bg-page) px-3 text-xs text-(--color-text)" placeholder="Scope or spec deviation" />
                <Button type="button" size="sm" disabled={!deviationDescription.trim() || deviationMutation.isPending} onClick={() => void addDeviation()}>Record</Button>
              </div>
              {deviationMutation.error && <p role="alert" className="mt-2 text-xs text-(--color-error)">{errorText(deviationMutation.error)}</p>}
            </section>
          )}

          <section>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-(--color-text-muted)">Deviations</h2>
            <div className="space-y-2">
              {detail.deviations.length === 0 && <p className="text-xs text-(--color-text-subtle)">No recorded deviation.</p>}
              {detail.deviations.map((item) => (
                <article key={item.id} className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3 text-xs">
                  <div className="flex items-center justify-between gap-2"><span className={item.blocking && (item.status === 'open' || item.status === 'approved') ? 'font-medium text-(--color-warning)' : 'font-medium text-(--color-text)'}>{item.criterion_id ?? 'General'} · {item.status}</span>{item.blocking && <span className="text-[10px] text-(--color-warning)">blocking</span>}</div>
                  <p className="mt-1 text-(--color-text-2)">{item.description}</p>
                </article>
              ))}
            </div>
          </section>
          </>}
        </div>
      </div>
    </div>
  )
}

export function EvoAgentSpecsPanel({ workspace, projectId, sessionId, active = true, onRunInChat }: EvoAgentSpecsPanelProps) {
  const setupQuery = useEasdSetupQuery(workspace, projectId, active)
  const setup = setupQuery.data
  const runsQuery = useEasdRunsQuery(workspace, projectId, active && Boolean(setup?.ready))
  const selectedRunId = useUIStore((state) => state.easdSelectedRunId)
  const setSelectedRunId = useUIStore((state) => state.setEasdSelectedRunId)
  const [creating, setCreating] = useState(false)
  const [showSetup, setShowSetup] = useState(false)
  const [runsView, setRunsView] = useState<RunsView>(loadRunsView)
  const [search, setSearch] = useState('')
  const easdRunOpenRequest = useUIStore((state) => state.easdRunOpenRequest)
  const clearEasdRunOpenRequest = useUIStore((state) => state.clearEasdRunOpenRequest)

  useEffect(() => {
    if (!active || !easdRunOpenRequest) return
    clearEasdRunOpenRequest(easdRunOpenRequest.id)
  }, [active, clearEasdRunOpenRequest, easdRunOpenRequest])

  const changeView = (view: RunsView) => {
    setRunsView(view)
    try {
      localStorage.setItem(STORAGE_KEYS.easd.runsView, view)
    } catch {
      // Storage is optional in restricted webviews.
    }
  }

  if (selectedRunId && setup) return <RunDetail runId={selectedRunId} setup={setup} onBack={() => setSelectedRunId(null)} onRunInChat={onRunInChat} />
  if (creating && setup) {
    return (
      <CreateIntentForm
        setup={setup}
        projectId={projectId}
        sessionId={sessionId}
        initialWorkspace={workspace}
        onCreated={(runId) => {
          setCreating(false)
          setSelectedRunId(runId)
        }}
        onCancel={() => setCreating(false)}
      />
    )
  }

  if (setupQuery.isLoading) {
    return <div className="flex h-full items-center justify-center"><Loader2 className="animate-spin text-(--color-accent)" /></div>
  }
  if (!setup) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <AlertTriangle className="text-(--color-error)" />
        <p className="text-sm font-medium text-(--color-text)">Could not load repository setup</p>
        <p className="text-xs text-(--color-error)">{errorText(setupQuery.error)}</p>
        <Button type="button" variant="outline" onClick={() => void setupQuery.refetch()}>Try again</Button>
      </div>
    )
  }

  const setupVisible = showSetup || !setup.ready
  const scopeLabel = setup.scope === 'project'
    ? `${setup.repository_count} ${setup.repository_count === 1 ? 'repository' : 'repositories'}`
    : workspaceName(workspace)

  return (
    <div className="@container/easd flex h-full min-h-0 flex-col bg-(--bg-page)">
      <header className="shrink-0 border-b border-(--color-border) bg-(--bg-card)/45">
        <div className="flex min-h-16 items-center gap-3 px-3 @xl/easd:px-4">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-(--color-accent) to-(--color-accent)/70 text-(--color-text-on-accent) shadow-sm"><Route size={17} /></span>
          <div className="min-w-0 flex-1">
            <div className="mb-0.5 flex items-center gap-2">
              <span className="text-[9px] font-semibold uppercase tracking-[0.16em] text-(--color-accent)">EASD</span>
              <span className="size-1 rounded-full bg-(--color-border-strong)" />
              <span className="truncate text-[9px] text-(--color-text-subtle)">{setup.scope === 'project' ? 'Project' : 'Workspace'} · {scopeLabel}</span>
            </div>
            <h1 className="line-clamp-2 text-[13px] font-semibold leading-4 text-(--color-text)" title={EASD_DISPLAY_NAME}>{EASD_DISPLAY_NAME}</h1>
          </div>
        </div>
        <div className="flex items-center gap-2 border-t border-(--color-border) px-3 py-2 @xl/easd:px-4">
          <p className="min-w-0 flex-1 truncate text-[10px] text-(--color-text-subtle)">{setup.ready ? 'Repositories ready · runs enabled' : 'Repository setup required'}</p>
          {setup.ready && (
            <Button type="button" variant={setupVisible ? 'secondary' : 'ghost'} size="sm" onClick={() => setShowSetup((value) => !value)}>
              <Settings2 /> Repositories
            </Button>
          )}
          {!setupVisible && <Button type="button" size="sm" onClick={() => setCreating(true)}><Plus /> New run</Button>}
        </div>
      </header>

      {setupQuery.error ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <AlertTriangle className="text-(--color-error)" />
          <p className="text-sm font-medium text-(--color-text)">Could not load repository setup</p>
          <p className="text-xs text-(--color-error)">{errorText(setupQuery.error)}</p>
          <Button type="button" variant="outline" onClick={() => void setupQuery.refetch()}>Try again</Button>
        </div>
      ) : setupVisible ? (
        <div className="min-h-0 flex-1 overflow-auto">
          <SetupView setup={setup} workspace={workspace} projectId={projectId} onReady={() => setShowSetup(false)} />
        </div>
      ) : runsQuery.isLoading ? (
        <div className="flex flex-1 items-center justify-center"><Loader2 className="animate-spin text-(--color-accent)" /></div>
      ) : runsQuery.error ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <AlertTriangle className="text-(--color-error)" />
          <p className="text-sm font-medium text-(--color-text)">Could not load specification runs</p>
          <p className="text-xs text-(--color-error)">{errorText(runsQuery.error)}</p>
          <Button type="button" variant="outline" onClick={() => void runsQuery.refetch()}>Try again</Button>
        </div>
      ) : (
        <RunsOverview
          runs={runsQuery.data?.runs ?? []}
          setup={setup}
          view={runsView}
          search={search}
          onSearch={setSearch}
          onView={changeView}
          onOpen={setSelectedRunId}
          onCreate={() => setCreating(true)}
        />
      )}
    </div>
  )
}
