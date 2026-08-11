/** Compact session model controls shared by the Work, Coding, and AIM composers. */

import { useState } from 'react'
import { ChevronDown, Zap } from 'lucide-react'
import { useRegistryQuery } from '@/queries'
import { cn } from '@/lib/utils'
import {
  buildThinkingOptions,
  reconcileThinkingLevel,
  shortModelName,
  supportsFastMode,
  thinkingColor,
  type ThinkingOption,
} from '@/lib/model-settings'
import { DiscreteSlider } from '@/components/ui/discrete-slider'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { AgentInfoPopover } from './AgentInfoPopover'
import { ProviderBrandIcon } from '@/components/providers/ProviderBrandIcon'
import { ModelOptions } from '@/components/model-picker/ModelOptions'

const CONTROL_CLASS =
  'flex h-7 min-w-0 items-center rounded-md px-2 text-xs text-(--color-text-muted) outline-none transition-colors duration-(--motion-fast) hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:ring-2 focus-visible:ring-(--color-accent)/30'

function ThinkingEffortButtons({
  options,
  currentIndex,
  fastMode,
  onSelectIndex,
}: {
  options: ThinkingOption[]
  currentIndex: number
  fastMode: boolean
  onSelectIndex: (index: number) => void
}) {
  return (
    <div role="radiogroup" aria-label="Thinking effort" className="grid grid-cols-2 gap-1">
      {options.map((option, index) => {
        const selected = index === currentIndex
        return (
          <button
            key={option.value ?? '__default__'}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onSelectIndex(index)}
            className={cn(
              'flex h-8 items-center justify-center gap-1.5 rounded-md border px-2 text-xs outline-none transition-colors',
              'focus-visible:ring-2 focus-visible:ring-(--color-accent)/30',
              selected
                ? 'border-(--color-border-strong) bg-(--bg-key) text-(--color-text)'
                : 'border-transparent bg-(--bg-input) text-(--color-text-muted) hover:text-(--color-text)',
            )}
          >
            <span
              aria-hidden="true"
              className="size-1.5 shrink-0 rounded-full"
              style={{ backgroundColor: thinkingColor(option.value) }}
            />
            <span>{option.label}</span>
            {fastMode && selected && (
              <Zap aria-hidden="true" size={10} className="shrink-0 text-(--thinking-low)" />
            )}
          </button>
        )
      })}
    </div>
  )
}

function ThinkingEffortControl({
  options,
  currentIndex,
  fastMode,
  onSelectIndex,
}: {
  options: ThinkingOption[]
  currentIndex: number
  fastMode: boolean
  onSelectIndex: (index: number) => void
}) {
  const current = options[currentIndex] ?? options[0]

  if (options.length <= 2) {
    return (
      <ThinkingEffortButtons
        options={options}
        currentIndex={currentIndex}
        fastMode={fastMode}
        onSelectIndex={onSelectIndex}
      />
    )
  }

  // DiscreteSlider owns keyboard focus on a single range input. Tick labels
  // are mouse-only (tabIndex=-1), so clicking a mode never flashes a focus
  // ring on each step.
  return (
    <DiscreteSlider
      label="Thinking"
      valueLabel={current?.label ?? 'Default'}
      index={currentIndex}
      marks={options.map((option) => option.mark)}
      color={thinkingColor(current?.value ?? null)}
      onChange={onSelectIndex}
      compact
    />
  )
}

function AdvancedComposerControl({
  sessionModel,
  defaultModel,
  sessionThinkingLevel,
  sessionFastMode,
  onChange,
}: {
  sessionModel: string | null
  defaultModel: string | null
  sessionThinkingLevel: string | null
  sessionFastMode: boolean
  onChange?: (model: string | null, thinkingLevel: string | null, fastMode: boolean) => void
}) {
  const registry = useRegistryQuery()
  const [open, setOpen] = useState(false)
  const effectiveModel = sessionModel ?? defaultModel ?? ''
  const model = registry.data?.models.find((entry) => entry.id === effectiveModel)
  const thinkingOptions = buildThinkingOptions(model?.thinking_levels ?? [])
  const currentThinkingLevel = sessionThinkingLevel
  const currentIndex = Math.max(
    0,
    thinkingOptions.findIndex((option) => option.value === currentThinkingLevel),
  )
  const currentOption = thinkingOptions[currentIndex] ?? thinkingOptions[0]
  const fastAvailable = supportsFastMode(effectiveModel)
  const effectiveFastMode = fastAvailable && sessionFastMode
  const thinkingTone = thinkingColor(currentOption.value)

  const selectThinkingAt = (index: number) => {
    const boundedIndex = Math.min(Math.max(index, 0), thinkingOptions.length - 1)
    const next = thinkingOptions[boundedIndex]
    if (!next) return
    onChange?.(sessionModel, next.value, effectiveFastMode)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label={`Model settings: ${effectiveModel ? shortModelName(effectiveModel) : 'model'}, ${currentOption.label}`}
            className={cn(
              CONTROL_CLASS,
              'composer-model-trigger max-w-[14rem] shrink-0 justify-center gap-1.5',
              open && 'bg-(--bg-key) text-(--color-text)',
            )}
          />
        }
      >
        {effectiveModel ? (
          <ProviderBrandIcon providerId={effectiveModel} size="xs" />
        ) : null}
        <span className="composer-model-name min-w-0 truncate font-medium text-(--color-text-2)">
          {effectiveModel ? shortModelName(effectiveModel) : 'Model'}
        </span>
        <span
          className="composer-optional-badge shrink-0 rounded px-1 py-px font-medium"
          style={{
            color: thinkingTone,
            backgroundColor: `color-mix(in srgb, ${thinkingTone} 16%, transparent)`,
          }}
        >
          {currentOption.label}
        </span>
        <ChevronDown
          aria-hidden="true"
          size={10}
          className={cn('shrink-0 transition-transform', open && 'rotate-180')}
        />
      </PopoverTrigger>

      <PopoverContent
        side="top"
        align="end"
        className="w-[min(18rem,calc(100vw-1rem))] gap-0 overflow-hidden rounded-lg border-(--color-border) bg-(--color-surface)/96 p-0 shadow-xl backdrop-blur-xl"
      >
        <div className="border-b border-(--color-border-subtle) px-2.5 py-2">
          <div className="flex items-center gap-2">
            {effectiveModel ? <ProviderBrandIcon providerId={effectiveModel} size="xs" /> : null}
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-semibold text-(--color-text)">
                {effectiveModel ? shortModelName(effectiveModel) : 'Choose a model'}
              </p>
              {effectiveModel && (
                <p className="truncate font-mono text-[9px] text-(--color-text-subtle)">
                  {effectiveModel}
                </p>
              )}
            </div>
          </div>
        </div>

        <div className="px-2.5 py-2">
          <ModelOptions
            models={registry.data?.models ?? []}
            selectedModel={effectiveModel}
            onSelect={(modelId) => {
              const nextModel = registry.data?.models.find((entry) => entry.id === modelId)
              const nextThinking = reconcileThinkingLevel(
                currentThinkingLevel,
                nextModel,
              )
              onChange?.(modelId, nextThinking, supportsFastMode(modelId) && sessionFastMode)
            }}
          />
        </div>

        <div className="border-t border-(--color-border-subtle) px-2.5 py-2">
          {thinkingOptions.length > 1 ? (
            <ThinkingEffortControl
              options={thinkingOptions}
              currentIndex={currentIndex}
              fastMode={effectiveFastMode}
              onSelectIndex={selectThinkingAt}
            />
          ) : (
            <div className="flex items-center justify-between gap-3 py-0.5">
              <span className="text-[11px] font-medium text-(--color-text-2)">Thinking</span>
              <span className="text-[10px] text-(--color-text-subtle)">Provider default</span>
            </div>
          )}
        </div>

        <div className="border-t border-(--color-border-subtle) px-2.5 py-2">
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="text-[11px] font-medium text-(--color-text-2)">Speed</span>
            {!fastAvailable && (
              <span className="text-[10px] text-(--color-text-subtle)">Fast unavailable</span>
            )}
          </div>
          <SegmentedControl
            layoutId="composer-speed"
            ariaLabel="Response speed"
            className="h-7 w-full [&>button]:flex-1 [&>button]:py-0 [&>button]:text-[11px]"
            options={[
              { value: 'standard', label: 'Standard' },
              {
                value: 'fast',
                label: 'Fast',
                disabled: !fastAvailable,
              },
            ]}
            value={effectiveFastMode ? 'fast' : 'standard'}
            onChange={(speed) =>
              onChange?.(sessionModel, currentThinkingLevel, speed === 'fast')
            }
          />
        </div>
      </PopoverContent>
    </Popover>
  )
}

export interface SessionPillsRowProps {
  sessionModel?: string | null
  defaultModel?: string | null
  sessionThinkingLevel?: string | null
  sessionFastMode?: boolean
  onSessionModelSettingsChange?: (
    model: string | null,
    thinkingLevel: string | null,
    fastMode: boolean,
  ) => void
  agentNames?: string[]
  workspace?: string | null
  mode?: 'coding' | 'aim' | null
}

export function SessionPillsRow({
  sessionModel,
  defaultModel,
  sessionThinkingLevel,
  sessionFastMode,
  onSessionModelSettingsChange,
  agentNames,
  workspace,
  mode,
}: SessionPillsRowProps) {
  return (
    <div className="flex min-w-0 items-center gap-1">
      <AdvancedComposerControl
        sessionModel={sessionModel ?? null}
        defaultModel={defaultModel ?? null}
        sessionThinkingLevel={sessionThinkingLevel ?? null}
        sessionFastMode={sessionFastMode ?? false}
        onChange={onSessionModelSettingsChange}
      />
      <AgentInfoPopover
        agentNames={agentNames}
        workspace={workspace}
        sessionModel={sessionModel ?? null}
        mode={mode}
      />
    </div>
  )
}
