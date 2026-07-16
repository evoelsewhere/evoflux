/**
 * SessionPillsRow — compact inline model/thinking/fast-mode controls.
 *
 * Rendered inside InputBar above the textarea. Each control is a minimal
 * pill button that opens a small dropdown on click. The design mirrors
 * how Gemini and Grok surface model selection: always-visible, one-tap,
 * no modal popup.
 *
 * Props mirror the slice of SessionSettingsPanel that the pills own.
 * Agent-info (capabilities + tools) is delegated to AgentInfoPopover.
 */

import { useState, useEffect, useMemo, useRef } from 'react'
import fuzzysort from 'fuzzysort'
import { ChevronDown, Zap } from 'lucide-react'
import { useRegistryQuery } from '@/queries'
import { AgentInfoPopover } from './AgentInfoPopover'

const THINKING_LEVEL_LABEL: Record<string, string> = {
  none: 'None', minimal: 'Minimal', low: 'Low',
  medium: 'Medium', high: 'High', xhigh: 'X-High', max: 'Max',
}
function buildThinkingOptions(levels: string[]) {
  return [
    { value: '', label: 'Default' },
    ...levels.map((l) => ({ value: l, label: THINKING_LEVEL_LABEL[l] ?? l })),
  ]
}

/** Short display name for a model id — strip common provider prefixes. */
function shortModelName(id: string): string {
  // "copilot:claude-haiku-4.5" → "claude-haiku-4.5"
  // "openai:gpt-4o" → "gpt-4o"
  // "ollama:llama3" → "llama3"
  const colon = id.indexOf(':')
  return colon === -1 ? id : id.slice(colon + 1)
}

// ── Model pill ───────────────────────────────────────────────────────────────

function ModelPill({
  sessionModel,
  defaultModel,
  onSelect,
}: {
  sessionModel: string | null
  defaultModel: string | null
  onSelect: (modelId: string | null) => void
}) {
  const registry = useRegistryQuery()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const modelOptions = useMemo(() => registry.data?.models ?? [], [registry.data?.models])

  const visibleOptions = useMemo(() => {
    const q = query.trim()
    if (!q) return modelOptions.slice(0, 30)
    return fuzzysort.go(q, modelOptions, { key: 'id', limit: 30 }).map((r) => r.obj)
  }, [modelOptions, query])

  const effectiveModel = sessionModel ?? defaultModel ?? ''
  const displayLabel = effectiveModel ? shortModelName(effectiveModel) : 'Model'

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
        setQuery('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const selectModel = (id: string) => {
    const trimmed = id.trim()
    onSelect(trimmed && trimmed !== defaultModel ? trimmed : null)
    setOpen(false)
    setQuery('')
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v)
          setQuery('')
          setActiveIndex(0)
          setTimeout(() => inputRef.current?.focus(), 0)
        }}
        className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Session model"
      >
        <span className="max-w-[10rem] truncate font-mono">{displayLabel}</span>
        <ChevronDown size={11} className={`shrink-0 text-(--color-text-muted) transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-1 w-[min(22rem,calc(90vw-2rem))] rounded-lg border border-(--color-border-strong) bg-(--color-surface) shadow-(--shadow-popover)">
          <div className="border-b border-(--color-border) p-2">
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setActiveIndex(0)
              }}
              onKeyDown={(e) => {
                if (e.key === 'ArrowDown') {
                  e.preventDefault()
                  setActiveIndex((i) => Math.min(i + 1, visibleOptions.length - 1))
                } else if (e.key === 'ArrowUp') {
                  e.preventDefault()
                  setActiveIndex((i) => Math.max(i - 1, 0))
                } else if (e.key === 'Enter') {
                  e.preventDefault()
                  const opt = visibleOptions[activeIndex]
                  if (opt) selectModel(opt.id)
                } else if (e.key === 'Escape') {
                  setOpen(false)
                  setQuery('')
                }
              }}
              placeholder="Search models..."
              className="w-full rounded-md border border-(--color-border) bg-(--bg-card) px-2.5 py-1.5 font-mono text-xs text-(--color-text) outline-none focus:border-(--color-accent)"
            />
          </div>
          <div className="max-h-52 overflow-auto p-1">
            {visibleOptions.length === 0 && (
              <div className="px-2 py-1.5 text-xs text-(--color-text-muted)">No models found</div>
            )}
            {visibleOptions.map((model, index) => (
              <button
                key={model.id}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => selectModel(model.id)}
                className={`block w-full rounded-sm px-2 py-1.5 text-left font-mono text-xs transition-colors ${
                  index === activeIndex
                    ? 'bg-(--bg-key) text-(--color-text)'
                    : 'text-(--color-text-muted) hover:bg-(--bg-key)'
                }`}
              >
                {model.id}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Thinking pill ────────────────────────────────────────────────────────────

function ThinkingPill({
  sessionThinkingLevel,
  thinkingLevels,
  onSelect,
}: {
  sessionThinkingLevel: string | null
  thinkingLevels: string[]
  onSelect: (level: string | null) => void
}) {
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const containerRef = useRef<HTMLDivElement>(null)

  const options = buildThinkingOptions(thinkingLevels)
  const currentLabel = options.find((l) => l.value === (sessionThinkingLevel ?? ''))?.label ?? 'Default'

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-(--color-text-2) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Thinking level"
      >
        <span>{currentLabel}</span>
        <ChevronDown size={11} className={`shrink-0 text-(--color-text-muted) transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          className="absolute bottom-full left-0 z-50 mb-1 w-36 rounded-lg border border-(--color-border-strong) bg-(--color-surface) p-1 shadow-(--shadow-popover)"
          role="listbox"
        >
          {options.map((level, index) => (
            <button
              key={level.value}
              type="button"
              role="option"
              aria-selected={level.value === (sessionThinkingLevel ?? '')}
              onMouseDown={(e) => {
                e.preventDefault()
                onSelect(level.value || null)
                setOpen(false)
              }}
              onMouseEnter={() => setActiveIndex(index)}
              className={`block w-full rounded-sm px-2 py-1.5 text-left text-xs transition-colors ${
                index === activeIndex
                  ? 'bg-(--bg-key) text-(--color-text)'
                  : 'text-(--color-text-muted) hover:bg-(--bg-key)'
              }`}
            >
              {level.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Fast mode pill ───────────────────────────────────────────────────────────

function FastModePill({
  sessionFastMode,
  available,
  onToggle,
}: {
  sessionFastMode: boolean
  available: boolean
  onToggle: (enabled: boolean) => void
}) {
  if (!available) return null

  return (
    <button
      type="button"
      onClick={() => onToggle(!sessionFastMode)}
      className={`flex items-center gap-1 rounded-md px-2 py-1 text-xs transition-colors ${
        sessionFastMode
          ? 'bg-(--color-accent) text-(--color-accent-fg)'
          : 'text-(--color-text-2) hover:bg-(--bg-key) hover:text-(--color-text)'
      }`}
      title="Fast mode"
    >
      <Zap size={11} />
      <span>Fast</span>
    </button>
  )
}

// ── Main row ─────────────────────────────────────────────────────────────────

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
  /** Agent names for the info popover. */
  agentNames?: string[]
  workspace?: string | null
  /** Roster mode for the workspace team ('coding' | 'aim'). */
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
  const registry = useRegistryQuery()
  const effectiveModel = sessionModel ?? defaultModel ?? ''
  const fastModeAvailable = effectiveModel.startsWith('codex:')
  const thinkingLevels = useMemo(() => {
    if (!effectiveModel) return []
    return registry.data?.models.find((m) => m.id === effectiveModel)?.thinking_levels ?? []
  }, [effectiveModel, registry.data?.models])

  return (
    <div className="flex items-center gap-1 px-1 pb-1">
      <ModelPill
        sessionModel={sessionModel ?? null}
        defaultModel={defaultModel ?? null}
        onSelect={(model) => {
          onSessionModelSettingsChange?.(
            model,
            sessionThinkingLevel ?? null,
            fastModeAvailable && (sessionFastMode ?? false),
          )
        }}
      />
      {thinkingLevels.length > 0 && (
        <ThinkingPill
          sessionThinkingLevel={sessionThinkingLevel ?? null}
          thinkingLevels={thinkingLevels}
          onSelect={(level) => {
            onSessionModelSettingsChange?.(
              sessionModel ?? null,
              level,
              fastModeAvailable && (sessionFastMode ?? false),
            )
          }}
        />
      )}
      <FastModePill
        sessionFastMode={sessionFastMode ?? false}
        available={fastModeAvailable}
        onToggle={(enabled) => {
          onSessionModelSettingsChange?.(
            sessionModel ?? null,
            sessionThinkingLevel ?? null,
            enabled,
          )
        }}
      />
      <div className="flex-1" />
      <AgentInfoPopover
        agentNames={agentNames}
        workspace={workspace}
        sessionModel={sessionModel ?? null}
        mode={mode}
      />
    </div>
  )
}
