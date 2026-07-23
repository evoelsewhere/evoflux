/** Compact session model controls shared by the Forge, Coding, and AIM composers. */

import { useMemo, useState } from 'react'
import fuzzysort from 'fuzzysort'
import { motion } from 'framer-motion'
import { Check, ChevronDown, Search, Zap } from 'lucide-react'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import { useRegistryQuery } from '@/queries'
import { cn } from '@/lib/utils'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { AgentInfoPopover } from './AgentInfoPopover'

const THINKING_LEVEL_LABEL: Record<string, string> = {
  none: 'None',
  minimal: 'Minimal',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  xhigh: 'X-High',
  max: 'Max',
}

const CONTROL_CLASS =
  'flex h-7 min-w-0 items-center rounded-[7px] px-2 text-xs text-(--color-text-muted) outline-none transition-[background-color,color,transform] duration-150 hover:bg-(--bg-key) hover:text-(--color-text) active:translate-y-px focus-visible:ring-2 focus-visible:ring-(--color-accent)/30'

function buildThinkingOptions(levels: string[]) {
  return [
    { value: null, label: 'Default' },
    { value: 'none', label: 'None' },
    ...levels
      .filter((level) => level !== 'none')
      .map((level) => ({ value: level, label: THINKING_LEVEL_LABEL[level] ?? level })),
  ]
}

function shortModelName(id: string): string {
  const colon = id.indexOf(':')
  return colon === -1 ? id : id.slice(colon + 1)
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
  const registry = useRegistryQuery()
  const [query, setQuery] = useState('')
  const models = useMemo(() => registry.data?.models ?? [], [registry.data?.models])
  const visibleModels = useMemo(() => {
    const value = query.trim()
    if (!value) return models.slice(0, 30)
    return fuzzysort.go(value, models, { key: 'id', limit: 30 }).map((result) => result.obj)
  }, [models, query])

  return (
    <div className="flex min-h-0 flex-col gap-1.5">
      <label className="relative block">
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-(--color-text-subtle)"
          size={13}
        />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search models..."
          className="h-8 w-full rounded-[7px] border border-(--color-border) bg-(--bg-input) pl-8 pr-2 text-xs text-(--color-text) outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-(--color-text-subtle) focus:border-(--color-border-strong) focus:ring-2 focus:ring-(--color-accent)/20"
        />
      </label>
      <div className="max-h-44 overflow-y-auto overscroll-contain" role="listbox" aria-label="Models">
        {visibleModels.length === 0 ? (
          <p className="px-2 py-4 text-center text-xs text-(--color-text-muted)">No models found</p>
        ) : (
          visibleModels.map((model) => (
            <button
              key={model.id}
              type="button"
              role="option"
              aria-selected={model.id === selectedModel}
              onClick={() => onSelect(model.id)}
              className={cn(
                'flex h-8 w-full items-center gap-2 rounded-[6px] px-2 text-left text-xs outline-none transition-[background-color,color] duration-150 hover:bg-(--bg-key) focus-visible:bg-(--bg-key)',
                model.id === selectedModel
                  ? 'bg-(--bg-key) text-(--color-text)'
                  : 'text-(--color-text-2)',
              )}
            >
              <span className="min-w-0 flex-1 truncate font-medium">{shortModelName(model.id)}</span>
              <span className="shrink-0 text-[10px] text-(--color-text-subtle)">
                {model.id.includes(':') ? model.id.slice(0, model.id.indexOf(':')) : ''}
              </span>
              <Check
                aria-hidden="true"
                size={12}
                className={cn('shrink-0', model.id === selectedModel ? 'opacity-100' : 'opacity-0')}
              />
            </button>
          ))
        )}
      </div>
    </div>
  )
}

type ThinkingOption = {
  value: string | null
  label: string
}

const THINKING_TRAIL_PARTICLES = [
  { top: 3, size: 3, delay: 0, duration: 1.45 },
  { top: 9, size: 4, delay: 0.28, duration: 1.7 },
  { top: 16, size: 3, delay: 0.55, duration: 1.55 },
  { top: 5, size: 4, delay: 0.8, duration: 1.8 },
  { top: 14, size: 3, delay: 1.05, duration: 1.6 },
  { top: 8, size: 3, delay: 1.3, duration: 1.75 },
] as const

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
    <div
      role="radiogroup"
      aria-label="Thinking effort"
      className="flex flex-wrap gap-1"
    >
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
              'flex h-8 min-w-[4rem] flex-1 items-center justify-center gap-1.5 rounded-[6px] border px-2 text-xs outline-none transition-[background-color,border-color,color,transform] active:translate-y-px focus-visible:ring-2 focus-visible:ring-(--color-accent)/30',
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

function ThinkingEffortSlider({
  options,
  currentIndex,
  onSelectIndex,
}: {
  options: ThinkingOption[]
  currentIndex: number
  fastMode: boolean
  onSelectIndex: (index: number) => void
}) {
  const reducedMotion = Boolean(useReducedMotion())
  const currentOption = options[currentIndex] ?? options[0]
  const progress = options.length <= 1
    ? 0
    : (currentIndex / (options.length - 1)) * 100
  const color = thinkingColor(currentOption?.value ?? null)

  return (
    <div className="relative h-6 rounded-[7px] bg-(--bg-key) shadow-[inset_0_1px_1px_rgb(0_0_0/0.08)] transition-shadow focus-within:ring-2 focus-within:ring-(--color-accent)/25">
      <div aria-hidden="true" className="absolute inset-x-2 inset-y-0">
        <motion.div
          data-testid="thinking-effort-tail"
          className="absolute inset-y-0 left-0 overflow-hidden rounded-[5px]"
          initial={false}
          animate={{ width: `${progress}%` }}
          transition={reducedMotion
            ? { duration: 0 }
            : { type: 'spring', stiffness: 180, damping: 24, mass: 0.9 }}
          style={{ backgroundColor: `color-mix(in srgb, ${color} 18%, transparent)` }}
        >
          {reducedMotion ? (
            <span
              className="absolute inset-1 rounded-[4px] opacity-35"
              style={{ backgroundColor: color }}
            />
          ) : (
            THINKING_TRAIL_PARTICLES.map((particle, index) => (
              <motion.span
                key={`${particle.top}-${particle.delay}`}
                data-testid={`thinking-trail-particle-${index}`}
                className="absolute left-0 rounded-[1px]"
                style={{
                  top: particle.top,
                  width: particle.size,
                  height: particle.size,
                  backgroundColor: color,
                }}
                animate={{
                  x: ['-10%', '4800%'],
                  opacity: [0, 0.75, 0.55, 0],
                  scale: [0.65, 1, 0.8],
                }}
                transition={{
                  duration: particle.duration,
                  delay: particle.delay,
                  ease: 'linear',
                  repeat: Infinity,
                }}
              />
            ))
          )}
        </motion.div>
        <span className="absolute inset-0 flex items-center justify-between">
          {options.map((option, index) => (
            <span
              key={option.value ?? '__default__'}
              className="relative z-10 size-1.5 rounded-full transition-colors duration-150"
              style={{
                backgroundColor: index === currentIndex
                  ? color
                  : 'var(--color-text-subtle)',
                opacity: index === currentIndex ? 1 : 0.55,
              }}
            />
          ))}
        </span>
        <motion.span
          data-testid="thinking-effort-thumb"
          className="absolute top-1/2 z-20 h-5 w-[18px] -translate-x-1/2 -translate-y-1/2 rounded-[6px] border border-(--color-border-strong) bg-(--color-surface) shadow-[0_1px_3px_rgb(0_0_0/0.16),0_2px_5px_rgb(0_0_0/0.08)]"
          initial={false}
          animate={{ left: `${progress}%` }}
          transition={reducedMotion
            ? { duration: 0 }
            : { type: 'spring', stiffness: 520, damping: 34, mass: 0.55 }}
        />
      </div>
      <input
        type="range"
        min={0}
        max={Math.max(0, options.length - 1)}
        step={1}
        value={currentIndex}
        aria-label="Thinking effort"
        aria-valuetext={currentOption?.label ?? 'Default'}
        onChange={(event) => onSelectIndex(Number(event.target.value))}
        className="absolute inset-x-2 top-0 h-6 w-[calc(100%-1rem)] cursor-pointer appearance-none opacity-0 outline-none"
      />
    </div>
  )
}

function ThinkingEffortControl(props: {
  options: ThinkingOption[]
  currentIndex: number
  fastMode: boolean
  onSelectIndex: (index: number) => void
}) {
  return props.options.length <= 2
    ? <ThinkingEffortButtons {...props} />
    : <ThinkingEffortSlider {...props} />
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
  const currentIndex = Math.max(0, thinkingOptions.findIndex((option) => option.value === currentThinkingLevel))
  const currentOption = thinkingOptions[currentIndex] ?? thinkingOptions[0]
  const fastAvailable = supportsFastMode(effectiveModel)
  const effectiveFastMode = fastAvailable && sessionFastMode

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
            className={cn(CONTROL_CLASS, 'max-w-[12rem] shrink-0 justify-center gap-1.5', open && 'bg-(--bg-key) text-(--color-text)')}
          />
        }
      >
        <span className="truncate font-medium text-(--color-text-2)">
          {effectiveModel ? shortModelName(effectiveModel) : 'Model'}
        </span>
        <span aria-hidden="true" className="text-(--color-text-subtle)">·</span>
        <span className="shrink-0" style={{ color: thinkingColor(currentOption.value) }}>
          {currentOption.label}
        </span>
        <ChevronDown aria-hidden="true" size={10} className={cn('shrink-0 transition-transform duration-150', open && 'rotate-180')} />
      </PopoverTrigger>

      <PopoverContent
        side="top"
        align="end"
        className="w-[min(18rem,calc(100vw-1rem))] gap-3 rounded-[9px] border-(--color-border) bg-(--color-surface) p-3"
      >
        <div>
          <p className="text-sm font-semibold text-(--color-text)">Model</p>
          <p className="mt-0.5 truncate text-xs text-(--color-text-subtle)">{effectiveModel || 'Choose a model'}</p>
        </div>

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

        <div className="border-t border-(--color-border-subtle) pt-2.5">
          <div className="mb-1 flex items-center justify-between gap-3">
            <span className="text-xs font-medium text-(--color-text-2)">
              Thinking
            </span>
            <span className="text-xs" style={{ color: thinkingColor(currentOption.value) }}>
              {currentOption.label}
            </span>
          </div>
          <ThinkingEffortControl
            options={thinkingOptions}
            currentIndex={currentIndex}
            fastMode={effectiveFastMode}
            onSelectIndex={selectThinkingAt}
          />
        </div>

        <div>
          <p className="mb-1.5 text-xs font-medium text-(--color-text-2)">Speed</p>
          <div className="grid h-8 grid-cols-2 rounded-[7px] bg-(--bg-input) p-0.5" role="group" aria-label="Response speed">
            {([false, true] as const).map((fast) => (
              <button
                key={String(fast)}
                type="button"
                disabled={fast && !fastAvailable}
                aria-pressed={fast === effectiveFastMode}
                title={fast && !fastAvailable ? 'Fast mode is unavailable for this model' : undefined}
                onClick={() => onChange?.(sessionModel, currentThinkingLevel, fast)}
                className={cn(
                  'flex items-center justify-center gap-1 rounded-[6px] px-2 text-xs outline-none transition-[background-color,color,box-shadow,transform] duration-150 active:translate-y-px focus-visible:ring-2 focus-visible:ring-(--color-accent)/30 disabled:cursor-not-allowed disabled:opacity-40',
                  fast === effectiveFastMode
                    ? 'bg-(--color-surface) text-(--color-text) shadow-sm'
                    : 'text-(--color-text-muted) hover:text-(--color-text)',
                )}
              >
                {fast && (
                  <Zap
                    data-testid="fast-mode-zap"
                    data-fast-active={String(effectiveFastMode)}
                    aria-hidden="true"
                    size={11}
                    className={effectiveFastMode ? 'text-(--thinking-low)' : undefined}
                  />
                )}
                {fast ? 'Fast' : 'Standard'}
              </button>
            ))}
          </div>
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
    <div className="flex min-w-0 items-center gap-0.5">
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
