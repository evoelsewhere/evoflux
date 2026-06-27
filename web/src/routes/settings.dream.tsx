/** /settings/dream — edit Dream runtime settings. */
import { useMemo, useState } from 'react'
import { ArrowLeft, Moon, Play, Save } from 'lucide-react'

import {
  useDreamConfigQuery,
  useUpdateDreamConfigMutation,
  useTriggerDreamMutation,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { useIsMobile } from '@/hooks/use-mobile'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { ModelCombobox } from '@/components/settings/AgentForm'
import { validateModel } from '@/components/settings/schema'
import { useRegistryQuery } from '@/queries'
import type { DreamConfig } from '@/api/client'

const DEFAULT_FORM: DreamConfig = {
  enabled: false,
  model: '',
  schedule: '0 2 * * *',
}

function normalized(form: DreamConfig): DreamConfig {
  return {
    enabled: form.enabled,
    model: form.model.trim(),
    schedule: form.schedule.trim() || '0 2 * * *',
  }
}

export function DreamSettingsPage() {
  const isMobile = useIsMobile()
  const settingsNavigate = useSettingsNavigate()
  const { data, isLoading, error } = useDreamConfigQuery()
  const updateMut = useUpdateDreamConfigMutation()
  const dreamMut = useTriggerDreamMutation()
  const registry = useRegistryQuery()
  const push = useToastStore((s) => s.push)

  const [form, setForm] = useState<DreamConfig>(DEFAULT_FORM)
  const [sourceRaw, setSourceRaw] = useState<DreamConfig | null>(null)

  if (data && data !== sourceRaw) {
    setForm(data)
    setSourceRaw(data)
  }

  const dirty = useMemo(() => {
    if (!sourceRaw) return false
    const current = normalized(form)
    const source = normalized(sourceRaw)
    return (
      current.enabled !== source.enabled ||
      current.model !== source.model ||
      current.schedule !== source.schedule
    )
  }, [form, sourceRaw])
  const modelOptions = useMemo(() => registry.data?.models ?? [], [registry.data?.models])
  const validModelIds = useMemo(() => modelOptions.map((m) => m.id), [modelOptions])
  const modelError = validateModel(form.model, { validValues: validModelIds })

  const setField = <K extends keyof DreamConfig>(key: K, val: DreamConfig[K]) =>
    setForm((prev) => ({ ...prev, [key]: val }))

  const handleSave = async () => {
    try {
      const saved = await updateMut.mutateAsync(normalized(form))
      setSourceRaw(saved)
      push({ tone: 'success', title: 'Dream settings saved' })
    } catch (err) {
      push({
        tone: 'error',
        title: 'Save failed',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  const handleRunNow = async () => {
    try {
      const result = await dreamMut.mutateAsync()
      if (result.skipped) {
        push({
          tone: 'info',
          title: 'Dream skipped',
          description: `${result.skipped}. ${result.remaining ?? 0} pending.`,
        })
        return
      }
      push({
        tone: 'success',
        title: 'Dream run complete',
        description: `${result.sessions_processed} sessions, ${result.notes_processed} notes processed.`,
      })
    } catch (err) {
      push({
        tone: 'error',
        title: 'Dream run failed',
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
        <Moon size={15} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
        <h1 className="flex-1 truncate text-sm font-semibold text-(--color-text)">Dream</h1>
        {dirty && <span className="text-xs text-(--color-text-muted)">Unsaved</span>}
        <Button size="sm" variant="outline" className="min-h-11 md:min-h-0" onClick={handleRunNow} disabled={dreamMut.isPending}>
          <Play size={12} aria-hidden="true" />
          <span className="hidden sm:inline">{dreamMut.isPending ? 'Running...' : 'Run now'}</span>
        </Button>
        <Button size="sm" className="min-h-11 md:min-h-0" onClick={handleSave} disabled={!dirty || !!modelError || updateMut.isPending}>
          <Save size={12} aria-hidden="true" />
          <span className="hidden sm:inline">{updateMut.isPending ? 'Saving...' : 'Save'}</span>
        </Button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-5 p-6">
          <p className="text-sm leading-relaxed text-(--color-text-muted)">
            Dream synthesises unprocessed conversation sessions and notes into the wiki.
            Its prompt and tools are built in; configure only when it runs and which model it uses.
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
                  Schedule
                </h2>
                <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm text-(--color-text) md:min-h-0">
                  <Switch
                    checked={form.enabled}
                    onCheckedChange={(checked) => setField('enabled', checked)}
                  />
                  Enabled
                </label>
                <div className="grid gap-1.5">
                  <label htmlFor="dream-schedule" className="text-xs font-medium text-(--color-text-muted)">
                    Cron expression
                  </label>
                  <Input
                    id="dream-schedule"
                    value={form.schedule}
                    onChange={(e) => setField('schedule', e.target.value)}
                    placeholder="0 2 * * *"
                    className="min-h-11 font-mono text-sm md:min-h-9"
                  />
                  <p className="text-xs text-(--color-text-muted)">
                    Standard 5-field cron in UTC. Disabled Dream can still be triggered with Run now.
                  </p>
                </div>
              </section>

              <section className="space-y-3 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-text-muted)">
                  Model
                </h2>
                <div className="grid gap-1.5">
                  <label htmlFor="dream-model" className="text-xs font-medium text-(--color-text-muted)">
                    Model ID
                  </label>
                  <ModelCombobox
                    value={form.model}
                    onChange={(value) => setField('model', value)}
                    options={modelOptions}
                    invalid={!!modelError}
                    placeholder="codex:gpt-5.5"
                  />
                  {modelError ? (
                    <p className="text-xs text-(--color-error)">{modelError}</p>
                  ) : (
                    <p className="text-xs text-(--color-text-muted)">
                      Choose from the same registry used by agent setup. Leave empty to skip LLM synthesis.
                    </p>
                  )}
                </div>
              </section>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
