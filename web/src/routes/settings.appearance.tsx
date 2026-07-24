import { Check, Palette } from 'lucide-react'

import { useAppearance } from '@/hooks/useAppearance'
import { ThemeToggle } from '@/components/ThemeToggle'
import { MotionPreview } from '@/components/settings/MotionPreview'
import { SettingsGroup, SettingsPage, SettingsRow } from '@/components/settings/SettingsLayout'
import { DiscreteSlider } from '@/components/ui/discrete-slider'
import { cn } from '@/lib/utils'
import {
  FONT_SCALES,
  MOTION_INTENSITIES,
  type AccentColor,
  type FontFamily,
  type FontScale,
  type MotionIntensity,
} from '@/lib/appearance'

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
  { value: 'anthropic-sans', label: 'Anthropic Sans', description: 'Claude-inspired', family: "'Anthropic Sans', 'Source Sans 3 Variable', sans-serif" },
]

const MOTION_OPTIONS: ReadonlyArray<{ value: MotionIntensity; label: string; description: string }> = [
  {
    value: 'reduced',
    label: 'Reduced',
    description: 'Transitions resolve instantly. Progress spinners keep turning so nothing looks stuck.',
  },
  {
    value: 'subtle',
    label: 'Subtle',
    description: 'Short fades, no overshoot, and decorative loops stay off.',
  },
  {
    value: 'standard',
    label: 'Standard',
    description: 'The product default. Panels, menus and lists move at a normal pace.',
  },
  {
    value: 'expressive',
    label: 'Expressive',
    description: 'Springier controls and longer travel on entering elements.',
  },
  {
    value: 'cinematic',
    label: 'Cinematic',
    description: 'Slow, weighty motion with the most pronounced spring.',
  },
]

export function AppearanceSettingsPage() {
  const { settings, update } = useAppearance()
  const scaleIndex = Math.max(0, FONT_SCALES.indexOf(settings.fontScale))
  const motionIndex = Math.max(0, MOTION_INTENSITIES.indexOf(settings.motionIntensity))
  const motionOption = MOTION_OPTIONS[motionIndex] ?? MOTION_OPTIONS[2]

  return (
    <SettingsPage
      icon={Palette}
      title="Appearance"
      lede="Theme, type and motion. Every change applies immediately across the app and is remembered on this machine."
    >
      <SettingsGroup title="Theme">
        <SettingsRow
          label="Color scheme"
          description="Follow the system setting or pin the app to light or dark."
          control={<ThemeToggle />}
        />
        <SettingsRow
          label="Accent"
          description="Used for selection, focus and active states."
          stacked
          control={
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Accent color">
              {ACCENT_OPTIONS.map((opt) => {
                const active = settings.accent === opt.value
                return (
                  <button
                    key={opt.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    aria-label={opt.label}
                    title={opt.label}
                    onClick={() => update({ accent: opt.value })}
                    className={cn(
                      'flex size-11 items-center justify-center rounded-md border transition-colors md:size-9',
                      active
                        ? 'border-(--color-border-strong) bg-(--bg-key)'
                        : 'border-transparent hover:bg-(--bg-key)',
                    )}
                  >
                    <span
                      className="flex size-5 items-center justify-center rounded-full ring-1 ring-inset ring-black/15"
                      style={{
                        background:
                          opt.value === 'default' ? 'var(--color-text-muted)' : `var(--accent-${opt.value})`,
                      }}
                      aria-hidden="true"
                    >
                      {active && <Check size={12} strokeWidth={3} className="text-(--bg-page)" />}
                    </span>
                  </button>
                )
              })}
            </div>
          }
        />
      </SettingsGroup>

      <SettingsGroup title="Typography">
        <SettingsRow
          label="Interface font"
          description="Applies to every surface except code blocks, which stay monospaced."
          stacked
          control={
            <div role="radiogroup" aria-label="Font family" className="grid gap-1.5 sm:grid-cols-2">
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
                      'flex items-center gap-3 rounded-md border p-2.5 text-left outline-none transition-colors',
                      'focus-visible:ring-2 focus-visible:ring-(--focus-ring)/35 active:translate-y-px',
                      active
                        ? 'border-(--color-border-strong) bg-(--bg-key)'
                        : 'border-(--color-border) hover:border-(--color-border-strong) hover:bg-(--bg-key)/60',
                    )}
                  >
                    <span
                      className="flex size-8 shrink-0 items-center justify-center rounded bg-(--color-surface-2) text-sm font-semibold text-(--color-text)"
                      style={{ fontFamily: opt.family }}
                      aria-hidden="true"
                    >
                      Aa
                    </span>
                    <span className="min-w-0">
                      <span
                        className="block text-sm text-(--color-text)"
                        style={{ fontFamily: opt.family }}
                      >
                        {opt.label}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-(--color-text-muted)">
                        {opt.description}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          }
        />

        <SettingsRow
          stacked
          control={
            <DiscreteSlider
              label="Interface scale"
              valueLabel={`${Math.round(settings.fontScale * 100)}%`}
              index={scaleIndex}
              marks={FONT_SCALES.map((scale) => `${Math.round(scale * 100)}`)}
              hint="Scales every size in the app, including this page."
              onChange={(nextIndex) => {
                const next = FONT_SCALES[nextIndex] as FontScale | undefined
                if (next != null) update({ fontScale: next })
              }}
            />
          }
        />
      </SettingsGroup>

      <SettingsGroup
        title="Motion"
        description="One setting drives panel transitions, menus, list reveals, switches and drag physics everywhere in the app. The system reduced-motion preference always wins."
      >
        <SettingsRow
          stacked
          control={
            <div className="space-y-3.5">
              <DiscreteSlider
                label="UI animations"
                valueLabel={motionOption.label}
                index={motionIndex}
                marks={MOTION_OPTIONS.map((option) => option.label)}
                color="var(--thinking-medium)"
                hint={motionOption.description}
                onChange={(nextIndex) => {
                  const next = MOTION_INTENSITIES[nextIndex] as MotionIntensity | undefined
                  if (next != null) update({ motionIntensity: next })
                }}
              />
              <MotionPreview />
            </div>
          }
        />
      </SettingsGroup>
    </SettingsPage>
  )
}
