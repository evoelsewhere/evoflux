import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ManagedAgentRuntimeModel } from '@/components/settings/ManagedAgentRuntimeModel'

const mocks = vi.hoisted(() => ({
  mutateAsync: vi.fn(),
  push: vi.fn(),
}))

vi.mock('@/queries', () => ({
  useRegistryQuery: () => ({
    data: {
      models: [
        {
          id: 'xiaomi:mimo-v2.5',
          provider: 'xiaomi',
          model: 'mimo-v2.5',
          vision: false,
        },
        {
          id: 'anthropic:claude-sonnet-5',
          provider: 'anthropic',
          model: 'claude-sonnet-5',
          vision: true,
        },
      ],
      tools: [],
      skills: [],
    },
    isLoading: false,
    isError: false,
  }),
  useMcpServersQuery: () => ({ data: { servers: [] } }),
  useUpdateAgentRuntimeSettingsMutation: () => ({
    isPending: false,
    mutateAsync: mocks.mutateAsync,
  }),
}))

vi.mock('@/components/settings/AgentForm', () => ({
  ModelCombobox: ({
    value,
    onChange,
    options,
  }: {
    value: string
    onChange: (value: string) => void
    options: { id: string }[]
  }) => (
    <select
      aria-label="Execution model selector"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">Choose a model</option>
      {options.map((option) => (
        <option key={option.id} value={option.id}>
          {option.id}
        </option>
      ))}
    </select>
  ),
}))

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector: (state: { push: typeof mocks.push }) => unknown) =>
    selector({ push: mocks.push }),
}))

const provider = {
  project_id: 'project-1',
  project_name: 'Evolint',
  resource_id: 'agent-1',
  version_id: 'version-1',
  version: '1.0.0',
  applied_version_id: 'version-1',
  applied_version: '1.0.0',
  release_channel: 'published' as const,
  observed_state: 'in_sync' as const,
}

describe('ManagedAgentRuntimeModel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.mutateAsync.mockResolvedValue({})
  })

  it('keeps managed source locked while saving an installation model', async () => {
    render(
      <ManagedAgentRuntimeModel
        name="youtube-comment-analyst"
        provider={provider}
        effectiveModel="__PROVIDER_MODEL__"
        bundleModel="__PROVIDER_MODEL__"
        modelOverride={null}
      />,
    )

    expect(screen.getByText(/managed prompt and scalar policy stay locked/i)).toBeVisible()
    expect(screen.getByText(/requires each installation to choose a model/i)).toBeVisible()

    fireEvent.change(screen.getByRole('combobox', { name: 'Execution model selector' }), {
      target: { value: 'xiaomi:mimo-v2.5' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Use this model' }))

    await waitFor(() =>
      expect(mocks.mutateAsync).toHaveBeenCalledWith({
        name: 'youtube-comment-analyst',
        model: 'xiaomi:mimo-v2.5',
        extraTools: [],
        extraSkills: [],
        extraMcp: [],
      }),
    )
  })

  it('can reset an existing local override to the bundle model', async () => {
    render(
      <ManagedAgentRuntimeModel
        name="youtube-comment-analyst"
        provider={provider}
        effectiveModel="anthropic:claude-sonnet-5"
        bundleModel="xiaomi:mimo-v2.5"
        modelOverride="anthropic:claude-sonnet-5"
      />,
    )

    expect(screen.getByText('Local override')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))

    await waitFor(() =>
      expect(mocks.mutateAsync).toHaveBeenCalledWith({
        name: 'youtube-comment-analyst',
        model: null,
        extraTools: [],
        extraSkills: [],
        extraMcp: [],
      }),
    )
  })
})
