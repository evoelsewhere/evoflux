import { useId, useMemo, useState, type ReactNode } from 'react'
import fuzzysort from 'fuzzysort'
import { motion } from 'framer-motion'
import { Check, Search } from 'lucide-react'

import { ProviderBrandIcon } from '@/components/providers/ProviderBrandIcon'
import { cn } from '@/lib/utils'
import {
  formatModelPrice,
  formatTokenCount,
  modelSearchText,
  providerOf,
  shortModelName,
  type ModelOption,
} from '@/lib/model-settings'
import { fadeRise, staggerDelay, useListEnterIndex, useMotionPreset } from '@/lib/motion'

/** Which slice of the catalogue the picker is showing. */
type ModelFilter = 'all' | 'free' | 'vision'

function matchesFilter(model: ModelOption, filter: ModelFilter): boolean {
  if (filter === 'free') return Boolean(model.free)
  if (filter === 'vision') return Boolean(model.vision)
  return true
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors',
        active
          ? 'bg-(--color-accent)/15 text-(--color-accent)'
          : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
      )}
    >
      {children}
    </button>
  )
}

interface Props {
  models: readonly ModelOption[]
  selectedModel: string
  onSelect: (modelId: string) => void
  limit?: number
  listClassName?: string
}

/**
 * Shared searchable model list used by the composer and Agent Settings.
 * Keeping filtering and option rendering here prevents the two model
 * selectors from drifting apart.
 */
export function ModelOptions({
  models,
  selectedModel,
  onSelect,
  limit = 30,
  listClassName,
}: Props) {
  const preset = useMotionPreset()
  const listboxId = useId()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<ModelFilter>('all')
  const freeCount = useMemo(
    () => models.reduce((count, model) => count + (model.free ? 1 : 0), 0),
    [models],
  )
  const visionCount = useMemo(
    () => models.reduce((count, model) => count + (model.vision ? 1 : 0), 0),
    [models],
  )
  const visibleModels = useMemo(() => {
    const pool = models.filter((model) => matchesFilter(model, filter))
    const value = query.trim()
    if (!value) return pool.slice(0, limit)
    return fuzzysort
      .go(value, pool, { key: modelSearchText, limit })
      .map((result) => result.obj)
  }, [filter, limit, models, query])
  const enterIndex = useListEnterIndex(visibleModels.map((model) => model.id))

  return (
    <div className="flex min-h-0 flex-col gap-1.5">
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
          aria-controls={listboxId}
          className="h-7 w-full rounded-md border border-(--color-border) bg-(--bg-input) pr-2 pl-8 text-[11px] text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-subtle) focus:border-(--color-border-strong) focus-visible:ring-2 focus-visible:ring-(--color-accent)/20"
        />
      </label>
      {(freeCount > 0 || visionCount > 0) && (
        <div className="flex shrink-0 items-center gap-1">
          <FilterChip active={filter === 'all'} onClick={() => setFilter('all')}>
            All
          </FilterChip>
          {freeCount > 0 && (
            <FilterChip active={filter === 'free'} onClick={() => setFilter('free')}>
              Free · {freeCount}
            </FilterChip>
          )}
          {visionCount > 0 && (
            <FilterChip
              active={filter === 'vision'}
              onClick={() => setFilter('vision')}
            >
              Vision · {visionCount}
            </FilterChip>
          )}
        </div>
      )}
      <div
        id={listboxId}
        className={cn(
          'max-h-56 overflow-y-auto overscroll-contain',
          listClassName,
        )}
        role="listbox"
        aria-label="Models"
      >
        {visibleModels.length === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-(--color-text-muted)">
            No models found
          </p>
        ) : (
          <div className="flex flex-col gap-0.5">
            {visibleModels.map((model) => {
              const selected = model.id === selectedModel
              const provider = providerOf(model.id)
              const index = enterIndex(model.id)
              const enter = index !== undefined ? fadeRise(preset, 6) : null
              // Context window and price, both catalog facts. Either may be
              // absent — a local or newly listed model has neither — so the
              // row degrades to just its name rather than showing zeroes.
              const meta = [
                formatTokenCount(model.context_length),
                model.free ? '' : formatModelPrice(model.cost),
              ]
                .filter(Boolean)
                .join(' · ')
              const option = (
                <button
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onClick={() => onSelect(model.id)}
                  className={cn(
                    'relative flex min-h-8 w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[11px] outline-none transition-colors',
                    'hover:bg-(--bg-key) focus-visible:bg-(--bg-key)',
                    selected
                      ? 'bg-(--bg-key) text-(--color-text)'
                      : 'text-(--color-text-2)',
                  )}
                >
                  {selected && (
                    <span
                      aria-hidden="true"
                      className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-(--color-accent)"
                    />
                  )}
                  <ProviderBrandIcon providerId={model.id} size="xs" />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span className="min-w-0 flex-1 truncate font-medium">
                        {shortModelName(model.id)}
                      </span>
                      {model.free && (
                        <span className="shrink-0 rounded bg-(--color-success-subtle) px-1 py-px text-[9px] font-medium tracking-wide text-(--color-success) uppercase">
                          free
                        </span>
                      )}
                      {model.status && (
                        <span
                          className={cn(
                            'shrink-0 rounded px-1 py-px text-[9px] font-medium tracking-wide uppercase',
                            model.status === 'deprecated'
                              ? 'bg-(--color-danger)/12 text-(--color-danger)'
                              : 'bg-(--color-accent)/12 text-(--color-accent)',
                          )}
                        >
                          {model.status}
                        </span>
                      )}
                    </span>
                    {(meta || provider) && (
                      <span className="flex min-w-0 items-center gap-1.5 font-mono text-[9.5px] text-(--color-text-subtle)">
                        {provider && (
                          <span className="shrink-0 tracking-wide uppercase">
                            {provider}
                          </span>
                        )}
                        {meta && <span className="truncate tabular-nums">{meta}</span>}
                      </span>
                    )}
                  </span>
                  <Check
                    aria-hidden="true"
                    size={12}
                    className={cn(
                      'shrink-0 text-(--color-accent)',
                      selected ? 'opacity-100' : 'opacity-0',
                    )}
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
                  transition={{
                    ...enter.transition,
                    delay: staggerDelay(preset, index),
                  }}
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
