import { ArrowLeft, Palette } from 'lucide-react'

import { useIsMobile } from '@/hooks/use-mobile'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { useAppearance } from '@/hooks/useAppearance'
import { ThemeToggle } from '@/components/ThemeToggle'
import { cn } from '@/lib/utils'
import type { AccentColor, FontFamily, FontScale } from '@/lib/appearance'

const ACCENT_OPTIONS: ReadonlyArray<{ value: AccentColor; label: string }> = [
  { value: 'default', label: 'Default' },
  { value: 'blue', label: 'Blue' },
  { value: 'green', label: 'Green' },
  { value: 'orange', label: 'Orange' },
  { value: 'pink', label: 'Pink' },
  { value: 'purple', label: 'Purple' },
  { value: 'red', label: 'Red' },
]

const FONT_OPTIONS: ReadonlyArray<{ value: FontFamily; label: string; description: string; family: string }> = [
  { value: 'inter', label: 'Inter', description: 'Balanced default for dense product UI', family: "'Inter Variable', sans-serif" },
  { value: 'system', label: 'System UI', description: 'Native to your operating system', family: "-apple-system, 'Segoe UI', system-ui, sans-serif" },
  { value: 'mono', label: 'Monospace', description: 'JetBrains Mono across the full interface', family: "'JetBrains Mono Variable', monospace" },
  { value: 'geist', label: 'Geist', description: 'ChatGPT-inspired', family: "'Geist Variable', sans-serif" },
  { value: 'source-sans', label: 'Source Sans 3', description: 'Claude-inspired', family: "'Source Sans 3 Variable', sans-serif" },
]

const SCALE_OPTIONS: ReadonlyArray<{ value: FontScale; label: string }> = [
  { value: 0.9, label: '90%' },
  { value: 1, label: '100%' },
  { value: 1.1, label: '110%' },
  { value: 1.2, label: '120%' },
]

export function AppearanceSettingsPage() {
  const isMobile = useIsMobile()
  const settingsNavigate = useSettingsNavigate()
  const { settings, update } = useAppearance()

  return (
    <>
      <header className="sticky top-0 z-(--z-panel) flex h-14 shrink-0 items-center gap-3 border-b border-(--color-border) bg-(--bg-page) px-4">
        {isMobile && (
          <button
            type="button"
            onClick={() => settingsNavigate('/settings')}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
            aria-label="Back to settings"
          >
            <ArrowLeft size={14} />
          </button>
        )}
        <Palette size={15} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
        <h1 className="flex-1 truncate text-sm font-semibold text-(--color-text)">Appearance</h1>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-5 p-6">
          <p className="text-sm leading-relaxed text-(--color-text-muted)">
            Customize how EvoFlux looks. Changes apply immediately across the whole app.
          </p>

          <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
              Theme
            </h2>
            <ThemeToggle />
          </section>

          <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
              Accent color
            </h2>
            <div className="flex flex-wrap gap-2">
              {ACCENT_OPTIONS.map((opt) => {
                const active = settings.accent === opt.value
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => update({ accent: opt.value })}
                    aria-pressed={active}
                    title={opt.label}
                    className={cn(
                      'flex h-9 items-center gap-2 rounded-md border px-2.5 text-xs font-medium transition-colors',
                      active
                        ? 'border-(--color-border-strong) bg-(--bg-key) text-(--color-text)'
                        : 'border-(--color-border) text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
                    )}
                  >
                    <span
                      className="h-4 w-4 shrink-0 rounded-full ring-1 ring-inset ring-(--color-border-strong)"
                      style={{
                        background: opt.value === 'default' ? 'var(--color-text-muted)' : `var(--accent-${opt.value})`,
                      }}
                      aria-hidden="true"
                    />
                    {opt.label}
                  </button>
                )
              })}
            </div>
          </section>

          <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
              Font
            </h2>
            <div role="radiogroup" aria-label="Font family" className="grid gap-2 sm:grid-cols-2">
              {FONT_OPTIONS.map((opt) => {
                const active = settings.fontFamily === opt.value
                return (
                  <button
                    key={opt.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => update({ fontFamily: opt.value })}
                    className={cn(
                      'group flex min-h-16 items-center gap-3 rounded-[10px] border p-3 text-left outline-none transition-[background-color,border-color,color,box-shadow,transform] duration-150 focus-visible:ring-2 focus-visible:ring-(--focus-ring)/35 active:translate-y-px',
                      active
                        ? 'border-(--color-border-strong) bg-(--bg-key) text-(--color-text)'
                        : 'border-(--color-border) bg-(--bg-page) text-(--color-text-muted) hover:border-(--color-border-strong) hover:bg-(--bg-key)',
                    )}
                  >
                    <span
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-(--color-surface-2) text-base font-semibold text-(--color-text)"
                      style={{ fontFamily: opt.family }}
                      aria-hidden="true"
                    >
                      Aa
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-(--color-text)" style={{ fontFamily: opt.family }}>
                        {opt.label}
                      </span>
                      <span className="mt-0.5 block text-xs leading-snug text-(--color-text-muted)">{opt.description}</span>
                    </span>
                  </button>
                )
              })}
            </div>
          </section>

          <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
              UI scale
            </h2>
            <div
              role="radiogroup"
              aria-label="UI scale"
              className="inline-flex items-center overflow-hidden rounded-md border border-(--color-border-subtle) p-0.5"
            >
              {SCALE_OPTIONS.map((opt) => {
                const active = settings.fontScale === opt.value
                return (
                  <button
                    key={opt.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => update({ fontScale: opt.value })}
                    className={cn(
                      'h-7 rounded-sm px-2.5 text-xs font-medium transition-colors',
                      active
                        ? 'bg-(--color-surface-2) text-(--color-text)'
                        : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text-2)',
                    )}
                  >
                    {opt.label}
                  </button>
                )
              })}
            </div>
          </section>

        </div>
      </div>
    </>
  )
}
