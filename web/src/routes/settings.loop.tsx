/** /settings/loop — edit Loop runtime defaults. */
import { useMemo, useState } from 'react'
import { ArrowLeft, Repeat, Save } from 'lucide-react'

import { useLoopConfigQuery, useUpdateLoopConfigMutation } from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { useIsMobile } from '@/hooks/use-mobile'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import type { LoopConfig } from '@/api/client'

const DEFAULT_FORM: LoopConfig = {
  default_max_iterations: 10,
  default_evolve_prompt: true,
  default_verify_command: '',
  default_max_total_tokens: null,
  default_no_progress_threshold: 3,
  default_max_consecutive_errors: 3,
  default_delay_between_iterations: 0.0,
}

function normalized(form: LoopConfig): LoopConfig {
  return {
    default_max_iterations: form.default_max_iterations,
    default_evolve_prompt: form.default_evolve_prompt,
    default_verify_command: form.default_verify_command.trim(),
    default_max_total_tokens: form.default_max_total_tokens,
    default_no_progress_threshold: form.default_no_progress_threshold,
    default_max_consecutive_errors: form.default_max_consecutive_errors,
    default_delay_between_iterations: form.default_delay_between_iterations,
  }
}

function fieldsEqual(a: LoopConfig, b: LoopConfig): boolean {
  return (
    a.default_max_iterations === b.default_max_iterations &&
    a.default_evolve_prompt === b.default_evolve_prompt &&
    a.default_verify_command === b.default_verify_command &&
    a.default_max_total_tokens === b.default_max_total_tokens &&
    a.default_no_progress_threshold === b.default_no_progress_threshold &&
    a.default_max_consecutive_errors === b.default_max_consecutive_errors &&
    a.default_delay_between_iterations === b.default_delay_between_iterations
  )
}

export function LoopSettingsPage() {
  const isMobile = useIsMobile()
  const settingsNavigate = useSettingsNavigate()
  const { data, isLoading, error } = useLoopConfigQuery()
  const updateMut = useUpdateLoopConfigMutation()
  const push = useToastStore((s) => s.push)

  const [form, setForm] = useState<LoopConfig>(DEFAULT_FORM)
  const [sourceRaw, setSourceRaw] = useState<LoopConfig | null>(null)

  if (data && data !== sourceRaw) {
    setForm(data)
    setSourceRaw(data)
  }

  const dirty = useMemo(() => {
    if (!sourceRaw) return false
    return !fieldsEqual(normalized(form), normalized(sourceRaw))
  }, [form, sourceRaw])

  const setField = <K extends keyof LoopConfig>(key: K, val: LoopConfig[K]) =>
    setForm((prev) => ({ ...prev, [key]: val }))

  const handleSave = async () => {
    try {
      const saved = await updateMut.mutateAsync(normalized(form))
      setSourceRaw(saved)
      push({ tone: 'success', title: 'Loop settings saved' })
    } catch (err) {
      push({
        tone: 'error',
        title: 'Save failed',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  return (
    <>
      <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-3 border-b border-(--color-border) bg-(--bg-page) px-4">
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
        <Repeat size={15} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
        <h1 className="flex-1 truncate text-sm font-semibold text-(--color-text)">Loop</h1>
        {dirty && <span className="text-xs text-(--color-text-muted)">Unsaved</span>}
        <Button size="sm" className="min-h-11 md:min-h-0" onClick={handleSave} disabled={!dirty || updateMut.isPending}>
          <Save size={12} aria-hidden="true" />
          <span className="hidden sm:inline">{updateMut.isPending ? 'Saving...' : 'Save'}</span>
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-5 p-6">
          <p className="text-sm leading-relaxed text-(--color-text-muted)">
            Configure default loop behaviour — iterations, evolution, verification.
            These defaults apply to new loops unless overridden per-session.
          </p>

          {isLoading && <p className="text-sm text-(--color-text-muted)">Loading...</p>}
          {error && (
            <p className="text-sm text-(--color-error)">
              {error instanceof Error ? error.message : String(error)}
            </p>
          )}

          {!isLoading && !error && (
            <div className="space-y-5">
              <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Iterations
                </h2>
                <div className="grid gap-1.5">
                  <label htmlFor="loop-max-iterations" className="text-xs font-medium text-(--color-text-muted)">
                    Max iterations
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {[5, 10, 20, 50].map((n) => (
                      <button
                        key={n}
                        type="button"
                        onClick={() => setField('default_max_iterations', n)}
                        className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                          form.default_max_iterations === n
                            ? 'bg-(--color-accent) text-(--color-accent-fg)'
                            : 'border border-(--color-border) text-(--color-text-muted) hover:border-(--color-border-strong) hover:text-(--color-text)'
                        }`}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                  <p className="text-xs text-(--color-text-muted)">
                    Maximum number of loop iterations before forced stop.
                  </p>
                </div>
              </section>

              <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Evolution
                </h2>
                <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-(--color-text) md:min-h-0">
                  <Switch
                    checked={form.default_evolve_prompt}
                    onCheckedChange={(checked) => setField('default_evolve_prompt', checked)}
                  />
                  Evolve prompt between iterations
                </label>
                <p className="text-xs text-(--color-text-muted)">
                  When enabled, the loop modifies its prompt based on previous results to improve convergence.
                </p>
              </section>

              <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Verification
                </h2>
                <div className="grid gap-1.5">
                  <label htmlFor="loop-verify-command" className="text-xs font-medium text-(--color-text-muted)">
                    Verify command
                  </label>
                  <Input
                    id="loop-verify-command"
                    value={form.default_verify_command}
                    onChange={(e) => setField('default_verify_command', e.target.value)}
                    placeholder="uv run pytest -q"
                    className="min-h-11 font-mono text-sm md:min-h-9"
                  />
                  <p className="text-xs text-(--color-text-muted)">
                    Command to run after each iteration to verify progress. Leave empty to skip.
                  </p>
                </div>
              </section>

              <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Limits
                </h2>
                <div className="grid gap-1.5">
                  <label htmlFor="loop-max-tokens" className="text-xs font-medium text-(--color-text-muted)">
                    Max total tokens
                  </label>
                  <Input
                    id="loop-max-tokens"
                    type="number"
                    value={form.default_max_total_tokens ?? ''}
                    onChange={(e) =>
                      setField(
                        'default_max_total_tokens',
                        e.target.value === '' ? null : Number(e.target.value),
                      )
                    }
                    placeholder="unlimited"
                    className="min-h-11 font-mono text-sm md:min-h-9"
                  />
                  <p className="text-xs text-(--color-text-muted)">
                    Token budget across all iterations. Leave empty for unlimited.
                  </p>
                </div>
              </section>

              <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Termination
                </h2>
                <div className="grid gap-3">
                  <div className="grid gap-1.5">
                    <label htmlFor="loop-no-progress" className="text-xs font-medium text-(--color-text-muted)">
                      No-progress threshold
                    </label>
                    <Input
                      id="loop-no-progress"
                      type="number"
                      value={form.default_no_progress_threshold}
                      onChange={(e) =>
                        setField('default_no_progress_threshold', Number(e.target.value))
                      }
                      placeholder="3"
                      className="min-h-11 font-mono text-sm md:min-h-9"
                    />
                    <p className="text-xs text-(--color-text-muted)">
                      Stop after this many consecutive iterations with the same error signature.
                    </p>
                  </div>
                  <div className="grid gap-1.5">
                    <label htmlFor="loop-max-errors" className="text-xs font-medium text-(--color-text-muted)">
                      Max consecutive errors
                    </label>
                    <Input
                      id="loop-max-errors"
                      type="number"
                      value={form.default_max_consecutive_errors}
                      onChange={(e) =>
                        setField('default_max_consecutive_errors', Number(e.target.value))
                      }
                      placeholder="3"
                      className="min-h-11 font-mono text-sm md:min-h-9"
                    />
                    <p className="text-xs text-(--color-text-muted)">
                      Stop after this many consecutive errors of any kind.
                    </p>
                  </div>
                </div>
              </section>

              <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Timing
                </h2>
                <div className="grid gap-1.5">
                  <label htmlFor="loop-delay" className="text-xs font-medium text-(--color-text-muted)">
                    Delay between iterations (seconds)
                  </label>
                  <Input
                    id="loop-delay"
                    type="number"
                    step="0.1"
                    value={form.default_delay_between_iterations}
                    onChange={(e) =>
                      setField('default_delay_between_iterations', Number(e.target.value))
                    }
                    placeholder="0.0"
                    className="min-h-11 font-mono text-sm md:min-h-9"
                  />
                  <p className="text-xs text-(--color-text-muted)">
                    Pause between loop iterations in seconds. 0 means no delay.
                  </p>
                </div>
              </section>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
