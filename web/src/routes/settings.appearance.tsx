import { Check, Languages, Palette } from 'lucide-react'

import { useAppearance } from '@/hooks/useAppearance'
import { ThemeToggle } from '@/components/ThemeToggle'
import { MotionPreview } from '@/components/settings/MotionPreview'
import { SettingsGroup, SettingsPage, SettingsRow } from '@/components/settings/SettingsLayout'
import { DiscreteSlider } from '@/components/ui/discrete-slider'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { useI18n, type AppLocale } from '@/i18n'
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
  { value: 'system', label: 'System UI', description: 'Native to your operating system', family: "-apple-system, 'Segoe UI', system-ui, sans-serif" },
  { value: 'inter', label: 'Inter', description: 'Clear and balanced for product UI', family: "'Inter Variable', sans-serif" },
  { value: 'geist', label: 'Geist', description: 'Compact with strong visual rhythm', family: "'Geist Variable', sans-serif" },
  { value: 'anthropic-sans', label: 'Anthropic Sans', description: 'Warm and comfortable for reading', family: "'Anthropic Sans', 'Source Sans 3 Variable', sans-serif" },
  { value: 'mono', label: 'JetBrains Mono', description: 'Monospaced across the interface', family: "'JetBrains Mono Variable', monospace" },
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
  const { locale, setLocale } = useI18n()
  const scaleIndex = Math.max(0, FONT_SCALES.indexOf(settings.fontScale))
  const motionIndex = Math.max(0, MOTION_INTENSITIES.indexOf(settings.motionIntensity))
  const motionOption = MOTION_OPTIONS[motionIndex] ?? MOTION_OPTIONS[2]

  return (
      <SettingsPage
        icon={Palette}
        title="Appearance"
      lede="Tune contrast, typography and motion. Changes apply immediately and stay on this machine."
    >
      <SettingsGroup title="Language & region">
        <SettingsRow
          label="Display language"
          description="Choose the language used across EvoFlux. Changes apply immediately and stay on this machine."
          control={
            <NativeSelect
              platformNative
              value={locale}
              aria-label="Display language"
              onChange={(event) => setLocale(event.target.value as AppLocale)}
              className="min-w-40"
            >
              <NativeSelectOption value="en" data-i18n-ignore>English</NativeSelectOption>
              <NativeSelectOption value="vi" data-i18n-ignore>Tiếng Việt</NativeSelectOption>
              <NativeSelectOption value="ja" data-i18n-ignore>日本語</NativeSelectOption>
            </NativeSelect>
          }
        />
        <SettingsRow
          label="Regional formatting"
          description="Dates, times and numbers follow the selected display language. Your configured time zone is unchanged."
          control={<Languages size={17} className="text-(--color-text-muted)" aria-hidden="true" />}
        />
      </SettingsGroup>

      <SettingsGroup title="Theme">
        <SettingsRow
          label="Color scheme"
          description="Follow the system setting or pin the app to light or dark."
          control={<ThemeToggle />}
        />
        <SettingsRow
          label="Accent"
          description="Used for actions, selection, focus and active states."
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
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)/35',
                      active
                        ? 'border-(--color-border-strong) bg-(--bg-key)'
                        : 'border-transparent hover:bg-(--bg-key)',
                    )}
                  >
                    <span
                      className="flex size-5 items-center justify-center rounded-full ring-1 ring-inset ring-black/15"
                      style={{
                        background:
                          opt.value === 'default' ? 'var(--color-accent)' : `var(--accent-${opt.value})`,
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
              label="Interface size"
              valueLabel={`${Math.round(settings.fontScale * 100)}%`}
              index={scaleIndex}
              marks={FONT_SCALES.map((scale) => `${Math.round(scale * 100)}%`)}
              hint="100% is the balanced default. Choose a smaller size for density or a larger size for longer reading sessions."
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
              <MotionPreview intensity={settings.motionIntensity} />
            </div>
          }
        />
      </SettingsGroup>
    </SettingsPage>
  )
}
