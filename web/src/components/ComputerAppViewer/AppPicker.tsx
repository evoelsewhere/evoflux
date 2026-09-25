/**
 * Pick apps by what they look like, not by executable name.
 *
 * Lists the programs on this computer — the ones open right now first, then
 * the Start menu — each with its own icon, and stores the executable name
 * the policy matches on. A name typed into the search that matches nothing
 * can still be added, for an app that is not installed yet.
 */
import { useMemo, useRef, useState } from 'react'
import { AppWindow, Check, ChevronDown, Plus, Search, X } from 'lucide-react'

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'
import { normalizeExe, type InstalledApp } from './useInstalledApps'

export function AppPicker({
  value,
  onChange,
  apps,
  loading = false,
  placeholder,
  ariaLabel,
  disabled = false,
}: {
  value: string[]
  onChange: (next: string[]) => void
  apps: InstalledApp[]
  loading?: boolean
  placeholder: string
  ariaLabel: string
  disabled?: boolean
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)

  const byExe = useMemo(() => new Map(apps.map((app) => [app.exe, app])), [apps])
  const selected = useMemo(() => new Set(value.map(normalizeExe)), [value])
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return apps
    return apps.filter((app) => app.name.toLowerCase().includes(needle) || app.exe.includes(needle))
  }, [apps, query])
  const custom = normalizeExe(query)
  const canAddCustom = Boolean(query.trim()) && !byExe.has(custom) && !selected.has(custom)

  const toggle = (exe: string) => {
    if (disabled) return
    onChange(selected.has(exe)
      ? value.filter((item) => normalizeExe(item) !== exe)
      : [...value, exe])
  }

  return (
    <Popover
      open={open && !disabled}
      onOpenChange={(next) => {
        if (disabled) return
        setOpen(next)
        if (!next) setQuery('')
      }}
    >
      <PopoverTrigger
        nativeButton={false}
        render={
          <div
            role="combobox"
            aria-label={ariaLabel}
            aria-expanded={open}
            aria-disabled={disabled || undefined}
            aria-haspopup="listbox"
            tabIndex={disabled ? -1 : 0}
            className={cn(
              'flex min-h-11 w-full cursor-pointer flex-wrap items-center gap-1 rounded-lg border border-(--color-border) bg-(--bg-input) px-1.5 py-1 text-sm transition-colors outline-none md:min-h-9',
              'focus-visible:border-(--focus-ring) focus-visible:ring-3 focus-visible:ring-(--focus-ring)/50',
              'aria-expanded:border-(--focus-ring)',
              disabled && 'pointer-events-none cursor-not-allowed opacity-50',
            )}
          >
            {value.length === 0 && (
              <span className="px-1.5 text-(--color-text-muted)">{placeholder}</span>
            )}
            {value.map((item) => {
              const exe = normalizeExe(item)
              const app = byExe.get(exe)
              return (
                <span
                  key={item}
                  className="flex items-center gap-1.5 rounded-md bg-(--bg-key) py-0.5 pr-1 pl-1.5 text-xs text-(--color-text)"
                  title={exe}
                >
                  <AppIcon app={app} />
                  <span className="max-w-40 truncate" data-i18n-ignore>{app?.name ?? exe}</span>
                  <button
                    type="button"
                    disabled={disabled}
                    onMouseDown={(event) => event.stopPropagation()}
                    onClick={(event) => {
                      event.preventDefault()
                      event.stopPropagation()
                      toggle(exe)
                    }}
                    aria-label={t('Remove {0}', [app?.name ?? exe])}
                    className="flex size-5 items-center justify-center rounded text-(--color-text-muted) transition-colors hover:text-(--color-text)"
                  >
                    <X size={11} />
                  </button>
                </span>
              )
            })}
            <ChevronDown size={14} className="ml-auto shrink-0 text-(--color-text-muted)" aria-hidden />
          </div>
        }
      />
      <PopoverContent align="start" sideOffset={4} className="w-[--anchor-width] min-w-80 max-w-[30rem] p-0">
        <div className="flex items-center gap-2 border-b border-(--color-border) px-2.5 py-2">
          <Search size={13} className="shrink-0 text-(--color-text-muted)" aria-hidden />
          <input
            ref={searchRef}
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                const first = filtered[0]
                if (first) toggle(first.exe)
                else if (canAddCustom) toggle(custom)
              } else if (event.key === 'Escape') {
                setOpen(false)
              }
            }}
            placeholder={t('Search apps…')}
            className="flex-1 bg-transparent text-sm text-(--color-text) outline-none placeholder:text-(--color-text-muted)"
            aria-label={t('Search apps')}
          />
        </div>
        <ul role="listbox" aria-multiselectable className="max-h-72 overflow-y-auto py-1">
          {loading && (
            <li className="px-3 py-4 text-center text-sm text-(--color-text-muted)">{t('Finding apps…')}</li>
          )}
          {!loading && filtered.length === 0 && !canAddCustom && (
            <li className="px-3 py-4 text-center text-sm text-(--color-text-muted)">{t('No apps match')}</li>
          )}
          {filtered.map((app) => {
            const isSelected = selected.has(app.exe)
            return (
              <li key={app.exe}>
                <button
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    toggle(app.exe)
                    searchRef.current?.focus()
                  }}
                  className="flex w-full items-center gap-2.5 px-2.5 py-1.5 text-left transition-colors hover:bg-(--bg-key)"
                >
                  <AppIcon app={app} size="md" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-(--color-text)" data-i18n-ignore>{app.name}</span>
                    <span className="block truncate font-mono text-[11px] text-(--color-text-muted)">{app.exe}</span>
                  </span>
                  {app.running && (
                    <span className="shrink-0 rounded-full bg-(--color-accent)/12 px-1.5 py-0.5 text-[10px] text-(--color-accent)">
                      {t('Open')}
                    </span>
                  )}
                  <span
                    className={cn(
                      'flex size-4 shrink-0 items-center justify-center rounded-sm border',
                      isSelected ? 'border-(--color-text) bg-(--color-text) text-(--bg-page)' : 'border-(--color-border)',
                    )}
                    aria-hidden
                  >
                    {isSelected && <Check size={10} strokeWidth={3} />}
                  </span>
                </button>
              </li>
            )
          })}
          {canAddCustom && (
            <li>
              <button
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  toggle(custom)
                  setQuery('')
                }}
                className="flex w-full items-center gap-2.5 px-2.5 py-1.5 text-left text-sm text-(--color-text) transition-colors hover:bg-(--bg-key)"
              >
                <span className="flex size-6 items-center justify-center rounded bg-(--bg-key)"><Plus size={13} /></span>
                <span className="truncate">{t('Add "{0}"', [custom])}</span>
              </button>
            </li>
          )}
        </ul>
      </PopoverContent>
    </Popover>
  )
}

function AppIcon({ app, size = 'sm' }: { app: InstalledApp | undefined; size?: 'sm' | 'md' }) {
  const box = size === 'md' ? 'size-6' : 'size-4'
  return app?.icon
    ? <img src={app.icon} alt="" className={cn(box, 'shrink-0 object-contain')} draggable={false} />
    : (
        <span className={cn(box, 'flex shrink-0 items-center justify-center text-(--color-text-muted)')} aria-hidden>
          <AppWindow size={size === 'md' ? 16 : 12} />
        </span>
      )
}
