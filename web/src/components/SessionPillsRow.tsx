/** Compact session model controls shared by the Forge, Coding, and AIM composers. */

import { useId, useMemo, useState, type CSSProperties } from 'react'
import fuzzysort from 'fuzzysort'
import { AnimatePresence, LayoutGroup, motion } from 'framer-motion'
import { ChevronDown, Search, Zap } from 'lucide-react'
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
  'flex h-8 items-center rounded-lg border border-transparent px-2 text-xs text-(--color-text-2) outline-none transition-[background-color,border-color,color,box-shadow,transform] duration-150 hover:bg-(--bg-key) hover:text-(--color-text) active:translate-y-px focus-visible:border-(--color-border-strong) focus-visible:ring-2 focus-visible:ring-(--color-accent)/35'

function buildThinkingOptions(levels: string[]) {
  return [
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
  onSelect,
}: {
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
    <div className="flex min-h-0 flex-col gap-2">
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
          className="h-9 w-full rounded-lg border border-(--color-border) bg-(--bg-input) pl-8 pr-2.5 font-mono text-xs text-(--color-text) outline-none transition-[border-color,box-shadow] duration-150 focus:border-(--color-border-strong) focus:ring-2 focus:ring-(--color-accent)/25"
        />
      </label>
      <div className="max-h-56 overflow-y-auto overscroll-contain" role="listbox" aria-label="Models">
        {visibleModels.length === 0 ? (
          <p className="px-2 py-4 text-center text-xs text-(--color-text-muted)">No models found</p>
        ) : (
          visibleModels.map((model) => (
            <button
              key={model.id}
              type="button"
              role="option"
              aria-selected="false"
              onClick={() => onSelect(model.id)}
              className="flex min-h-8 w-full items-center rounded-md px-2 text-left font-mono text-xs text-(--color-text-2) outline-none transition-[background-color,color] duration-150 hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:bg-(--bg-key) focus-visible:text-(--color-text)"
            >
              <span className="truncate">{model.id}</span>
            </button>
          ))
        )}
      </div>
    </div>
  )
}

type ThinkingOption = {
  value: string
  label: string
}

const FAST_PARTICLES = [
  { delay: 0, duration: 2.4, size: 2, y: -3 },
  { delay: 0.18, duration: 2.65, size: 3, y: 2 },
  { delay: 0.36, duration: 2.35, size: 2, y: 0 },
  { delay: 0.54, duration: 2.8, size: 2, y: -2 },
  { delay: 0.72, duration: 2.5, size: 3, y: 3 },
  { delay: 0.9, duration: 2.7, size: 2, y: 1 },
  { delay: 1.08, duration: 2.45, size: 2, y: -3 },
] as const

function ThinkingEffortSlider({
  options,
  currentIndex,
  fastMode,
  reducedMotion,
  onSelectIndex,
}: {
  options: ThinkingOption[]
  currentIndex: number
  fastMode: boolean
  reducedMotion: boolean
  onSelectIndex: (index: number) => void
}) {
  const layoutId = useId()
  const currentOption = options[currentIndex] ?? options[0]
  const progress = options.length <= 1
    ? 0
    : (currentIndex / (options.length - 1)) * 100
  const color = thinkingColor(currentOption?.value || null)
  const disabled = options.length <= 1
  const visualTransition = reducedMotion
    ? { duration: 0 }
    : { type: 'spring' as const, stiffness: 420, damping: 34, mass: 0.65 }

  return (
    <div
      data-testid="thinking-effort-slider"
      data-reduced-motion={String(reducedMotion)}
      className="group relative h-9 w-full rounded-full"
      style={{
        '--thinking-color': color,
        '--thinking-progress': `${progress}%`,
      } as CSSProperties}
    >
      <div
        data-testid="thinking-effort-rail"
        aria-hidden="true"
        className="absolute inset-x-0 top-1/2 h-3 -translate-y-1/2 overflow-hidden rounded-full bg-(--bg-key) shadow-[inset_0_1px_2px_rgb(0_0_0/0.18)]"
      >
        <motion.span
          className="absolute inset-0 origin-left rounded-full bg-(--thinking-color)"
          initial={false}
          animate={{ scaleX: progress / 100 }}
          transition={visualTransition}
        />
        {fastMode && !reducedMotion && progress > 0 && (
          <span
            className="pointer-events-none absolute inset-0 overflow-hidden"
            style={{ clipPath: `inset(0 ${100 - progress}% 0 0)` }}
          >
            {FAST_PARTICLES.map((particle, index) => (
              <span
                key={`${particle.delay}-${particle.y}`}
                data-testid={`fast-particle-${index}`}
                className="fast-mode-particle"
                style={{
                  '--particle-delay': `${particle.delay}s`,
                  '--particle-duration': `${particle.duration}s`,
                  '--particle-size': `${particle.size}px`,
                  '--particle-y': `${particle.y}px`,
                } as CSSProperties}
              />
            ))}
          </span>
        )}
        {fastMode && reducedMotion && (
          <span
            data-testid="fast-static-indicator"
            className="pointer-events-none absolute left-3 top-1/2 flex -translate-y-1/2 gap-2"
          >
            <span className="size-1 rounded-full bg-(--thinking-thumb-contrast)/90" />
            <span className="size-0.5 rounded-full bg-(--thinking-thumb-contrast)/70" />
            <span className="size-1 rounded-full bg-(--thinking-thumb-contrast)/80" />
          </span>
        )}
      </div>

      <LayoutGroup id={layoutId}>
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-1/2 z-20 flex -translate-y-1/2 justify-between"
        >
          {options.map((option, index) => (
            <span
              key={option.value}
              className="relative flex size-6 shrink-0 items-center justify-center"
            >
              <span
                className="size-1 rounded-full transition-colors duration-150"
                style={{
                  backgroundColor: index <= currentIndex
                    ? 'var(--thinking-thumb-contrast)'
                    : 'var(--color-text-subtle)',
                }}
              />
              {index === currentIndex && (
                <motion.span
                  layoutId="thinking-effort-thumb"
                  data-testid="thinking-effort-thumb"
                  className="absolute size-6 rounded-full border border-white/70 bg-(--thinking-thumb-contrast) shadow-[0_2px_8px_rgb(0_0_0/0.32),inset_0_1px_0_rgb(255_255_255/0.8)]"
                  transition={visualTransition}
                />
              )}
            </span>
          ))}
        </div>
      </LayoutGroup>

      <input
        id="thinking-effort"
        type="range"
        min={0}
        max={Math.max(0, options.length - 1)}
        step={1}
        value={currentIndex}
        disabled={disabled}
        aria-label="Thinking effort"
        aria-valuetext={currentOption?.label ?? 'None'}
        onChange={(event) => onSelectIndex(Number(event.target.value))}
        onKeyDown={(event) => {
          let nextIndex: number | null = null
          if (event.key === 'ArrowRight' || event.key === 'ArrowUp') nextIndex = currentIndex + 1
          if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') nextIndex = currentIndex - 1
          if (event.key === 'Home') nextIndex = 0
          if (event.key === 'End') nextIndex = options.length - 1
          if (nextIndex !== null) {
            event.preventDefault()
            onSelectIndex(nextIndex)
          }
        }}
        className="absolute inset-0 z-30 h-9 w-full cursor-pointer appearance-none opacity-0 outline-none disabled:cursor-not-allowed"
      />
    </div>
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
  const reducedMotion = Boolean(useReducedMotion())
  const [open, setOpen] = useState(false)
  const [modelFlyoutOpen, setModelFlyoutOpen] = useState(false)
  const effectiveModel = sessionModel ?? defaultModel ?? ''
  const model = registry.data?.models.find((entry) => entry.id === effectiveModel)
  const thinkingOptions = buildThinkingOptions(model?.thinking_levels ?? [])
  const currentThinkingLevel = sessionThinkingLevel ?? 'none'
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
    <Popover
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        if (!nextOpen) setModelFlyoutOpen(false)
      }}
    >
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label={`Model settings: ${effectiveModel ? shortModelName(effectiveModel) : 'model'}, ${currentOption.label}`}
            className={cn(CONTROL_CLASS, 'shrink-0 justify-center gap-1.5 border-(--color-border) bg-(--bg-card)')}
          />
        }
      >
        <span className="truncate font-mono font-medium text-(--color-text)">
          {effectiveModel ? shortModelName(effectiveModel) : 'Model'}
        </span>
        <span aria-hidden="true" className="text-(--color-text-subtle)">·</span>
        <span style={{ color: thinkingColor(currentOption.value || null) }}>{currentOption.label}</span>
        <ChevronDown aria-hidden="true" size={11} className={cn('ml-0.5 shrink-0 transition-transform duration-150', open && 'rotate-180')} />
      </PopoverTrigger>

      <PopoverContent
        side="top"
        align="end"
        className="w-[min(20rem,calc(100vw-1rem))] gap-3.5 overflow-visible p-3.5"
      >
          <>
            <div
              className="relative"
              onPointerLeave={() => setModelFlyoutOpen(false)}
              onBlur={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                  setModelFlyoutOpen(false)
                }
              }}
            >
              <p className="mb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-(--color-text-subtle)">Model</p>
              <button
                type="button"
                aria-label="Choose model"
                aria-haspopup="listbox"
                aria-expanded={modelFlyoutOpen}
                onPointerEnter={(event) => {
                  if (event.pointerType === 'mouse') setModelFlyoutOpen(true)
                }}
                onMouseEnter={() => setModelFlyoutOpen(true)}
                onClick={() => setModelFlyoutOpen(true)}
                className="flex h-9 w-full items-center justify-between gap-3 rounded-lg border border-(--color-border) bg-(--bg-input) px-2.5 font-mono text-xs text-(--color-text) outline-none transition-[background-color,border-color] duration-150 hover:bg-(--bg-key) focus-visible:border-(--color-border-strong)"
              >
                <span className="truncate">{effectiveModel || 'Choose a model'}</span>
                <ChevronDown aria-hidden="true" size={12} className="-rotate-90 shrink-0 text-(--color-text-subtle)" />
              </button>
              <AnimatePresence initial={false}>
                {modelFlyoutOpen && (
                  <motion.div
                    key="model-flyout"
                    data-testid="model-flyout"
                    initial={reducedMotion ? false : { opacity: 0, x: -6, scale: 0.98 }}
                    animate={{ opacity: 1, x: 0, scale: 1 }}
                    exit={reducedMotion ? { opacity: 0 } : { opacity: 0, x: -4, scale: 0.985 }}
                    transition={{ duration: reducedMotion ? 0 : 0.14, ease: [0.16, 1, 0.3, 1] }}
                    className="absolute left-[calc(100%+0.5rem)] top-0 z-(--z-modal) w-[min(19rem,calc(100vw-1rem))] rounded-xl border border-(--color-border-strong) bg-(--bg-page) p-2.5 shadow-(--shadow-popover) max-[1180px]:bottom-[calc(100%+0.5rem)] max-[1180px]:left-0 max-[1180px]:top-auto"
                  >
                    <ModelOptions
                      onSelect={(modelId) => {
                        const nextModel = registry.data?.models.find((entry) => entry.id === modelId)
                        const nextOptions = buildThinkingOptions(nextModel?.thinking_levels ?? [])
                        const nextThinking = nextOptions.some((option) => option.value === currentThinkingLevel)
                          ? currentThinkingLevel
                          : 'none'
                        onChange?.(modelId, nextThinking, supportsFastMode(modelId) && sessionFastMode)
                        setModelFlyoutOpen(false)
                      }}
                    />
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between gap-3">
                <label htmlFor="thinking-effort" className="text-[11px] font-medium uppercase tracking-[0.08em] text-(--color-text-subtle)">
                  Thinking
                </label>
                <span className="text-xs font-medium" style={{ color: thinkingColor(currentOption.value || null) }}>
                  {currentOption.label}
                </span>
              </div>
              <ThinkingEffortSlider
                options={thinkingOptions}
                currentIndex={currentIndex}
                fastMode={effectiveFastMode}
                reducedMotion={reducedMotion}
                onSelectIndex={selectThinkingAt}
              />
            </div>

            <div>
              <p className="mb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-(--color-text-subtle)">Speed</p>
              <div className="grid h-8 grid-cols-2 rounded-lg bg-(--bg-input) p-0.5" role="group" aria-label="Response speed">
                {([false, true] as const).map((fast) => (
                  <button
                    key={String(fast)}
                    type="button"
                    disabled={fast && !fastAvailable}
                    aria-pressed={fast === effectiveFastMode}
                    title={fast && !fastAvailable ? 'Fast mode is unavailable for this model' : undefined}
                    onClick={() => onChange?.(sessionModel, currentThinkingLevel, fast)}
                    className={cn(
                      'flex items-center justify-center gap-1 rounded-md px-2 text-xs outline-none transition-[background-color,color,box-shadow,transform] duration-150 active:translate-y-px focus-visible:ring-2 focus-visible:ring-(--color-accent)/30 disabled:cursor-not-allowed disabled:opacity-40',
                      fast === effectiveFastMode
                        ? 'bg-(--bg-key) text-(--color-text) shadow-sm'
                        : 'text-(--color-text-muted) hover:text-(--color-text)',
                    )}
                  >
                    {fast && (
                      <motion.span
                        data-testid="fast-mode-zap"
                        data-fast-active={String(effectiveFastMode)}
                        className={effectiveFastMode ? 'text-(--thinking-low)' : undefined}
                        initial={false}
                        animate={
                          effectiveFastMode && !reducedMotion
                            ? { scale: [1, 1.28, 1], rotate: [0, -12, 0] }
                            : { scale: 1, rotate: 0 }
                        }
                        transition={{ duration: reducedMotion ? 0 : 0.32, ease: [0.16, 1, 0.3, 1] }}
                      >
                        <Zap aria-hidden="true" size={11} />
                      </motion.span>
                    )}
                    {fast ? 'Fast' : 'Standard'}
                  </button>
                ))}
              </div>
            </div>
          </>
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
    <div className="flex min-w-0 items-center gap-1 px-1 pb-1">
      <AdvancedComposerControl
        sessionModel={sessionModel ?? null}
        defaultModel={defaultModel ?? null}
        sessionThinkingLevel={sessionThinkingLevel ?? null}
        sessionFastMode={sessionFastMode ?? false}
        onChange={onSessionModelSettingsChange}
      />
      <div className="min-w-2 flex-1" />
      <AgentInfoPopover
        agentNames={agentNames}
        workspace={workspace}
        sessionModel={sessionModel ?? null}
        mode={mode}
      />
    </div>
  )
}
