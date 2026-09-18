import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AsddChangeDetail, AsddChangeList, AsddSetupResponse } from '@/api/types'
import { AgentSpecsPanel } from '@/components/AgentSpecsPanel'

const mocks = vi.hoisted(() => ({
  setup: vi.fn(),
  changes: vi.fn(),
  detail: vi.fn(),
  spec: vi.fn(),
  approve: vi.fn(),
  startAction: vi.fn(),
  markReady: vi.fn(),
  autopilot: vi.fn(),
  archive: vi.fn(),
  remove: vi.fn(),
  create: vi.fn(),
  createArgs: vi.fn(),
  initialize: vi.fn(),
}))

vi.mock('@/queries', () => ({
  useAsddSetupQuery: () => mocks.setup(),
  useAsddChangesQuery: () => mocks.changes(),
  useAsddChangeQuery: () => mocks.detail(),
  useAsddSpecQuery: () => mocks.spec(),
  useApproveAsddArtifactMutation: () => mocks.approve(),
  useStartAsddActionMutation: () => mocks.startAction(),
  useMarkAsddChangeReadyMutation: () => mocks.markReady(),
  useSetAsddAutopilotMutation: () => mocks.autopilot(),
  useArchiveAsddChangeMutation: () => mocks.archive(),
  useDeleteAsddChangeMutation: () => mocks.remove(),
  // Records which workspace each render asked the mutation to target, so a
  // test can tell the "New change" form actually redirected the create call
  // to the repository selected in its dropdown.
  useCreateAsddChangeMutation: (workspace: string, projectId?: string | null) => {
    mocks.createArgs(workspace, projectId)
    return mocks.create()
  },
  useInitializeAsddSetupMutation: () => mocks.initialize(),
}))

vi.mock('@/utils/LazyMarkdownBlock', () => ({
  LazyMarkdownBlock: ({ content }: { content: string }) => <div>{content}</div>,
}))

function repository(overrides: Partial<AsddSetupResponse['repositories'][number]> = {}) {
  return {
    path: '/repo',
    name: 'repo',
    display_name: null,
    status: 'ready' as const,
    installed: true,
    manifest_path: '.evoflux/asdd/config.json',
    data_directory: 'documents/asdd',
    data_path: '/repo/documents/asdd',
    rules_path: '.evoflux/asdd/RULES.md',
    skills_path: '.evoflux/skills',
    skill_names: ['asdd-propose', 'asdd-specify'],
    missing_skills: [],
    missing_catalogue_files: [],
    issue: null,
    ...overrides,
  }
}

function setupResponse(overrides: Partial<AsddSetupResponse> = {}): AsddSetupResponse {
  const repositories = overrides.repositories ?? [repository()]
  return {
    scope: 'workspace',
    workspace: '/repo',
    project_id: null,
    workspace_ready: repositories.some(
      (item) => item.installed && item.path === (overrides.workspace ?? '/repo'),
    ),
    ready: repositories.every((item) => item.installed),
    repository_count: repositories.length,
    installed_count: repositories.filter((item) => item.installed).length,
    ...overrides,
    repositories,
  }
}

const change: AsddChangeList['changes'][number] = {
  change_id: 'add-user-auth',
  repository: '/repo',
  title: 'Add user authentication',
  status: 'specified',
  risk: 'standard',
  capabilities: ['user-auth'],
  delta_capabilities: ['user-auth'],
  approvals: {
    proposal: '2026-09-16T08:00:00Z',
    specs: null,
    design: null,
    tasks: null,
  },
  auto_approvals: { proposal: null, specs: null, design: null, tasks: null },
  autopilot: false,
  hold: null,
  tasks_total: 0,
  tasks_done: 0,
  evidence_count: 0,
  review_recorded: false,
  created: '2026-09-16T08:00:00Z',
  path: 'documents/asdd/changes/add-user-auth',
}

const detail: AsddChangeDetail = {
  change,
  rail: {
    status: 'specified',
    primary_action: 'approve_specs',
    actions: [
      { id: 'approve_specs', label: 'Approve specs', state: 'available', blockers: [] },
      { id: 'draft_specs', label: 'Redraft in chat', state: 'available', blockers: [] },
      { id: 'cancel', label: 'Cancel change', state: 'available', blockers: [] },
    ],
    required_approvals: ['proposal', 'specs', 'tasks'],
    problems: [],
    autopilot: false,
    hold: null,
    human_only_gates: [],
  },
  proposal: '## Why\n\nSessions own too much.',
  design: null,
  tasks: null,
  deltas: [
    {
      capability: 'user-auth',
      added: ['Slug identity'],
      modified: [],
      removed: [],
      problems: [],
      body: '## ADDED Requirements\n\n### Requirement: Slug identity',
    },
  ],
  evidence: [],
}

function idle<T>(data: T) {
  return { data, isLoading: false, isError: false, error: null }
}

function mutation(extra: Record<string, unknown> = {}) {
  return { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false, error: null, variables: undefined, ...extra }
}

beforeEach(() => {
  // SegmentedControl reads the motion preference on mount.
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  })
  mocks.setup.mockReturnValue(idle(setupResponse()))
  mocks.changes.mockReturnValue(idle({
    workspace: '/repo',
    project_id: null,
    changes: [change],
    archived: [],
    capabilities: ['user-auth'],
  }))
  mocks.detail.mockReturnValue({ data: undefined, isLoading: false, isError: false, error: null })
  mocks.spec.mockReturnValue(idle({
    capability: 'user-auth',
    purpose: 'Behavior contracted for `user-auth`.',
    requirements: [{ name: 'Slug identity', statement: 'The system SHALL …', scenarios: [] }],
    path: 'documents/asdd/specs/user-auth/spec.md',
    body: '## Purpose\n\nBehavior contracted for `user-auth`.',
  }))
  for (const key of ['approve', 'startAction', 'markReady', 'autopilot', 'archive', 'remove', 'create', 'initialize'] as const) {
    mocks[key].mockReturnValue(mutation())
  }
})

function panel(props: Partial<Parameters<typeof AgentSpecsPanel>[0]> = {}) {
  return render(<AgentSpecsPanel workspace="/repo" {...props} />)
}

describe('Agent Spec-Driven setup', () => {
  it('asks for installation while this workspace is not ready', () => {
    mocks.setup.mockReturnValue(idle(setupResponse({
      repositories: [
        repository({ status: 'not_initialized', installed: false }),
        repository({ path: '/other', name: 'other', status: 'not_initialized', installed: false }),
      ],
    })))

    panel()

    expect(screen.getByRole('heading', { name: 'Set up Agent Spec-Driven' })).toBeInTheDocument()
    expect(screen.getByText('0/2 ready')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Set up 2 repositories/ })).toBeInTheDocument()
  })

  it('opens a ready workspace even when a sibling repository is not', () => {
    // A catalogue belongs to one repository. Gating on the whole project
    // locked a set-up repository behind a sibling nobody had installed.
    mocks.setup.mockReturnValue(idle(setupResponse({
      repositories: [
        repository(),
        repository({ path: '/other', name: 'other', status: 'not_initialized', installed: false }),
      ],
    })))

    panel()

    expect(screen.queryByRole('heading', { name: 'Set up Agent Spec-Driven' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Add user authentication/ })).toBeInTheDocument()
  })

  it('names what an unhealthy repository is missing', () => {
    mocks.setup.mockReturnValue(idle(setupResponse({
      repositories: [repository({
        status: 'upgrade_required',
        installed: false,
        missing_skills: ['asdd-verify'],
        missing_catalogue_files: ['specs/README.md'],
        issue: 'ASDD setup is missing installed files',
      })],
    })))

    panel()

    expect(screen.getByText('Upgrade available')).toBeInTheDocument()
    expect(screen.getByText(/asdd-verify/)).toBeInTheDocument()
    expect(screen.getByText(/specs\/README\.md/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upgrade' })).toBeInTheDocument()
  })
})

describe('Agent Spec-Driven changes', () => {
  it('groups open changes by phase on the board', () => {
    panel()

    const board = screen.getByRole('button', { name: /Add user authentication/ })
    expect(board).toBeInTheDocument()
    expect(screen.getByText('add-user-auth')).toBeInTheDocument()
  })

  it('opens a change and shows its delta and approval gates', () => {
    mocks.detail.mockReturnValue(idle(detail))

    panel()
    fireEvent.click(screen.getByRole('button', { name: /Add user authentication/ }))

    expect(screen.getByText('documents/asdd/changes/add-user-auth')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve specs' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^Specs \(1\)$/ }))
    expect(screen.getByText('+1 added')).toBeInTheDocument()
  })

  it('approves the artifact the rail names', () => {
    const approve = mutation()
    mocks.approve.mockReturnValue(approve)
    mocks.detail.mockReturnValue(idle(detail))

    panel()
    fireEvent.click(screen.getByRole('button', { name: /Add user authentication/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Approve specs' }))

    expect(approve.mutate).toHaveBeenCalledWith({ artifact: 'specs' })
  })

  it('hands a phase prompt to the chat instead of binding a session', () => {
    const onRunInChat = vi.fn()
    const startAction = mutation({
      mutate: vi.fn((_action: string, options?: { onSuccess?: (result: unknown) => void }) => {
        options?.onSuccess?.({
          change,
          rail: detail.rail,
          prompt: '$asdd-specify\n\nWork on ASDD change `add-user-auth`.',
          skill: 'asdd-specify',
        })
      }),
    })
    mocks.startAction.mockReturnValue(startAction)
    mocks.detail.mockReturnValue(idle(detail))

    panel({ onRunInChat })
    fireEvent.click(screen.getByRole('button', { name: /Add user authentication/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Redraft in chat' }))

    expect(startAction.mutate).toHaveBeenCalledWith('draft_specs', expect.anything())
    expect(onRunInChat).toHaveBeenCalledWith(expect.objectContaining({
      changeId: 'add-user-auth',
      skill: 'asdd-specify',
    }))
  })

  it('disables a blocked action and explains why', () => {
    mocks.detail.mockReturnValue(idle({
      ...detail,
      rail: {
        ...detail.rail,
        actions: [
          {
            id: 'approve_specs',
            label: 'Approve specs',
            state: 'blocked',
            blockers: [{ code: 'capability_without_delta', message: 'The proposal names capabilities with no delta: audit-log' }],
          },
        ],
      },
    }))

    panel()
    fireEvent.click(screen.getByRole('button', { name: /Add user authentication/ }))

    expect(screen.getByRole('button', { name: 'Approve specs' })).toBeDisabled()
    expect(within(screen.getByRole('alert')).getByText(/audit-log/)).toBeInTheDocument()
  })

  it('reports a status that disagrees with the change folder', () => {
    mocks.detail.mockReturnValue(idle({
      ...detail,
      rail: {
        ...detail.rail,
        problems: [{ code: 'approval_missing', message: '`status: specified` is past the proposal gate, but `approvals.proposal` is empty' }],
      },
    }))

    panel()
    fireEvent.click(screen.getByRole('button', { name: /Add user authentication/ }))

    expect(screen.getByText('proposal.md disagrees with the change folder')).toBeInTheDocument()
  })
})

describe('Agent Spec-Driven vocabulary', () => {
  it('names a status the way the rail and the board name its phase', () => {
    // `tasking` read as "tasking" on a card while the rail above it and the
    // board column beside it both called that phase "Plan".
    mocks.changes.mockReturnValue(idle({
      workspace: '/repo',
      project_id: null,
      changes: [{ ...change, status: 'tasking' as const }],
      archived: [],
      capabilities: [],
    }))

    panel()

    expect(screen.getByText('Planning')).toBeInTheDocument()
    expect(screen.queryByText('tasking')).not.toBeInTheDocument()
  })

  it('counts the changes that cannot move without a person', () => {
    mocks.changes.mockReturnValue(idle({
      workspace: '/repo',
      project_id: null,
      changes: [
        change,
        { ...change, change_id: 'b', title: 'B', status: 'ready' as const },
        { ...change, change_id: 'c', title: 'C', status: 'implementing' as const },
      ],
      archived: [],
      capabilities: [],
    }))

    panel()

    expect(screen.getByText('2 waiting')).toBeInTheDocument()
  })
})

describe('Agent Spec-Driven catalogue', () => {
  it('opens the capability spec behind the counts in the header', () => {
    mocks.changes.mockReturnValue(idle({
      workspace: '/repo',
      project_id: null,
      changes: [change],
      archived: ['2026-09-16-add-session-binding'],
      capabilities: ['user-auth'],
    }))

    panel()
    fireEvent.click(screen.getByRole('button', { name: /1 · 1/ }))

    expect(screen.getByRole('heading', { name: 'Catalogue' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /user-auth/ }))

    expect(screen.getByText('documents/asdd/specs/user-auth/spec.md')).toBeInTheDocument()
    expect(screen.getByText('1 requirement')).toBeInTheDocument()
  })

  it('lists the archive by the change that produced it', () => {
    mocks.changes.mockReturnValue(idle({
      workspace: '/repo',
      project_id: null,
      changes: [],
      archived: ['2026-09-16-add-session-binding'],
      capabilities: [],
    }))

    panel()
    fireEvent.click(screen.getByRole('button', { name: /0 · 1/ }))
    fireEvent.click(screen.getByRole('tab', { name: 'Archived' }))

    expect(screen.getByText('add-session-binding')).toBeInTheDocument()
    expect(screen.getByText('2026-09-16')).toBeInTheDocument()
    expect(
      screen.getByText('changes/archive/2026-09-16-add-session-binding/'),
    ).toBeInTheDocument()
  })
})

describe('Agent Spec-Driven artifact tabs', () => {
  it('offers the design tab to a change whose tier requires one', () => {
    // The rail says this change needs a design; hiding the tab until the file
    // existed meant the one change that needed it could not open it.
    mocks.detail.mockReturnValue(idle({
      ...detail,
      change: { ...change, risk: 'critical' as const, status: 'designing' as const },
    }))

    panel()
    fireEvent.click(screen.getByRole('button', { name: /Add user authentication/ }))

    fireEvent.click(screen.getByRole('button', { name: 'Design' }))
    expect(screen.getByText('This change has no design document.')).toBeInTheDocument()
  })

  it('offers the evidence tab while a change is being verified', () => {
    mocks.detail.mockReturnValue(idle({
      ...detail,
      change: { ...change, status: 'verifying' as const },
    }))

    panel()
    fireEvent.click(screen.getByRole('button', { name: /Add user authentication/ }))

    fireEvent.click(screen.getByRole('button', { name: /^Evidence \(0\)$/ }))
    expect(screen.getByText('Nothing has been recorded under evidence/ yet.')).toBeInTheDocument()
  })

  it('keeps task progress in the header and on the tab', () => {
    mocks.detail.mockReturnValue(idle({
      ...detail,
      change: { ...change, status: 'implementing' as const, tasks_total: 6, tasks_done: 4 },
      tasks: '## 1. Filter state\n\n- [x] Done',
    }))

    panel()
    fireEvent.click(screen.getByRole('button', { name: /Add user authentication/ }))

    expect(screen.getByText('4/6 tasks')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Tasks \(4\/6\)$/ })).toBeInTheDocument()
  })
})

describe('Agent Spec-Driven new change', () => {
  function openForm() {
    panel()
    fireEvent.click(screen.getByRole('button', { name: /^New/ }))
  }

  it('shows the folder a title will produce before creating it', () => {
    openForm()
    fireEvent.click(screen.getByRole('button', { name: /Set the id, capabilities/ }))
    fireEvent.change(screen.getByPlaceholderText('Add user authentication'), {
      target: { value: 'Add PDF export!!' },
    })

    expect(screen.getByText('changes/add-pdf-export/')).toBeInTheDocument()
  })

  it('derives a slug from a title written in Vietnamese', () => {
    // The title field was validated as though it were already a slug, so a
    // Vietnamese title could not open a change at all.
    openForm()
    fireEvent.click(screen.getByRole('button', { name: /Set the id, capabilities/ }))
    fireEvent.change(screen.getByPlaceholderText('Add user authentication'), {
      target: { value: 'Đổi tên trường slug' },
    })

    expect(screen.getByText('changes/doi-ten-truong-slug/')).toBeInTheDocument()
  })

  it('asks for an id when a title has no letters to derive one from', () => {
    openForm()
    fireEvent.click(screen.getByRole('button', { name: /Set the id, capabilities/ }))
    fireEvent.change(screen.getByPlaceholderText('Add user authentication'), {
      target: { value: '日本語のタイトル' },
    })

    expect(screen.getByText(/no letters or digits to build an id from/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Create change/ })).toBeDisabled()
  })

  it('sends an explicit id only when the author overrode the derived one', () => {
    const create = mutation()
    mocks.create.mockReturnValue(create)

    openForm()
    fireEvent.change(screen.getByPlaceholderText('Add user authentication'), {
      target: { value: 'Add PDF export' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))
    expect(create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Add PDF export', changeId: undefined }),
      expect.anything(),
    )

    fireEvent.click(screen.getByRole('button', { name: /Set the id, capabilities/ }))
    fireEvent.change(screen.getByPlaceholderText('add-pdf-export'), {
      target: { value: 'pdf-export' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))
    expect(create.mutate).toHaveBeenLastCalledWith(
      expect.objectContaining({ changeId: 'pdf-export' }),
      expect.anything(),
    )
  })
})

describe('Agent Spec-Driven autopilot', () => {
  function withRail(rail: Partial<AsddChangeDetail['rail']>, change: Partial<typeof detail.change> = {}) {
    mocks.detail.mockReturnValue(idle({
      ...detail,
      change: { ...detail.change, ...change },
      rail: { ...detail.rail, ...rail },
    }))
  }

  function open() {
    panel()
    fireEvent.click(screen.getByRole('button', { name: /Add user authentication/ }))
  }

  it('turns autopilot on for the change, not the session', () => {
    const autopilot = mutation()
    mocks.autopilot.mockReturnValue(autopilot)
    withRail({})

    open()
    fireEvent.click(screen.getByRole('button', { name: /Autopilot off/ }))

    expect(autopilot.mutate).toHaveBeenCalledWith(true)
  })

  it('leads with Continue once autopilot is carrying the change', () => {
    withRail({
      autopilot: true,
      primary_action: 'autopilot_continue',
      actions: [
        { id: 'autopilot_continue', label: 'Continue', state: 'available', blockers: [] },
        { id: 'approve_specs', label: 'Approve specs', state: 'available', blockers: [] },
      ],
    }, { autopilot: true })

    open()

    expect(screen.getByRole('button', { name: 'Continue' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Autopilot on/ })).toBeInTheDocument()
    expect(screen.getByText(/Autopilot read the deltas/)).toBeInTheDocument()
  })

  it('puts a hold above the buttons and says what it is waiting on', () => {
    withRail({
      autopilot: true,
      hold: { gate: 'specs', reason: 'The delta removes a requirement two others cite.', raised: null },
    }, { autopilot: true })

    open()

    expect(screen.getByText(/Autopilot stopped for you at the specs gate/)).toBeInTheDocument()
    expect(screen.getByText(/removes a requirement two others cite/)).toBeInTheDocument()
  })

  it('shows which gates a person signed and which autopilot cleared', () => {
    // Both let the change move; only one is a signature, and archiving a
    // critical change depends on telling them apart.
    withRail({
      autopilot: true,
      human_only_gates: ['archive', 'design'],
      required_approvals: ['proposal', 'specs', 'design', 'tasks'],
    }, {
      autopilot: true,
      risk: 'critical',
      approvals: { proposal: '2026-09-16T08:00:00Z', specs: null, design: null, tasks: null },
      auto_approvals: { proposal: null, specs: '2026-09-16T09:00:00Z', design: null, tasks: null },
    })

    open()

    expect(screen.getByTitle(/Approved by you/)).toHaveTextContent('Proposal')
    expect(screen.getByTitle(/Cleared by autopilot/)).toHaveTextContent('Specs')
    // The tier reserves this one, so the chip says so rather than reading as a
    // gate autopilot simply has not reached yet.
    expect(screen.getByTitle(/this tier needs you, not autopilot/)).toHaveTextContent('Design')
  })

  it('marks a held change on the board without opening it', () => {
    mocks.changes.mockReturnValue(idle({
      workspace: '/repo',
      project_id: null,
      changes: [{ ...change, autopilot: true, hold: { gate: 'specs', reason: 'Needs a decision', raised: null } }],
      archived: [],
      capabilities: [],
    }))

    panel()

    expect(screen.getByText('Held')).toBeInTheDocument()
  })
})

describe('Agent Spec-Driven autopilot through the build phases', () => {
  function open(rail: Partial<AsddChangeDetail['rail']>, change: Partial<typeof detail.change> = {}) {
    mocks.detail.mockReturnValue(idle({
      ...detail,
      change: { ...detail.change, ...change },
      rail: { ...detail.rail, ...rail },
    }))
    panel()
    fireEvent.click(screen.getByRole('button', { name: /Add user authentication/ }))
  }

  it('leads implementation with Continue and keeps the manual actions', () => {
    open({
      status: 'implementing',
      autopilot: true,
      primary_action: 'autopilot_continue',
      actions: [
        { id: 'autopilot_continue', label: 'Continue', state: 'available', blockers: [] },
        { id: 'start_implementation', label: 'Run implementation', state: 'available', blockers: [] },
        {
          id: 'start_verification',
          label: 'Run verification',
          state: 'blocked',
          blockers: [{ code: 'tasks_open', message: '4 of 6 tasks are still unchecked' }],
        },
      ],
    }, { status: 'implementing', autopilot: true, tasks_total: 6, tasks_done: 2 })

    expect(screen.getByRole('button', { name: 'Continue' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run implementation' })).toBeEnabled()
    expect(screen.getByText(/Autopilot is working the tasks/)).toBeInTheDocument()
  })

  it('explains a blocked action that is not the primary one', () => {
    // The rail spells out the primary's blockers; a blocked secondary would
    // otherwise be a greyed button with no stated reason.
    open({
      status: 'implementing',
      autopilot: true,
      primary_action: 'autopilot_continue',
      actions: [
        { id: 'autopilot_continue', label: 'Continue', state: 'available', blockers: [] },
        {
          id: 'start_verification',
          label: 'Run verification',
          state: 'blocked',
          blockers: [{ code: 'tasks_open', message: '4 of 6 tasks are still unchecked' }],
        },
      ],
    }, { status: 'implementing', autopilot: true, tasks_total: 6, tasks_done: 2 })

    const blocked = screen.getByRole('button', { name: 'Run verification' })
    expect(blocked).toBeDisabled()
    expect(blocked).toHaveAttribute('title', '4 of 6 tasks are still unchecked')
  })

  it('says autopilot stops at the archive', () => {
    open({
      status: 'ready',
      autopilot: true,
      primary_action: 'archive',
      actions: [{ id: 'archive', label: 'Archive', state: 'available', blockers: [] }],
    }, { status: 'ready', autopilot: true })

    expect(screen.getByRole('button', { name: 'Archive' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Continue' })).not.toBeInTheDocument()
    expect(screen.getByText(/Archiving is yours at every risk tier/)).toBeInTheDocument()
  })
})

describe('Agent Spec-Driven new change form', () => {
  function openForm(props: Partial<Parameters<typeof AgentSpecsPanel>[0]> = {}) {
    panel(props)
    fireEvent.click(screen.getByRole('button', { name: /^New/ }))
  }

  it('asks only for a title, a problem and an outcome', () => {
    // The form used to ask for a risk tier before anything had been read.
    openForm()

    expect(screen.getByPlaceholderText('Add user authentication')).toBeInTheDocument()
    expect(screen.getByText('What is the problem?')).toBeInTheDocument()
    expect(screen.getByText('What should be true when it is done?')).toBeInTheDocument()
    expect(screen.queryByText('Risk tier')).not.toBeInTheDocument()
    expect(screen.queryByText('Change id')).not.toBeInTheDocument()
  })

  it('sends the problem and the outcome so the proposal starts from them', () => {
    const create = mutation()
    mocks.create.mockReturnValue(create)

    openForm()
    fireEvent.change(screen.getByPlaceholderText('Add user authentication'), {
      target: { value: 'Export notes to PDF' },
    })
    fireEvent.change(screen.getByPlaceholderText(/copying the text out by hand/), {
      target: { value: 'Readers copy notes by hand.' },
    })
    fireEvent.change(screen.getByPlaceholderText(/One command writes every note/), {
      target: { value: 'One command writes a PDF.' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))

    expect(create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Export notes to PDF',
        problem: 'Readers copy notes by hand.',
        outcome: 'One command writes a PDF.',
        risk: undefined,
      }),
      expect.anything(),
    )
  })

  it('leaves the tier to the propose phase unless someone overrides it', () => {
    const create = mutation()
    mocks.create.mockReturnValue(create)

    openForm()
    fireEvent.change(screen.getByPlaceholderText('Add user authentication'), {
      target: { value: 'Rotate keys' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Set the id, capabilities/ }))

    expect(screen.getByText(/the propose phase will choose one/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))
    expect(create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ risk: undefined }),
      expect.anything(),
    )
  })

  it('has no repository picker when the project has only one repository', () => {
    openForm()

    expect(screen.queryByText('Repository')).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Target repository' })).not.toBeInTheDocument()
  })

  it('offers a repository picker limited to the installed repositories of a multi-repo project', async () => {
    mocks.setup.mockReturnValue(idle(setupResponse({
      project_id: 'project-1',
      repositories: [
        repository({ path: '/repo', name: 'repo' }),
        repository({ path: '/other', name: 'other', display_name: 'Other service' }),
        // Not installed yet — cannot receive a change, so it must not appear.
        repository({ path: '/third', name: 'third', status: 'not_initialized', installed: false }),
      ],
    })))

    openForm({ projectId: 'project-1' })

    expect(screen.getByText('Repository')).toBeInTheDocument()
    expect(screen.getByText(/2 repositories set up/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('combobox', { name: 'Target repository' }))
    expect(await screen.findByRole('option', { name: 'repo' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Other service' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'third' })).not.toBeInTheDocument()
  })

  it('creates the change in the repository chosen from the picker, not the default one', async () => {
    const create = mutation()
    mocks.create.mockReturnValue(create)
    mocks.setup.mockReturnValue(idle(setupResponse({
      project_id: 'project-1',
      repositories: [
        repository({ path: '/repo', name: 'repo' }),
        repository({ path: '/other', name: 'other', display_name: 'Other service' }),
      ],
    })))

    openForm({ projectId: 'project-1' })
    fireEvent.click(screen.getByRole('combobox', { name: 'Target repository' }))
    const option = await screen.findByRole('option', { name: 'Other service' })
    fireEvent.mouseMove(option)
    fireEvent.pointerDown(option, { pointerType: 'mouse' })
    fireEvent.mouseUp(option)
    fireEvent.click(option)
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Target repository' })).toHaveTextContent('Other service'),
    )

    fireEvent.change(screen.getByPlaceholderText('Add user authentication'), {
      target: { value: 'Export notes to PDF' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Create change/ }))

    expect(mocks.createArgs).toHaveBeenLastCalledWith('/other', 'project-1')
    expect(create.mutate).toHaveBeenCalled()
  })
})

describe('Agent Spec-Driven tolerates a hand-edited status', () => {
  it('renders a status this build has never seen', () => {
    // `status` is hand-editable and the server reports an unrecognised value
    // rather than refusing to serve the change. Enforcing the union here would
    // move the same failure from the API into the panel.
    mocks.changes.mockReturnValue(idle({
      workspace: '/repo',
      project_id: null,
      changes: [{ ...change, status: 'wibbling' }],
      archived: [],
      capabilities: [],
    }))

    panel()

    expect(screen.getByText('wibbling')).toBeInTheDocument()
  })

  it('says so on the rail rather than showing an empty phase', () => {
    mocks.detail.mockReturnValue(idle({
      ...detail,
      change: { ...detail.change, status: 'wibbling' },
      rail: {
        ...detail.rail,
        status: 'wibbling',
        primary_action: null,
        actions: [],
        problems: [{ code: 'unknown_status', message: '`status: wibbling` is not one of: drafting, …' }],
      },
    }))

    panel()
    fireEvent.click(screen.getByRole('button', { name: /Add user authentication/ }))

    expect(screen.getByText(/is not a phase this build knows/)).toBeInTheDocument()
    expect(screen.getByText(/is not one of/)).toBeInTheDocument()
  })
})
