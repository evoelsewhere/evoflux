import { useMemo, useState } from 'react'
import { BrainCircuit, Boxes, LockKeyhole, RotateCcw } from 'lucide-react'

import type { ManagedResourceProvider } from '@/api/types'
import { ApiValidationError } from '@/api/client'
import {
  useRegistryQuery,
  useMcpServersQuery,
  useUpdateAgentRuntimeSettingsMutation,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { ModelCombobox } from '@/components/settings/AgentForm'
import {
  SettingsGroup,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { MultiSelect, type MultiSelectOption } from '@/components/settings/MultiSelect'
import { PROVIDER_MODEL_PLACEHOLDER } from '@/lib/model-settings'

interface ManagedAgentRuntimeModelProps {
  name: string
  provider: ManagedResourceProvider
  effectiveModel: string | null | undefined
  bundleModel: string | null
  modelOverride: string | null
  extraTools?: string[]
  extraSkills?: string[]
  extraMcp?: string[]
}

export function ManagedAgentRuntimeModel({
  name,
  provider,
  effectiveModel,
  bundleModel,
  modelOverride,
  extraTools = [],
  extraSkills = [],
  extraMcp = [],
}: ManagedAgentRuntimeModelProps) {
  const registry = useRegistryQuery()
  const mcpServers = useMcpServersQuery()
  const updateMutation = useUpdateAgentRuntimeSettingsMutation()
  const push = useToastStore((state) => state.push)
  const inheritedModel =
    bundleModel && bundleModel !== PROVIDER_MODEL_PLACEHOLDER ? bundleModel : ''
  const sourceModel = modelOverride ?? inheritedModel
  const [selectedModel, setSelectedModel] = useState(sourceModel)
  const [selectedTools, setSelectedTools] = useState(extraTools)
  const [selectedSkills, setSelectedSkills] = useState(extraSkills)
  const [selectedMcp, setSelectedMcp] = useState(extraMcp)
  const modelOptions = useMemo(() => registry.data?.models ?? [], [registry.data])
  const toolOptions = useMemo<MultiSelectOption[]>(
    () =>
      registry.data?.tools.map((item) => ({
        value: item.name,
        label: item.name,
        description: item.description,
      })) ?? [],
    [registry.data?.tools],
  )
  const skillOptions = useMemo<MultiSelectOption[]>(
    () =>
      registry.data?.skills.map((item) => ({
        value: item.name,
        label: item.display_name || item.name,
        description: item.short_description || item.description,
      })) ?? [],
    [registry.data?.skills],
  )
  const mcpOptions = useMemo<MultiSelectOption[]>(
    () =>
      mcpServers.data?.servers.map((item) => ({
        value: item.name,
        label: item.name,
        description: `${item.transport} · ${item.state}`,
      })) ?? [],
    [mcpServers.data?.servers],
  )
  const dirty =
    selectedModel !== sourceModel ||
    !sameValues(selectedTools, extraTools) ||
    !sameValues(selectedSkills, extraSkills) ||
    !sameValues(selectedMcp, extraMcp)
  const canSave = Boolean(selectedModel) && dirty && !updateMutation.isPending

  const handleSave = async () => {
    if (!canSave) return
    const localModel =
      modelOverride !== null || selectedModel !== inheritedModel ? selectedModel : null
    try {
      await updateMutation.mutateAsync({
        name,
        model: localModel,
        extraTools: selectedTools,
        extraSkills: selectedSkills,
        extraMcp: selectedMcp,
      })
      push({
        tone: 'success',
        title: 'Local additions updated',
        description: `${name} keeps its managed base and applies these additions from its next safe turn.`,
      })
    } catch (error) {
      push({
        tone: 'error',
        title: 'Model update failed',
        description:
          error instanceof ApiValidationError ? error.message : String(error),
      })
    }
  }

  const handleReset = async () => {
    try {
      await updateMutation.mutateAsync({
        name,
        model: null,
        extraTools: selectedTools,
        extraSkills: selectedSkills,
        extraMcp: selectedMcp,
      })
      setSelectedModel(inheritedModel)
      push({
        tone: 'success',
        title: 'Runtime model reset',
        description: inheritedModel
          ? `Using the ${provider.project_name} bundle default again.`
          : 'Choose a model before this Agent can run on this installation.',
      })
    } catch (error) {
      push({
        tone: 'error',
        title: 'Model reset failed',
        description:
          error instanceof ApiValidationError ? error.message : String(error),
      })
    }
  }

  return (
    <SettingsGroup
      title="Local runtime"
      description={`Choose the model and add local capabilities. ${provider.project_name} controls the immutable base; local values can only be unioned onto it.`}
      actions={
        modelOverride ? (
          <span className="rounded-full border border-(--color-accent)/25 bg-(--color-accent-soft) px-2 py-1 text-[10px] font-medium text-(--color-accent)">
            Local override
          </span>
        ) : null
      }
    >
      <SettingsRow
        label={
          <span className="inline-flex items-center gap-2">
            <BrainCircuit size={15} aria-hidden="true" /> Execution model
          </span>
        }
        description="The model is installation-local. Managed prompt and scalar policy stay locked."
        stacked
        control={
          <div className="space-y-3">
            {registry.isLoading ? (
              <Skeleton className="h-11 w-full rounded-lg md:h-9" />
            ) : (
              <ModelCombobox
                value={selectedModel}
                onChange={setSelectedModel}
                options={modelOptions}
                placeholder="Choose a configured model"
                disabled={updateMutation.isPending || registry.isError}
              />
            )}
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 items-start gap-2 text-[11px] leading-relaxed text-(--color-text-muted)">
                <LockKeyhole
                  size={12}
                  className="mt-0.5 shrink-0"
                  aria-hidden="true"
                />
                <span>
                  {bundleModel === PROVIDER_MODEL_PLACEHOLDER
                    ? 'This bundle requires each installation to choose a model.'
                    : `Bundle default: ${bundleModel ?? 'not set'}`}
                  {effectiveModel && effectiveModel !== PROVIDER_MODEL_PLACEHOLDER
                    ? ` Current runtime: ${effectiveModel}.`
                    : ''}
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {modelOverride && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => void handleReset()}
                    disabled={updateMutation.isPending}
                  >
                    <RotateCcw size={13} aria-hidden="true" /> Reset
                  </Button>
                )}
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void handleSave()}
                  disabled={!canSave}
                >
                  {updateMutation.isPending ? 'Saving…' : 'Use this model'}
                </Button>
              </div>
            </div>
          </div>
        }
      />
      <SettingsRow
        label={
          <span className="inline-flex items-center gap-2">
            <Boxes size={15} aria-hidden="true" /> Additive capabilities
          </span>
        }
        description="Add tools, skills, or MCP servers available on this installation. Removing a local chip never removes anything supplied by EvoFlux or Conductor."
        stacked
        control={
          <div className="grid gap-4">
            <LocalAdditionField label="Extra tools">
              <MultiSelect
                options={toolOptions}
                value={selectedTools}
                onChange={setSelectedTools}
                placeholder="Add local tools…"
              />
            </LocalAdditionField>
            <LocalAdditionField label="Extra skills">
              <MultiSelect
                options={skillOptions}
                value={selectedSkills}
                onChange={setSelectedSkills}
                placeholder="Add local skills…"
              />
            </LocalAdditionField>
            <LocalAdditionField label="Extra MCP servers">
              <MultiSelect
                options={mcpOptions}
                value={selectedMcp}
                onChange={setSelectedMcp}
                placeholder="Add local MCP servers…"
              />
            </LocalAdditionField>
            <div className="flex justify-end">
              <Button
                type="button"
                size="sm"
                onClick={() => void handleSave()}
                disabled={!canSave}
              >
                {updateMutation.isPending ? 'Saving…' : 'Save local additions'}
              </Button>
            </div>
          </div>
        }
      />
    </SettingsGroup>
  )
}

function LocalAdditionField({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <label className="grid gap-1.5 text-xs font-medium text-(--color-text)">
      {label}
      {children}
    </label>
  )
}

function sameValues(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index])
}
