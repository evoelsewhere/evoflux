import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { EasdRunDetail } from '@/api/types'
import { EvoAgentSpecsPanel } from '@/components/EvoAgentSpecsPanel'

const mocks = vi.hoisted(() => ({
  runs: vi.fn(),
  setup: vi.fn(),
  detail: vi.fn(),
  action: vi.fn(),
  generate: vi.fn(),
  projectSessions: vi.fn(),
  workspaceSessions: vi.fn(),
}))

vi.mock('@/queries', () => ({
  useEasdRunsQuery: () => mocks.runs(),
  useEasdSetupQuery: () => mocks.setup(),
  useProjectSessionsQuery: () => mocks.projectSessions(),
  useCodingWorkspaceSessionsQuery: () => mocks.workspaceSessions(),
  useGenerateEasdScopeAndProofMutation: () => mocks.generate(),
  useInitializeEasdSetupMutation: () => mocks.action(),
  useEasdRunQuery: () => mocks.detail(),
  useAcceptEasdPlanRevisionMutation: () => mocks.action(),
  useCreateEasdRunMutation: () => mocks.action(),
  useCreateEasdRevisionMutation: () => mocks.action(),
  useAcceptEasdRevisionMutation: () => mocks.action(),
  useStartEasdRunInChatMutation: () => mocks.action(),
  useStartEasdPlanningMutation: () => mocks.action(),
  useStartEasdReviewMutation: () => mocks.action(),
  useStartEasdSpecAuthoringMutation: () => mocks.action(),
  useStartEasdVerificationMutation: () => mocks.action(),
  useConvergeEasdRunMutation: () => mocks.action(),
  useAddEasdEvidenceMutation: () => mocks.action(),
  useAddEasdDeviationMutation: () => mocks.action(),
}))

const run = {
  id: 'run-1',
  project_id: 'project-1',
  workspace: '/repo',
  session_id: 'session-1',
  title: 'EASD feature',
  intent: null,
  status: 'active',
  risk_tier: 'standard',
  active_spec_revision_id: 'revision-1',
  active_plan_revision_id: null,
  convergence_report: null,
  converged_at: null,
  created_at: '2026-08-23T00:00:00Z',
  updated_at: '2026-08-23T00:00:00Z',
} as const

const detail: EasdRunDetail = {
  run,
  revisions: [],
  active_spec: {
    id: 'revision-1',
    run_id: 'run-1',
    version: 1,
    status: 'accepted',
    content_hash: 'f'.repeat(64),
    created_at: '2026-08-23T00:00:00Z',
    accepted_at: '2026-08-23T00:00:00Z',
    spec: {
      title: 'EASD feature',
      problem: 'No traceability',
      outcome: 'Verified convergence',
      goals: [],
      non_goals: [],
      source_refs: [],
      risk_tier: 'standard',
      criteria: [],
    },
  },
  plan_revisions: [],
  active_plan: null,
  criteria: [
    {
      id: 'AC-1',
      statement: 'The API exposes the AC matrix.',
      required: true,
      status: 'passed',
      evidence_policy: {
        allowed_kinds: ['machine'],
        machine_required: true,
        minimum_passes: 1,
      },
      evidence_ids: ['evidence-1'],
      mission_ids: ['mission-1'],
    },
  ],
  missions: [
    {
      id: 'mission-1',
      trace_run_id: 'run-1',
      lead_session_id: 'session-1',
      delegator: 'lead',
      recipient: 'coder#1',
      status: 'completed',
      spec: { goal: 'Implement AC-1', acceptance_criteria: ['AC-1'] },
      dependencies: [],
      attempt: 1,
      deadline_at: null,
      dispatched_at: null,
      completed_at: '2026-08-23T00:00:00Z',
      result: null,
      last_rejection: null,
      created_at: '2026-08-23T00:00:00Z',
      updated_at: '2026-08-23T00:00:00Z',
    },
  ],
  evidence: [
    {
      id: 'evidence-1',
      run_id: 'run-1',
      delegation_task_id: 'mission-1',
      spec_hash: 'f'.repeat(64),
      criterion_ids: ['AC-1'],
      producer: 'coder#1',
      kind: 'machine',
      result: 'passed',
      summary: 'Focused tests passed.',
      revision: 'abc123',
      artifact_hash: 'e'.repeat(64),
      payload: {},
      source_key: 'source-1',
      created_at: '2026-08-23T00:00:00Z',
    },
  ],
  deviations: [],
  convergence: null,
}

const planRevision = {
  id: 'plan-revision-1',
  run_id: 'run-1',
  version: 1,
  status: 'draft' as const,
  spec_hash: 'f'.repeat(64),
  content_hash: 'a'.repeat(64),
  created_at: '2026-08-24T00:00:00Z',
  accepted_at: null,
  authoring: {
    mode: 'agent_chat' as const,
    agent: 'lead',
    session_id: 'session-1',
    summary: 'Every AC has bounded implementation and review ownership.',
    confidence: 0.92,
    submitted_at: '2026-08-24T00:00:00Z',
  },
  plan: {
    spec_hash: 'f'.repeat(64),
    review_required: true,
    integration_owner: 'M1',
    missions: [
      {
        id: 'M1',
        kind: 'implementation' as const,
        title: 'Implement AC-1',
        goal: 'Implement the accepted behavior.',
        acceptance_criteria: ['AC-1'],
        target_repositories: ['repo'],
        target_paths: ['app/service.py'],
        depends_on: [],
        expected_output: 'Implementation and machine evidence.',
        constraints: ['Preserve the public contract'],
        verification_commands: ['pytest -q tests/service.py'],
        isolation: 'worktree' as const,
      },
      {
        id: 'M2',
        kind: 'review' as const,
        title: 'Review AC-1',
        goal: 'Independently review the integrated behavior.',
        acceptance_criteria: ['AC-1'],
        target_repositories: ['repo'],
        target_paths: ['app/service.py'],
        depends_on: ['M1'],
        expected_output: 'Cited review evidence.',
        constraints: [],
        verification_commands: [],
        isolation: 'shared' as const,
      },
    ],
  },
}

function useDraftDetail() {
  const draftRevision = {
    ...detail.active_spec!,
    status: 'draft' as const,
    accepted_at: null,
    spec: {
      ...detail.active_spec!.spec,
      criteria: [{
        id: 'AC-1',
        statement: 'The API exposes the AC matrix.',
        required: true,
        evidence_policy: {
          allowed_kinds: ['machine'] as Array<'machine'>,
          machine_required: true,
          minimum_passes: 1,
        },
      }],
    },
    authoring: {
      mode: 'agent_chat' as const,
      agent: 'lead',
      session_id: 'session-1',
      summary: 'Grounded in repository API ownership and focused tests.',
      confidence: 0.91,
      submitted_at: '2026-08-24T00:00:00Z',
    },
  }
  mocks.detail.mockReturnValue({
    data: {
      ...detail,
      run: {
        ...run,
        status: 'draft',
        intent: {
          title: run.title,
          problem: detail.active_spec!.spec.problem,
          outcome: '',
        },
        active_spec_revision_id: null,
      },
      revisions: [draftRevision],
      active_spec: null,
      criteria: [],
      missions: [],
      evidence: [],
    } satisfies EasdRunDetail,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  })
}

const readySetup = {
  scope: 'project',
  workspace: '/repo',
  project_id: 'project-1',
  ready: true,
  repository_count: 2,
  installed_count: 2,
  repositories: [
    {
      path: '/repo',
      name: 'repo',
      display_name: 'Backend',
      status: 'ready',
      installed: true,
      manifest_path: '.evoflux/easd/config.json',
      data_directory: 'documents/easd',
      data_path: '/repo/documents/easd',
      rules_path: '.evoflux/easd/RULES.md',
      skills_path: '.evoflux/skills',
      skill_names: ['easd-specify', 'easd-plan', 'easd-implement', 'easd-review', 'easd-verify'],
      issue: null,
    },
    {
      path: '/web',
      name: 'web',
      display_name: 'Frontend',
      status: 'ready',
      installed: true,
      manifest_path: '.evoflux/easd/config.json',
      data_directory: 'documents/easd',
      data_path: '/web/documents/easd',
      rules_path: '.evoflux/easd/RULES.md',
      skills_path: '.evoflux/skills',
      skill_names: ['easd-specify', 'easd-plan', 'easd-implement', 'easd-review', 'easd-verify'],
      issue: null,
    },
  ],
} as const

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
  mocks.runs.mockReset()
  mocks.setup.mockReset()
  mocks.detail.mockReset()
  mocks.action.mockReset()
  mocks.generate.mockReset()
  mocks.projectSessions.mockReset()
  mocks.workspaceSessions.mockReset()
  mocks.runs.mockReturnValue({
    data: { runs: [run] },
    isLoading: false,
  })
  mocks.setup.mockReturnValue({ data: readySetup, isLoading: false, error: null, refetch: vi.fn() })
  mocks.detail.mockReturnValue({ data: detail, isLoading: false })
  mocks.action.mockReturnValue({
    error: null,
    isPending: false,
    mutateAsync: vi.fn(),
  })
  mocks.generate.mockReturnValue({
    error: null,
    isPending: false,
    mutateAsync: vi.fn(),
    reset: vi.fn(),
  })
  const emptySessions = {
    data: { pages: [{ data: [] }] },
    isLoading: false,
    error: null,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
  }
  mocks.projectSessions.mockReturnValue(emptySessions)
  mocks.workspaceSessions.mockReturnValue(emptySessions)
})

describe('EvoAgentSpecsPanel', () => {
  it('renders live AC, mission, and evidence state from the server detail', async () => {
    mocks.detail.mockReturnValue({
      data: { ...detail, run: { ...run, status: 'verifying' } },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    })
    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" />)

    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))
    expect(await screen.findByText('Acceptance matrix')).toBeInTheDocument()
    expect(screen.getByText('The API exposes the AC matrix.')).toBeInTheDocument()
    expect(screen.getByText('coder#1')).toBeInTheDocument()
    expect(screen.getByText('Focused tests passed.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Converge/i })).toBeEnabled()
  })

  it('does not render a false empty state while the run list is loading', () => {
    mocks.runs.mockReturnValue({ data: undefined, isLoading: true })
    render(<EvoAgentSpecsPanel workspace="/repo" />)

    expect(screen.queryByText('Your repositories are ready')).not.toBeInTheDocument()
  })

  it('requires repository initialization before showing run creation', () => {
    mocks.setup.mockReturnValue({
      data: {
        ...readySetup,
        ready: false,
        installed_count: 1,
        repositories: [
          readySetup.repositories[0],
          {
            ...readySetup.repositories[1],
            status: 'not_initialized',
            installed: false,
          },
        ],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    })

    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" />)

    expect(screen.getByText('Set up Agent Specification-Driven Development')).toBeInTheDocument()
    expect(screen.getByText('1/2 ready')).toBeInTheDocument()
    expect(screen.getByLabelText('EASD skill bundle')).toHaveTextContent(
      'easd-specifyeasd-planeasd-implementeasd-revieweasd-verify',
    )
    expect(screen.getByRole('button', { name: 'Initialize' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /New run/i })).not.toBeInTheDocument()
  })

  it('offers an in-place skill bundle upgrade without calling destructive repair', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(readySetup)
    mocks.action.mockReturnValue({ error: null, isPending: false, mutateAsync })
    mocks.setup.mockReturnValue({
      data: {
        ...readySetup,
        ready: false,
        installed_count: 1,
        repositories: [
          readySetup.repositories[0],
          {
            ...readySetup.repositories[1],
            status: 'upgrade_required',
            installed: false,
            issue: 'EASD setup schema 2 needs a repository-store upgrade',
          },
        ],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    })

    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" />)

    expect(screen.getByText('Upgrade available')).toBeInTheDocument()
    expect(screen.getByText(
      '5 Coding skills · .evoflux/skills',
    )).toBeInTheDocument()
    expect(screen.getByText(
      '5 required Coding skills · .evoflux/skills',
    )).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Upgrade' }))
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith({
      repositoryPaths: ['/web'],
      dataDirectory: 'documents/easd',
      overwrite: false,
    }))
  })

  it('isolates destructive repair from safe upgrades in the bulk setup action', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(readySetup)
    mocks.action.mockReturnValue({ error: null, isPending: false, mutateAsync })
    mocks.setup.mockReturnValue({
      data: {
        ...readySetup,
        ready: false,
        installed_count: 0,
        repositories: [
          {
            ...readySetup.repositories[0],
            status: 'upgrade_required',
            installed: false,
            issue: 'Upgrade required',
          },
          {
            ...readySetup.repositories[1],
            status: 'invalid',
            installed: false,
            issue: 'Invalid Skill scope',
          },
        ],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    })

    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" />)
    fireEvent.click(screen.getByRole('button', { name: 'Set up 2 repositories' }))

    await waitFor(() => expect(mutateAsync).toHaveBeenNthCalledWith(1, {
      repositoryPaths: ['/repo'],
      dataDirectory: 'documents/easd',
      overwrite: false,
    }))
    expect(mutateAsync).toHaveBeenNthCalledWith(2, {
      repositoryPaths: ['/web'],
      dataDirectory: 'documents/easd',
      overwrite: true,
    })
  })

  it('switches between board, table, and compact list views', () => {
    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" />)

    expect(screen.getByText('Planning')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Table' }))
    expect(screen.getByRole('columnheader', { name: 'Repository' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'List' }))
    expect(screen.getByText(/repo · Standard ·/)).toBeInTheDocument()
  })

  it('uses the full methodology name as the UI title', () => {
    const { container } = render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" />)

    expect(container.firstElementChild).toHaveClass('@container/easd')
    expect(screen.getByRole('heading', { name: 'Agent Specification-Driven Development' })).toBeInTheDocument()
  })

  it('creates a run from minimal Intent and keeps outcome optional', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ run: { id: 'intent-run' } })
    mocks.action.mockReturnValue({ error: null, isPending: false, mutateAsync })
    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" />)

    fireEvent.click(screen.getByRole('button', { name: 'New run' }))
    expect(screen.getByRole('heading', { name: 'Describe the problem; agents draft the specification next' })).toBeInTheDocument()
    expect(screen.queryByText('02 · Scope')).not.toBeInTheDocument()
    expect(screen.queryByText('03 · Proof')).not.toBeInTheDocument()
    const repository = screen.getByRole('combobox', { name: 'Owning repository' })
    expect(repository.tagName).toBe('BUTTON')
    fireEvent.click(repository)
    const repositorySearch = await screen.findByRole('combobox', { name: 'Search Owning repository' })
    expect(repositorySearch).toBeInTheDocument()
    fireEvent.keyDown(repositorySearch, { key: 'Escape' })
    fireEvent.change(screen.getByRole('textbox', { name: 'Run title' }), { target: { value: 'Minimal Intent' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Problem' }), { target: { value: 'The specification has not been drafted.' } })
    expect(screen.getByRole('textbox', { name: /Intended outcome/ })).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Create run' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Create run' }))
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith({
      sessionId: undefined,
      intent: {
        title: 'Minimal Intent',
        problem: 'The specification has not been drafted.',
        outcome: undefined,
      },
    }))
  })

  it('starts specification drafting in the linked chat without authorizing implementation', async () => {
    const onRunInChat = vi.fn()
    const mutateAsync = vi.fn().mockResolvedValue({ ...run, status: 'authoring' })
    mocks.action.mockReturnValue({ error: null, isPending: false, mutateAsync })
    mocks.detail.mockReturnValue({
      data: {
        ...detail,
        run: {
          ...run,
          status: 'intent',
          intent: {
            title: 'Draft from Intent',
            problem: 'No specification exists yet.',
            outcome: '',
          },
          active_spec_revision_id: null,
        },
        revisions: [],
        active_spec: null,
        criteria: [],
        missions: [],
        evidence: [],
      } satisfies EasdRunDetail,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    })
    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" onRunInChat={onRunInChat} />)

    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Draft specification in chat' }))

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith('session-1')
      expect(onRunInChat).toHaveBeenCalledWith(expect.objectContaining({
        phase: 'authoring',
        autoSend: true,
        prompt: expect.stringContaining('easd_submit_specification'),
      }))
    })
    const prompt = String(onRunInChat.mock.calls[0][0].prompt)
    expect(prompt).toMatch(/^\$easd-specify/)
    expect(prompt).toContain('do not implement')
  })

  it('shows the persisted agent draft for edit and explicit human approval', () => {
    useDraftDetail()
    const mutateAsync = vi.fn().mockResolvedValue({ status: 'accepted' })
    mocks.action.mockReturnValue({ error: null, isPending: false, mutateAsync })
    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" />)

    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))

    expect(screen.getByRole('heading', { name: 'Review before approval' })).toBeInTheDocument()
    expect(screen.getByText('Verified convergence')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit specification' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Approve specification' }))
    expect(mutateAsync).toHaveBeenCalledOnce()
  })

  it('saves user edits as a newer specification draft revision', async () => {
    useDraftDetail()
    const mutateAsync = vi.fn().mockResolvedValue({ id: 'revision-2' })
    mocks.action.mockReturnValue({ error: null, isPending: false, mutateAsync })
    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" />)

    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Edit specification' }))
    fireEvent.change(screen.getByRole('textbox', { name: /Intended outcome/ }), {
      target: { value: 'A user-reviewed observable outcome.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save draft revision' }))

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith(expect.objectContaining({
      specification: expect.objectContaining({
        outcome: 'A user-reviewed observable outcome.',
      }),
    })))
  })

  it('opens an active run in its linked chat with a resume prompt', () => {
    const onRunInChat = vi.fn()
    render(
      <EvoAgentSpecsPanel
        workspace="/repo"
        projectId="project-1"
        sessionId="session-1"
        onRunInChat={onRunInChat}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Open implementation chat' }))

    expect(onRunInChat).toHaveBeenCalledWith(expect.objectContaining({
      sessionId: 'session-1',
      workspace: '/repo',
      projectId: 'project-1',
      autoSend: false,
      phase: 'implementation',
      prompt: expect.stringContaining('Resume implementation for EASD run'),
    }))
    expect(String(onRunInChat.mock.calls[0][0].prompt)).toMatch(/^\$easd-implement/)
  })

  it('loads the EASD planning skill for the first accepted-run kickoff', async () => {
    const onRunInChat = vi.fn()
    const mutateAsync = vi.fn().mockResolvedValue({ ...run, status: 'planning' })
    mocks.action.mockReturnValue({ error: null, isPending: false, mutateAsync })
    mocks.detail.mockReturnValue({
      data: { ...detail, run: { ...run, status: 'accepted' } },
      isLoading: false,
    })
    render(
      <EvoAgentSpecsPanel
        workspace="/repo"
        projectId="project-1"
        sessionId="session-1"
        onRunInChat={onRunInChat}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Run plan in chat' }))

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith('session-1'))
    const prompt = String(onRunInChat.mock.calls[0][0].prompt)
    expect(prompt).toMatch(/^\$easd-plan/)
    expect(prompt).toContain('Plan EASD run')
  })

  it('renders the persisted plan and requires explicit plan approval', () => {
    const mutateAsync = vi.fn().mockResolvedValue({ status: 'accepted' })
    mocks.action.mockReturnValue({ error: null, isPending: false, mutateAsync })
    mocks.detail.mockReturnValue({
      data: {
        ...detail,
        run: { ...run, status: 'plan_review', active_plan_revision_id: null },
        plan_revisions: [planRevision],
        active_plan: null,
      },
      isLoading: false,
    })

    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" />)
    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))

    expect(screen.getByRole('heading', { name: 'Review before approval' })).toBeInTheDocument()
    expect(screen.getByText('Implement AC-1')).toBeInTheDocument()
    expect(screen.getByText('Review AC-1')).toBeInTheDocument()
    expect(screen.getByText('pytest -q tests/service.py')).toBeInTheDocument()
    expect(screen.getByText(/Preserve the public contract/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Approve plan' }))
    expect(mutateAsync).toHaveBeenCalledOnce()
  })

  it('starts implementation only from an approved plan', async () => {
    const onRunInChat = vi.fn()
    const mutateAsync = vi.fn().mockResolvedValue({ ...run, status: 'active' })
    const acceptedPlan = { ...planRevision, status: 'accepted' as const, accepted_at: '2026-08-24T00:01:00Z' }
    mocks.action.mockReturnValue({ error: null, isPending: false, mutateAsync })
    mocks.detail.mockReturnValue({
      data: {
        ...detail,
        run: { ...run, status: 'planned', active_plan_revision_id: acceptedPlan.id },
        plan_revisions: [acceptedPlan],
        active_plan: acceptedPlan,
      },
      isLoading: false,
    })

    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" onRunInChat={onRunInChat} />)
    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Run implementation in chat' }))

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith('session-1'))
    expect(onRunInChat).toHaveBeenCalledWith(expect.objectContaining({
      phase: 'implementation',
      prompt: expect.stringMatching(/^\$easd-implement/),
    }))
    expect(String(onRunInChat.mock.calls[0][0].prompt)).toContain(acceptedPlan.content_hash)
  })

  it('uses the accepted direct flow to skip Plan but not later gates', async () => {
    const onRunInChat = vi.fn()
    const mutateAsync = vi.fn().mockResolvedValue({ ...run, status: 'active' })
    mocks.action.mockReturnValue({ error: null, isPending: false, mutateAsync })
    mocks.detail.mockReturnValue({
      data: {
        ...detail,
        run: { ...run, status: 'accepted', active_plan_revision_id: null },
        active_spec: {
          ...detail.active_spec!,
          spec: {
            ...detail.active_spec!.spec,
            delivery_flow: {
              mode: 'direct',
              rationale: 'One low-risk repository boundary.',
              confidence: 0.94,
              required_by: [],
            },
          },
        },
        plan_revisions: [],
        active_plan: null,
      },
      isLoading: false,
    })

    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" onRunInChat={onRunInChat} />)
    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))

    expect(screen.queryByRole('button', { name: 'Run plan in chat' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Run implementation in chat' }))

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith('session-1'))
    const prompt = String(onRunInChat.mock.calls[0][0].prompt)
    expect(prompt).toMatch(/^\$easd-implement/)
    expect(prompt).toContain('user-approved direct flow')
    expect(prompt).toContain('no Plan artifact exists')
  })

  it('advances active implementation to Review, then Review to Verify', async () => {
    const onRunInChat = vi.fn()
    const mutateAsync = vi.fn().mockResolvedValue({ ...run, status: 'reviewing' })
    const acceptedPlan = { ...planRevision, status: 'accepted' as const, accepted_at: '2026-08-24T00:01:00Z' }
    mocks.action.mockReturnValue({ error: null, isPending: false, mutateAsync })
    mocks.detail.mockReturnValue({
      data: {
        ...detail,
        run: { ...run, status: 'active', active_plan_revision_id: acceptedPlan.id },
        plan_revisions: [acceptedPlan],
        active_plan: acceptedPlan,
      },
      isLoading: false,
    })
    const rendered = render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" onRunInChat={onRunInChat} />)
    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Run review in chat' }))
    await waitFor(() => expect(onRunInChat).toHaveBeenCalledWith(expect.objectContaining({
      phase: 'review',
      prompt: expect.stringMatching(/^\$easd-review/),
    })))

    onRunInChat.mockClear()
    mutateAsync.mockClear()
    mocks.detail.mockReturnValue({
      data: {
        ...detail,
        run: { ...run, status: 'reviewing', active_plan_revision_id: acceptedPlan.id },
        plan_revisions: [acceptedPlan],
        active_plan: acceptedPlan,
      },
      isLoading: false,
    })
    rendered.rerender(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" onRunInChat={onRunInChat} />)
    fireEvent.click(screen.getByRole('button', { name: 'Run verify in chat' }))
    await waitFor(() => expect(onRunInChat).toHaveBeenCalledWith(expect.objectContaining({
      phase: 'verification',
      prompt: expect.stringMatching(/^\$easd-verify/),
    })))
  })

  it('offers existing or new Coding chat selection for an unbound accepted run', () => {
    mocks.detail.mockReturnValue({
      data: { ...detail, run: { ...run, status: 'accepted', session_id: null } },
      isLoading: false,
    })
    render(
      <EvoAgentSpecsPanel
        workspace="/repo"
        projectId="project-1"
        onRunInChat={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Choose planning chat' }))

    expect(screen.getByText('Choose a Coding chat')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /New Coding chat/ })).toBeInTheDocument()
  })

  it('generates reviewable Scope and Proof without overwriting user edits', async () => {
    const generated = {
      status: 'ready',
      target: 'both',
      generation_id: 'generation-1',
      generated_at: '2026-08-24T00:00:00Z',
      provider: 'test',
      model: 'test:model',
      usage: { input: 100, output: 50 },
      confidence: 0.88,
      rationale: 'Grounded in the API and focused tests.',
      questions: [],
      outcome: 'Clients receive one observable and stable API response.',
      scope: {
        goals: ['Add the bounded endpoint'],
        non_goals: ['Change unrelated routes'],
        source_refs: ['Backend:app/api/routes.py'],
        impact_targets: [{ repository: 'Backend', path: 'app/api/routes.py', module: 'API', reason: 'Owns the endpoint' }],
        constraints: [{ kind: 'compatibility', statement: 'Preserve response shape', source_refs: ['documents/reference/http-api.md'] }],
        used_sources: ['Backend:app/api/routes.py'],
      },
      proof: {
        risk_tier: 'cross_layer',
        criteria: [{ id: 'AC-1', statement: 'The endpoint returns a stable response.', required: true, evidence_policy: { allowed_kinds: ['machine', 'review'], machine_required: true, minimum_passes: 1 } }],
        verification_commands: ['uv run pytest -q tests/api/routes/test_feature.py'],
        independent_review_required: true,
        used_sources: ['Backend:tests/api/routes/test_feature.py'],
      },
      provenance: [{ repository: 'Backend', path: 'app/api/routes.py', kind: 'source', sha256: 'a'.repeat(64), truncated: false, used_for: ['scope'] }],
      base_fingerprint: 'b'.repeat(64),
      context_fingerprint: 'c'.repeat(64),
    }
    mocks.generate.mockReturnValue({
      error: null,
      isPending: false,
      mutateAsync: vi.fn().mockResolvedValue(generated),
      reset: vi.fn(),
    })
    useDraftDetail()
    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" />)
    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Edit specification' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Run title' }), { target: { value: 'Generate a feature spec' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Problem' }), { target: { value: 'The scope is not known yet.' } })
    fireEvent.change(screen.getByRole('textbox', { name: /Intended outcome/ }), { target: { value: '' } })
    expect(screen.getByRole('textbox', { name: /Intended outcome/ })).toHaveValue('')
    fireEvent.click(screen.getByRole('button', { name: 'Generate Outcome, Scope & Proof' }))

    expect(await screen.findByText('Outcome, Scope & Proof proposal')).toBeInTheDocument()
    expect(screen.getByText('6 changed fields · exact before/after')).toBeInTheDocument()
    expect(screen.getByText('4 changed fields · exact before/after')).toBeInTheDocument()
    const goals = screen.getByRole('textbox', { name: /Goals/ })
    fireEvent.change(goals, { target: { value: 'Keep my edited goal' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply Outcome & Scope draft' }))
    expect(goals).toHaveValue('Keep my edited goal')
    expect(screen.getByText(/Outcome or Scope changed after generation/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Replace edited Outcome & Scope' }))
    expect(goals).toHaveValue('Add the bounded endpoint')
    expect(screen.getByRole('textbox', { name: /Intended outcome/ })).toHaveValue('Clients receive one observable and stable API response.')
    expect(screen.getByText('Independent review required')).toBeInTheDocument()
  })

  it('loads additional Coding chats from the paginated picker', () => {
    const fetchNextPage = vi.fn()
    mocks.detail.mockReturnValue({
      data: { ...detail, run: { ...run, status: 'accepted', session_id: null } },
      isLoading: false,
    })
    mocks.projectSessions.mockReturnValue({
      data: {
        pages: [{
          data: [{ id: 'chat-1', title: 'Existing Coding chat', running: false }],
        }],
      },
      isLoading: false,
      error: null,
      hasNextPage: true,
      isFetchingNextPage: false,
      fetchNextPage,
    })
    render(
      <EvoAgentSpecsPanel
        workspace="/repo"
        projectId="project-1"
        onRunInChat={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Choose planning chat' }))

    expect(screen.getByRole('button', { name: /Existing Coding chat/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Load more chats' }))
    expect(fetchNextPage).toHaveBeenCalledOnce()
  })

  it('binds clarification answers to stable question IDs', async () => {
    const mutateAsync = vi.fn()
      .mockResolvedValueOnce({
        status: 'needs_clarification',
        target: 'both',
        generation_id: 'generation-question',
        generated_at: '2026-08-24T00:00:00Z',
        provider: 'test',
        model: 'test:model',
        usage: null,
        confidence: 0.4,
        rationale: 'Product behavior is ambiguous.',
        questions: [{ id: 'Q-BEHAVIOR', question: 'Which behavior is authoritative?', reason: 'Two implementations disagree.', required: true }],
        outcome: null,
        scope: null,
        proof: null,
        provenance: [],
        base_fingerprint: 'b'.repeat(64),
        context_fingerprint: 'c'.repeat(64),
      })
      .mockResolvedValueOnce({
        status: 'ready',
        target: 'both',
        generation_id: 'generation-ready',
        generated_at: '2026-08-24T00:01:00Z',
        provider: 'test',
        model: 'test:model',
        usage: null,
        confidence: 0.9,
        rationale: 'Intent clarified.',
        questions: [],
        outcome: 'The stable API remains authoritative.',
        scope: null,
        proof: null,
        provenance: [],
        base_fingerprint: 'd'.repeat(64),
        context_fingerprint: 'e'.repeat(64),
      })
    mocks.generate.mockReturnValue({ error: null, isPending: false, mutateAsync, reset: vi.fn() })
    useDraftDetail()
    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" />)
    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Edit specification' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Run title' }), { target: { value: 'Clarify behavior' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Problem' }), { target: { value: 'Two behaviors disagree.' } })
    fireEvent.change(screen.getByRole('textbox', { name: /Intended outcome/ }), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate Outcome, Scope & Proof' }))
    fireEvent.change(await screen.findByRole('textbox', { name: /Which behavior is authoritative/ }), { target: { value: 'Keep the stable API.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate with answers' }))

    expect(mutateAsync).toHaveBeenLastCalledWith(expect.objectContaining({
      request: expect.objectContaining({
        intent: { title: 'Clarify behavior', problem: 'Two behaviors disagree.', outcome: undefined },
        clarifications: [{ question: 'Which behavior is authoritative?', answer: 'Keep the stable API.' }],
      }),
    }))
  })

  it('regenerates Scope without discarding the existing Proof proposal', async () => {
    const metadata = {
      generated_at: '2026-08-24T00:00:00Z',
      provider: 'test',
      model: 'test:model',
      usage: null,
      confidence: 0.9,
      rationale: 'Grounded proposal.',
      questions: [],
      provenance: [],
      base_fingerprint: 'b'.repeat(64),
      context_fingerprint: 'c'.repeat(64),
    }
    const proof = {
      risk_tier: 'standard',
      criteria: [{ id: 'AC-1', statement: 'Proof remains after Scope regeneration.', required: true, evidence_policy: { allowed_kinds: ['machine'], machine_required: true, minimum_passes: 1 } }],
      verification_commands: ['uv run pytest -q'],
      independent_review_required: false,
      used_sources: [],
    }
    const mutateAsync = vi.fn()
      .mockResolvedValueOnce({ ...metadata, status: 'ready', target: 'both', generation_id: 'generation-both', outcome: 'Initial outcome', scope: { goals: ['Initial goal'], non_goals: [], source_refs: [], impact_targets: [], constraints: [], used_sources: [] }, proof })
      .mockResolvedValueOnce({ ...metadata, status: 'ready', target: 'scope', generation_id: 'generation-scope', outcome: 'Regenerated outcome', scope: { goals: ['Regenerated goal'], non_goals: [], source_refs: [], impact_targets: [], constraints: [], used_sources: [] }, proof: null })
    mocks.generate.mockReturnValue({ error: null, isPending: false, mutateAsync, reset: vi.fn() })
    useDraftDetail()
    render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" />)
    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Edit specification' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Run title' }), { target: { value: 'Partial regenerate' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Problem' }), { target: { value: 'Scope needs refinement.' } })
    fireEvent.change(screen.getByRole('textbox', { name: /Intended outcome/ }), { target: { value: 'Proof remains stable.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate Outcome, Scope & Proof' }))
    await screen.findByText('Outcome, Scope & Proof proposal')
    fireEvent.click(screen.getAllByRole('button', { name: 'Regenerate' })[0])

    expect(await screen.findByText(/Regenerated goal/)).toBeInTheDocument()
    expect(screen.getByText(/Regenerated outcome/)).toBeInTheDocument()
    expect(screen.getByText(/Proof remains after Scope regeneration/)).toBeInTheDocument()
  })

  it('renders generation cancel and retry states', () => {
    const reset = vi.fn()
    mocks.generate.mockReturnValue({
      error: new Error('Grounding provider unavailable'),
      isPending: false,
      mutateAsync: vi.fn(),
      reset,
    })
    useDraftDetail()
    const { rerender } = render(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" />)
    fireEvent.click(screen.getByRole('button', { name: /EASD feature/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Edit specification' }))
    expect(screen.getByText('Generation failed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()

    mocks.generate.mockReturnValue({ error: null, isPending: true, mutateAsync: vi.fn(), reset })
    rerender(<EvoAgentSpecsPanel workspace="/repo" projectId="project-1" sessionId="session-1" />)
    expect(screen.getAllByRole('button', { name: 'Cancel' })).toHaveLength(2)
    expect(screen.getByText('Generating…')).toBeInTheDocument()
  })
})
