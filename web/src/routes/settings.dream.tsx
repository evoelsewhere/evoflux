/** /settings/dream — edit Dream runtime settings. */
import { useMemo, useState } from 'react'
import { Moon, Play, Save } from 'lucide-react'

import {
  useDreamConfigQuery,
  useUpdateDreamConfigMutation,
  useTriggerDreamMutation,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import {
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
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
  const { data, isLoading, error, refetch } = useDreamConfigQuery()
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
    <SettingsPage
      icon={Moon}
      title="Dream"
      lede="Dream folds unprocessed sessions and notes into the wiki on a schedule. Its prompt and tools are built in, so only timing and model are configurable."
      actions={
        <div className="flex items-center gap-2">
          {dirty && (
            <span className="text-xs text-(--color-text-muted)" aria-live="polite">
              Unsaved
            </span>
          )}
          <Button
            size="sm"
            variant="outline"
            className="min-h-11 md:min-h-0"
            onClick={handleRunNow}
            disabled={dreamMut.isPending}
            aria-label={dreamMut.isPending ? 'Running Dream now' : 'Run Dream now'}
          >
            <Play size={12} aria-hidden="true" />
            <span className="hidden sm:inline">{dreamMut.isPending ? 'Running…' : 'Run now'}</span>
          </Button>
          <Button
            size="sm"
            className="min-h-11 md:min-h-0"
            onClick={handleSave}
            disabled={!dirty || !!modelError || updateMut.isPending}
            aria-label={updateMut.isPending ? 'Saving Dream settings' : 'Save Dream settings'}
          >
            <Save size={12} aria-hidden="true" />
            <span className="hidden sm:inline">{updateMut.isPending ? 'Saving…' : 'Save'}</span>
          </Button>
        </div>
      }
    >
      <SettingsAsyncBoundary
        loading={isLoading}
        hasData={Boolean(data)}
        error={error}
        variant="detail"
        loadingLabel="Loading Dream settings"
        errorTitle="Failed to load Dream settings"
        onRetry={() => void refetch()}
      >
      {data && (
        <>
          <SettingsGroup title="Schedule">
            <SettingsRow
              label="Run on a schedule"
              description="When off, Dream only runs from the Run now button."
              control={
                <Switch
                  checked={form.enabled}
                  onCheckedChange={(checked) => setField('enabled', checked)}
                  aria-label="Run Dream on a schedule"
                />
              }
            />
            <SettingsRow
              label="Cron expression"
              description="Standard 5-field cron, evaluated in UTC."
              htmlFor="dream-schedule"
              stacked
              control={
                <Input
                  id="dream-schedule"
                  value={form.schedule}
                  onChange={(e) => setField('schedule', e.target.value)}
                  placeholder="0 2 * * *"
                  disabled={!form.enabled}
                  className="min-h-11 font-mono text-sm md:min-h-9"
                />
              }
            />
          </SettingsGroup>

          <SettingsGroup title="Model">
            <SettingsRow
              label="Synthesis model"
              description="Picked from the same registry as agent setup. Leave empty to skip LLM synthesis and only index raw material."
              stacked
              control={
                <div className="space-y-1.5">
                  {registry.isLoading ? (
                    <div role="status" aria-live="polite" aria-label="Loading model registry">
                      <span className="sr-only">Loading model registry</span>
                      <Skeleton className="h-9 w-full rounded-md" />
                    </div>
                  ) : (
                    <ModelCombobox
                      value={form.model}
                      onChange={(value) => setField('model', value)}
                      options={modelOptions}
                      invalid={!!modelError}
                      placeholder="codex:gpt-5.5"
                    />
                  )}
                  {modelError && <p className="text-xs text-(--color-error)">{modelError}</p>}
                </div>
              }
            />
          </SettingsGroup>
        </>
      )}
      </SettingsAsyncBoundary>
    </SettingsPage>
  )
}
