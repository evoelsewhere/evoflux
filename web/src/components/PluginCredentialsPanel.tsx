import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Code2, KeyRound, Loader2, Save, ShieldCheck, Trash2 } from 'lucide-react'

import {
  clearPluginCredentials,
  getPluginCredentials,
  updatePluginCredentials,
} from '@/api/client'
import type { PluginCredentialState, PluginInstallation } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { queryKeys } from '@/queries/keys'
import { useToastStore } from '@/stores/useToastStore'

type DraftValues = Record<string, string | boolean>

function requiredFieldIsPresent(
  field: PluginCredentialState['fields'][number],
  draft: DraftValues,
): boolean {
  if (!field.required) return true
  if (field.type === 'boolean') return typeof draft[field.key] === 'boolean'
  const value = draft[field.key]
  if (typeof value === 'string' && value.trim().length > 0) return true
  return field.type === 'secret' && field.configured
}

function draftFrom(state: PluginCredentialState | undefined): DraftValues {
  if (!state) return {}
  return Object.fromEntries(
    state.fields.map((field) => [
      field.key,
      field.type === 'secret'
        ? ''
        : field.type === 'boolean'
          ? field.value === true
          : typeof field.value === 'string'
            ? field.value
            : '',
    ]),
  )
}

export function PluginCredentialsPanel({
  installation,
  onBack,
  onEdit,
  onSaved,
}: {
  installation: PluginInstallation
  onBack: () => void
  onEdit: () => void
  onSaved: (credentials: PluginCredentialState) => Promise<void>
}) {
  const queryClient = useQueryClient()
  const pushToast = useToastStore((state) => state.push)
  const credentialQueryKey = queryKeys.plugins.credentials(installation.id)
  const query = useQuery({
    queryKey: credentialQueryKey,
    queryFn: () => getPluginCredentials(installation.id),
  })
  const [draft, setDraft] = useState<DraftValues>({})
  const [busy, setBusy] = useState<'save' | 'clear' | null>(null)
  const [missingKeys, setMissingKeys] = useState<Set<string>>(new Set())
  const missingRequiredLabels = query.data?.fields
    .filter((field) => field.required && !field.configured)
    .map((field) => field.label) ?? []

  useEffect(() => {
    setDraft(draftFrom(query.data))
    setMissingKeys(new Set())
  }, [query.data])

  const save = async () => {
    if (!query.data) return
    const missing = query.data.fields.filter(
      (field) => !requiredFieldIsPresent(field, draft),
    )
    if (missing.length > 0) {
      setMissingKeys(new Set(missing.map((field) => field.key)))
      pushToast({
        tone: 'error',
        title: 'Required credentials are missing',
        description: `Enter ${missing.map((field) => field.label).join(', ')} before saving.`,
      })
      return
    }
    setMissingKeys(new Set())
    setBusy('save')
    try {
      const values: Record<string, string | boolean | null> = {}
      for (const field of query.data.fields) {
        const value = draft[field.key]
        if (field.type === 'secret' && value === '') continue
        values[field.key] =
          typeof value === 'string' && field.type !== 'secret'
            ? value.trim()
            : value ?? null
      }
      const credentials = await updatePluginCredentials(installation.id, values)
      queryClient.setQueryData(credentialQueryKey, credentials)
      await onSaved(credentials)
      pushToast({
        tone: 'success',
        title: 'Plugin credentials saved',
        description: 'The MCP runtime was refreshed with the new values.',
      })
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Could not save plugin credentials',
        description: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setBusy(null)
    }
  }

  const clear = async () => {
    if (!window.confirm(`Clear all credentials for ${installation.name}?`)) return
    setBusy('clear')
    try {
      const credentials = await clearPluginCredentials(installation.id)
      queryClient.setQueryData(credentialQueryKey, credentials)
      await onSaved(credentials)
      pushToast({ tone: 'success', title: 'Plugin credentials cleared' })
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Could not clear plugin credentials',
        description: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="flex h-full min-h-0 flex-col bg-(--bg-page)">
      <header className="border-b border-(--color-border) px-5 py-4">
        <button
          type="button"
          onClick={onBack}
          className="mb-2 inline-flex items-center gap-1 text-xs text-(--color-text-muted) hover:text-(--color-text)"
        >
          <ArrowLeft size={13} /> Plugin Center
        </button>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <KeyRound className="text-(--color-accent)" size={19} />
              <h2 className="truncate text-lg font-semibold text-(--color-text)">{installation.name} credentials</h2>
            </div>
            <p className="mt-1 text-sm text-(--color-text-muted)">
              Stored outside the plugin package and injected only into its MCP process.
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={onEdit}>
            <Code2 /> Edit plugin
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {query.isLoading ? (
          <div className="flex justify-center py-16"><Loader2 className="animate-spin text-(--color-text-subtle)" /></div>
        ) : query.isError ? (
          <div className="rounded-lg bg-(--color-error-subtle) p-4 text-sm text-(--color-error)">
            {query.error instanceof Error ? query.error.message : 'Could not load credentials.'}
          </div>
        ) : !query.data?.supported ? (
          <div className="rounded-xl border border-(--color-border) bg-(--bg-card) p-5">
            <h3 className="font-medium text-(--color-text)">No credential schema declared</h3>
            <p className="mt-2 text-sm text-(--color-text-muted)">
              Add an <code className="rounded bg-(--bg-key) px-1">evoflux.credentials</code> extension to plugin.json, then return here to configure its fields.
            </p>
            <Button className="mt-4" variant="outline" onClick={onEdit}><Code2 /> Open plugin.json</Button>
          </div>
        ) : (
          <div className="mx-auto max-w-2xl space-y-4">
            <div className="flex items-center gap-2 rounded-lg border border-(--color-border) bg-(--bg-card) px-3 py-2 text-sm">
              <ShieldCheck className={query.data.configured ? 'text-(--color-success)' : 'text-(--color-warning)'} size={17} />
              <span className="text-(--color-text-2)">
                {query.data.configured
                  ? 'All required credentials are configured.'
                  : `Missing required credentials: ${missingRequiredLabels.join(', ')}.`}
              </span>
            </div>
            {query.data.error && <p className="text-sm text-(--color-error)">{query.data.error}</p>}
            <div className="space-y-4 rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
              {query.data.fields.map((field) => (
                <label key={field.key} className="block">
                  <span className="flex items-center gap-1 text-sm font-medium text-(--color-text)">
                    {field.label}
                    {field.required && <span className="text-(--color-error)">*</span>}
                  </span>
                  {field.description && <span className="mt-0.5 block text-xs text-(--color-text-subtle)">{field.description}</span>}
                  {field.type === 'boolean' ? (
                    <div className="mt-2 flex items-center gap-2">
                      <Switch
                        checked={draft[field.key] === true}
                        onCheckedChange={(checked) => setDraft((current) => ({ ...current, [field.key]: checked }))}
                        aria-label={field.label}
                      />
                      <span className="text-xs text-(--color-text-muted)">{draft[field.key] === true ? 'Enabled' : 'Disabled'}</span>
                    </div>
                  ) : (
                    <Input
                      className="mt-2"
                      type={field.type === 'secret' ? 'password' : field.type === 'url' ? 'url' : 'text'}
                      value={typeof draft[field.key] === 'string' ? String(draft[field.key]) : ''}
                      onChange={(event) => {
                        setDraft((current) => ({ ...current, [field.key]: event.target.value }))
                        setMissingKeys((current) => {
                          if (!current.has(field.key)) return current
                          const next = new Set(current)
                          next.delete(field.key)
                          return next
                        })
                      }}
                      placeholder={field.type === 'secret' && field.configured ? 'Configured — leave blank to keep' : field.placeholder}
                      aria-label={field.label}
                      aria-invalid={missingKeys.has(field.key)}
                      autoComplete="off"
                    />
                  )}
                  {missingKeys.has(field.key) && (
                    <span className="mt-1 block text-xs text-(--color-error)">
                      {field.label} is required.
                    </span>
                  )}
                  <span className="mt-1 block font-mono text-[10px] text-(--color-text-subtle)">env: {field.env}</span>
                </label>
              ))}
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="destructive" onClick={() => void clear()} disabled={busy !== null}>
                {busy === 'clear' ? <Loader2 className="animate-spin" /> : <Trash2 />} Clear
              </Button>
              <Button onClick={() => void save()} disabled={busy !== null}>
                {busy === 'save' ? <Loader2 className="animate-spin" /> : <Save />} Save credentials
              </Button>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
