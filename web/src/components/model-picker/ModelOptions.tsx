import { useId, useMemo, useState } from 'react'
import fuzzysort from 'fuzzysort'
import { motion } from 'framer-motion'
import { Check, Search } from 'lucide-react'

import { ProviderBrandIcon } from '@/components/providers/ProviderBrandIcon'
import { cn } from '@/lib/utils'
import { providerOf, shortModelName, type ModelOption } from '@/lib/model-settings'
import { fadeRise, staggerDelay, useListEnterIndex, useMotionPreset } from '@/lib/motion'

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
  const visibleModels = useMemo(() => {
    const value = query.trim()
    if (!value) return models.slice(0, limit)
    return fuzzysort
      .go(value, models, { key: 'id', limit })
      .map((result) => result.obj)
  }, [limit, models, query])
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
      <div
        id={listboxId}
        className={cn(
          'max-h-36 overflow-y-auto overscroll-contain',
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
              const option = (
                <button
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onClick={() => onSelect(model.id)}
                  className={cn(
                    'relative flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-[11px] outline-none transition-colors',
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
