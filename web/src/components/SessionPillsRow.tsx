/** Compact session model controls shared by the Forge, Coding, and AIM composers. */

import { useMemo, useState } from 'react'
import fuzzysort from 'fuzzysort'
import { motion } from 'framer-motion'
import { Check, ChevronDown, Search, Zap } from 'lucide-react'
import { useRegistryQuery } from '@/queries'
import { cn } from '@/lib/utils'
import { fadeRise, staggerDelay, useListEnterIndex, useMotionPreset } from '@/lib/motion'
import { DiscreteSlider } from '@/components/ui/discrete-slider'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { AgentInfoPopover } from './AgentInfoPopover'
import { ProviderBrandIcon } from '@/components/providers/ProviderBrandIcon'

const THINKING_LEVEL_LABEL: Record<string, string> = {
  none: 'None',
  minimal: 'Minimal',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  xhigh: 'X-High',
  max: 'Max',
}

/** Compact tick labels — full names live in the value readout. */
const THINKING_MARK: Record<string, string> = {
  none: 'None',
  default: 'Def',
  minimal: 'Min',
  low: 'Low',
  medium: 'Med',
  high: 'High',
  xhigh: 'XH',
  max: 'Max',
}

const CONTROL_CLASS =
  'flex h-7 min-w-0 items-center rounded-md px-2 text-xs text-(--color-text-muted) outline-none transition-colors duration-(--motion-fast) hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:ring-2 focus-visible:ring-(--color-accent)/30'

type ThinkingOption = {
  value: string | null
  label: string
  mark: string
}

function buildThinkingOptions(levels: string[]): ThinkingOption[] {
  return [
    { value: 'none', label: 'None', mark: THINKING_MARK.none },
    { value: null, label: 'Default', mark: THINKING_MARK.default },
    ...levels
      .filter((level) => level !== 'none')
      .map((level) => ({
        value: level,
        label: THINKING_LEVEL_LABEL[level] ?? level,
        mark: THINKING_MARK[level] ?? level.slice(0, 3),
      })),
  ]
}

function shortModelName(id: string): string {
  const colon = id.indexOf(':')
  return colon === -1 ? id : id.slice(colon + 1)
}

function providerOf(id: string): string {
  const colon = id.indexOf(':')
  return colon === -1 ? '' : id.slice(0, colon)
}

function supportsFastMode(modelId: string): boolean {
  return modelId.startsWith('codex:')
}

function thinkingColor(level: string | null): string {
  if (!level || level === 'none') return 'var(--thinking-neutral)'
  if (level === 'minimal' || level === 'low') return 'var(--thinking-low)'
  if (level === 'medium') return 'var(--thinking-medium)'
  if (level === 'high') return 'var(--thinking-high)'
  return 'var(--thinking-max)'
}

function ModelOptions({
  selectedModel,
  onSelect,
}: {
  selectedModel: string
  onSelect: (modelId: string) => void
}) {
  const preset = useMotionPreset()
  const registry = useRegistryQuery()
  const [query, setQuery] = useState('')
  const models = useMemo(() => registry.data?.models ?? [], [registry.data?.models])
  const visibleModels = useMemo(() => {
    const value = query.trim()
    if (!value) return models.slice(0, 30)
    return fuzzysort.go(value, models, { key: 'id', limit: 30 }).map((result) => result.obj)
  }, [models, query])
  const enterIndex = useListEnterIndex(visibleModels.map((model) => model.id))

  return (
    <div className="flex min-h-0 flex-col gap-2">
      <label className="relative block">
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-(--color-text-subtle)"
          size={13}
        />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search models…"
          className="h-8 w-full rounded-md border border-(--color-border) bg-(--bg-input) pr-2 pl-8 text-xs text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-subtle) focus:border-(--color-border-strong) focus-visible:ring-2 focus-visible:ring-(--color-accent)/20"
        />
      </label>
      <div className="max-h-48 overflow-y-auto overscroll-contain" role="listbox" aria-label="Models">
        {visibleModels.length === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-(--color-text-muted)">No models found</p>
        ) : (
          <div className="flex flex-col gap-0.5">
            {visibleModels.map((model) => {
              const selected = model.id === selectedModel
              const provider = providerOf(model.id)
              const index = enterIndex(model.id)
              const enter = index !== undefined ? fadeRise(preset, 6) : null
              const option = (
                <button
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onClick={() => onSelect(model.id)}
                  className={cn(
                    'relative flex h-9 w-full items-center gap-2.5 rounded-md px-2 text-left text-xs outline-none transition-colors',
                    'hover:bg-(--bg-key) focus-visible:bg-(--bg-key)',
                    selected ? 'bg-(--bg-key) text-(--color-text)' : 'text-(--color-text-2)',
                  )}
                >
                  {selected && (
                    <span
                      aria-hidden="true"
                      className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-(--color-accent)"
                    />
                  )}
                  <ProviderBrandIcon providerId={model.id} size="xs" />
                  <span className="min-w-0 flex-1 truncate font-medium">
                    {shortModelName(model.id)}
                  </span>
                  {provider && (
                    <span className="shrink-0 font-mono text-[10px] tracking-wide text-(--color-text-subtle) uppercase">
                      {provider}
                    </span>
                  )}
                  <Check
                    aria-hidden="true"
                    size={12}
                    className={cn('shrink-0 text-(--color-accent)', selected ? 'opacity-100' : 'opacity-0')}
                  />
                </button>
              )
              if (!enter || index === undefined) {
                return <div key={model.id}>{option}</div>
              }
              return (
                <motion.div
                  key={model.id}
                  initial={enter.initial}
                  animate={enter.animate}
                  transition={{ ...enter.transition, delay: staggerDelay(preset, index) }}
                >
                  {option}
                </motion.div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

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
              'max-w-28 shrink-0 justify-center gap-1.5 sm:max-w-[14rem]',
              open && 'bg-(--bg-key) text-(--color-text)',
            )}
          />
        }
      >
        {effectiveModel ? (
          <ProviderBrandIcon providerId={effectiveModel} size="xs" />
        ) : null}
        <span className="min-w-0 truncate font-medium text-(--color-text-2)">
          {effectiveModel ? shortModelName(effectiveModel) : 'Model'}
        </span>
        <span
          className="hidden shrink-0 rounded px-1 py-px font-medium sm:inline"
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
        className="w-[min(20rem,calc(100vw-1rem))] gap-0 overflow-hidden rounded-lg border-(--color-border) bg-(--color-surface) p-0 shadow-xl"
      >
        <div className="border-b border-(--color-border-subtle) px-3 py-2.5">
          <div className="flex items-center gap-2">
            {effectiveModel ? <ProviderBrandIcon providerId={effectiveModel} size="sm" /> : null}
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-(--color-text)">
                {effectiveModel ? shortModelName(effectiveModel) : 'Choose a model'}
              </p>
              {effectiveModel && (
                <p className="mt-0.5 truncate font-mono text-[10px] text-(--color-text-subtle)">
                  {effectiveModel}
                </p>
              )}
            </div>
          </div>
        </div>

        <div className="px-3 py-2.5">
          <ModelOptions
            selectedModel={effectiveModel}
            onSelect={(modelId) => {
              const nextModel = registry.data?.models.find((entry) => entry.id === modelId)
              const nextOptions = buildThinkingOptions(nextModel?.thinking_levels ?? [])
              const nextThinking = nextOptions.some((option) => option.value === currentThinkingLevel)
                ? currentThinkingLevel
                : null
              onChange?.(modelId, nextThinking, supportsFastMode(modelId) && sessionFastMode)
            }}
          />
        </div>

        <div className="border-t border-(--color-border-subtle) px-3 py-3">
          <ThinkingEffortControl
            options={thinkingOptions}
            currentIndex={currentIndex}
            fastMode={effectiveFastMode}
            onSelectIndex={selectThinkingAt}
          />
        </div>

        <div className="border-t border-(--color-border-subtle) px-3 py-2.5">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-(--color-text-2)">Speed</span>
            {!fastAvailable && (
              <span className="text-[10px] text-(--color-text-subtle)">Fast unavailable</span>
            )}
          </div>
          <SegmentedControl
            layoutId="composer-speed"
            ariaLabel="Response speed"
            className="h-8 w-full [&>button]:flex-1"
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
