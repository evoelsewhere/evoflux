import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Save, Shield } from 'lucide-react'

import type { HookDefinition, HookEventName, HookSettings, HookSettingsResponse, PluginListResponse } from '@/api/types'
import {
  deleteSettingsHookWorkflowContent,
  getSettingsHookWorkflowContent,
  listPlugins,
  previewHookReplacement,
  revokePluginHookTrust,
  trustPluginHook,
} from '@/api/client'
import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
} from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useConfirm } from '@/hooks/use-confirm'
import {
  useHookSettingsQuery,
  useRevokeSettingsHookTrustMutation,
  useSaveSettingsHookWorkflowContentMutation,
  useTrustSettingsHookMutation,
  useUpdateHookSettingsMutation,
} from '@/queries'
import { useRegisterSettingsDirty } from '@/lib/settings-dirty'
import { useToastStore } from '@/stores/useToastStore'
import { queryKeys } from '@/queries/keys'
import { useI18n } from '@/i18n'

const EVENT_CHOICES: { event: HookEventName; label: string }[] = [
  { event: 'session.start', label: 'At the start of a chat' },
  { event: 'session.end', label: 'When a session ends' },
  { event: 'prompt.submit', label: 'When you send a message' },
  { event: 'agent.start', label: 'When an agent starts' },
  { event: 'agent.stop', label: 'When an agent finishes' },
  { event: 'model.before', label: 'Before the agent asks a model' },
  { event: 'model.after', label: 'After the model responds' },
  { event: 'tool.before', label: 'Before a tool runs' },
  { event: 'tool.after', label: 'After a tool finishes' },
  { event: 'completion.before', label: 'Before the agent completes a turn' },
  { event: 'compact.before', label: 'Before conversation context is shortened' },
  { event: 'compact.after', label: 'After conversation context is shortened' },
  { event: 'subagent.start', label: 'When a subagent starts' },
  { event: 'subagent.stop', label: 'When a subagent finishes' },
]

const COMMON_EVENT_IDS = new Set<HookEventName>([
  'session.start',
  'prompt.submit',
  'tool.before',
  'tool.after',
  'completion.before',
])

function workflowState(status: string | undefined, enabled: boolean): string {
  if (!enabled || status === 'disabled') return 'Plugin is off'
  switch (status) {
    case 'active': return 'On'
    case 'disabled_by_settings': return 'Paused'
    case 'replaced_by_settings': return 'Replaced by your workflow'
    case 'awaiting_trust': return 'Needs review'
    case 'blocked_isolation_unavailable': return 'Blocked on this device'
    case 'shadowed_by_settings': return 'Covered by your workflow'
    default: return 'Invalid'
  }
}

function hookIsPaused(settings: HookSettings, pluginId: string, hookId: string): boolean {
  return settings.disabled_plugin_hooks.some(
    (target) => target.plugin_id === pluginId && target.hook_id === hookId,
  )
}

function updatePausedHook(settings: HookSettings, pluginId: string, hookId: string, paused: boolean): HookSettings {
  const withoutTarget = settings.disabled_plugin_hooks.filter(
    (target) => target.plugin_id !== pluginId || target.hook_id !== hookId,
  )
  return {
    ...settings,
    disabled_plugin_hooks: paused
      ? [...withoutTarget, { plugin_id: pluginId, hook_id: hookId }]
      : withoutTarget,
  }
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableJson(item)}`)
      .join(',')}}`
  }
  return JSON.stringify(value) ?? 'undefined'
}

function hasRunnableSettingsWorkflow(
  settings: HookSettingsResponse,
  definitions: HookDefinition[],
  event: HookEventName,
): boolean {
  return definitions.some((definition) => {
    if (definition.event !== event) return false
    const savedDefinition = settings.definitions.find((saved) => saved.hook_id === definition.hook_id)
    if (!savedDefinition || stableJson(savedDefinition) !== stableJson(definition)) return false
    return settings.hook_statuses.some((status) =>
      status.hook_id === definition.hook_id
      && status.event === event
      && status.trusted
      && status.status === 'active',
    )
  })
}

function workflowTrustDescription(
  event: string,
  executionKind: string,
  inputs: string[],
  outputs: string[],
  digest: string,
  translate: (key: string) => string,
): string {
  const eventLabel = translate(EVENT_CHOICES.find((choice) => choice.event === event)?.label ?? event)
  return [
    eventLabel,
    translate(executionKind === 'static_context'
      ? 'Adds this plugin’s guidance as untrusted session context. It does not run code.'
      : 'Runs this plugin’s command. It requires verified isolation on this device.'),
    `${translate('Reads')}: ${inputs.length ? inputs.join(', ') : translate('no session data')}`,
    `${translate('Changes')}: ${outputs.length ? outputs.join(', ') : translate('nothing')}`,
    `${translate('Approve this exact package content')}: SHA-256 ${digest}`,
  ].join('\n')
}

type GuidedWorkflowDraft = {
  workflowId: string
  hookId: string | null
  name: string
  content: string
  loading: boolean
  saving: boolean
  error: string | null
}

function newWorkflowId(): string {
  return crypto.randomUUID().replaceAll('-', '').toLowerCase()
}

function workflowHookId(name: string, workflowId: string): string {
  const slug = name.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48) || 'guidance'
  return `workflow-${slug}-${workflowId.slice(0, 8)}`
}

function workflowName(hookId: string): string {
  const match = /^workflow-(.+)-[a-f0-9]{8}$/.exec(hookId)
  return match?.[1]?.replaceAll('-', ' ') ?? hookId
}

function settingsWorkflowFileId(definition: HookDefinition): string | null {
  const match = /^\.\/settings-workflows\/([a-f0-9]{32})\.md$/.exec(definition.command[0] ?? '')
  return match?.[1] ?? null
}

function SettingsWorkflowTitle({ hookId, definition }: { hookId: string; definition: HookDefinition }) {
  const workflowId = settingsWorkflowFileId(definition)
  const contentQuery = useQuery({
    queryKey: queryKeys.settings.hookWorkflowContent(workflowId ?? hookId),
    queryFn: () => {
      if (!workflowId) throw new Error('This workflow has no managed guidance file.')
      return getSettingsHookWorkflowContent(workflowId)
    },
    enabled: workflowId !== null,
    staleTime: 30_000,
  })
  const markdownTitle = contentQuery.data?.content.match(/^#\s+([^\r\n]+)/)?.[1]?.trim()
  return <h3 className="text-sm font-medium">{markdownTitle || workflowName(hookId)}</h3>
}

function editableSettings(settings: HookSettingsResponse): HookSettings {
  return {
    mode: settings.mode,
    replace_plugin_events: settings.replace_plugin_events,
    disabled_plugin_hooks: settings.disabled_plugin_hooks,
    definitions: settings.definitions,
  }
}

function formatSettings(settings: HookSettings): string {
  return JSON.stringify(settings, null, 2)
}

export function HookSettingsPage() {
  const query = useHookSettingsQuery()
  const pluginsQuery = useQuery({
    queryKey: queryKeys.plugins.list(),
    queryFn: listPlugins,
    staleTime: 5_000,
  })
  const queryClient = useQueryClient()
  const update = useUpdateHookSettingsMutation()
  const saveWorkflowContent = useSaveSettingsHookWorkflowContentMutation()
  const trust = useTrustSettingsHookMutation()
  const revoke = useRevokeSettingsHookTrustMutation()
  const { request, confirm, close } = useConfirm()
  const { t } = useI18n()
  const push = useToastStore((state) => state.push)
  const [edit, setEdit] = useState<{
    source: HookSettingsResponse
    text: string
  } | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const [workflowDraft, setWorkflowDraft] = useState<GuidedWorkflowDraft | null>(null)
  const settings = query.data ?? null
  const savedDraft = settings ? formatSettings(editableSettings(settings)) : ''
  const draft = settings && edit?.source === settings ? edit.text : savedDraft
  const dirty = draft !== savedDraft
  useRegisterSettingsDirty(dirty)

  const changePolicy = (next: HookSettings) => {
    if (!settings) return
    setEdit({ source: settings, text: formatSettings(next) })
    setParseError(null)
  }

  const pluginItems = pluginsQuery.data?.plugins ?? []
  const pluginRows = pluginItems.flatMap((item) => {
    const hooks = item.inspection.hooks ?? []
    const pluginId = item.inspection.manifest?.name ?? item.installation.name
    return hooks.map((hook) => ({
      item,
      pluginId,
      hook,
      runtime: item.inspection.hook_statuses?.find(
        (status) => status.hook_id === hook.definition.hook_id,
      ),
    }))
  })
  const eventLabel = (event: HookEventName) =>
    t(EVENT_CHOICES.find((choice) => choice.event === event)?.label ?? event)

  const reviewHook = (
    status: HookSettingsResponse['hook_statuses'][number],
    actionKind: 'trust' | 'revoke',
  ) => {
    const action = actionKind === 'revoke' ? 'Revoke trust' : 'Trust hook'
    const dataAccess = [
      `Input fields: ${status.input_fields.length ? status.input_fields.join(', ') : 'none'}`,
      `Output fields: ${status.output_fields.length ? status.output_fields.join(', ') : 'none'}`,
    ].join('\n')
    confirm({
      title: `${action}: ${status.hook_id}?`,
      description: [
        `Event: ${status.event}`,
        `Runtime: ${status.runtime} · Declared files: ${status.files.join(', ') || 'entrypoint only'}`,
        status.execution_kind === 'static_context'
          ? `Static context file: ${status.command.join(' ')}`
          : `Command: ${status.command.join(' ')}`,
        ...(status.execution_kind === 'static_context'
          ? [`Context wrapper: ${JSON.stringify(status.context_prefix)}…${JSON.stringify(status.context_suffix)}`]
          : []),
        dataAccess,
        `Isolation profile: ${status.isolation_profile}`,
        `SHA-256: ${status.digest ?? 'unavailable'}`,
        actionKind === 'revoke'
          ? 'Revoking removes approval for this hook identity.'
          : status.execution_kind === 'static_context'
            ? 'This approves only this exact digest and profile. The file content is added as untrusted session context; no command is executed.'
            : 'This approves only this exact digest and profile. Command execution still requires verified OS isolation on this host.',
      ].join('\n'),
      confirmLabel: action,
      destructive: actionKind === 'revoke',
      onConfirm: () => {
        const callbacks = {
          onError: (error: unknown) => {
            void query.refetch()
            push({
              tone: 'error',
              title: `${action} failed`,
              description: error instanceof Error ? error.message : String(error),
            })
          },
          onSuccess: () => push({ tone: 'success', title: `${action} complete` }),
        }
        if (actionKind === 'revoke') {
          revoke.mutate(status.hook_id, callbacks)
        } else if (status.digest) {
          trust.mutate({ hookId: status.hook_id, digest: status.digest }, callbacks)
        }
      },
    })
  }

  const reviewPluginWorkflow = (
    installationId: string,
    pluginName: string,
    hook: NonNullable<NonNullable<PluginListResponse['plugins'][number]['inspection']['hooks']>[number]>,
    runtime: NonNullable<NonNullable<PluginListResponse['plugins'][number]['inspection']['hook_statuses']>[number]> | undefined,
  ) => {
    if (!runtime?.digest) return
    const revoking = runtime.trusted
    const action = revoking ? t('Revoke workflow approval') : t('Allow this workflow')
    confirm({
      title: `${revoking ? t('Revoke approval') : t('Review workflow')}: ${pluginName}`,
      description: workflowTrustDescription(
        hook.definition.event,
        hook.definition.execution_kind ?? 'command',
        hook.definition.input_fields ?? [],
        hook.definition.output_fields ?? [],
        runtime.digest,
        t,
      ),
      confirmLabel: action,
      destructive: revoking,
      onConfirm: () => {
        void (async () => {
          try {
            if (revoking) await revokePluginHookTrust(installationId, hook.definition.hook_id)
            else await trustPluginHook(installationId, hook.definition.hook_id, runtime.digest!)
            await queryClient.invalidateQueries({ queryKey: queryKeys.plugins.list() })
            push({ tone: 'success', title: action })
          } catch (error) {
            push({
              tone: 'error',
              title: t('Could not update workflow approval'),
              description: error instanceof Error ? error.message : String(error),
            })
          }
        })()
      },
    })
  }

  const parsed = useMemo(() => {
    try {
      return JSON.parse(draft) as HookSettings
    } catch {
      return null
    }
  }, [draft])

  const persistSettings = async (next: HookSettings) => {
    try {
      const result = await update.mutateAsync(next)
      setEdit({ source: result, text: formatSettings(editableSettings(result)) })
      await queryClient.invalidateQueries({ queryKey: queryKeys.plugins.list() })
      push({ tone: 'success', title: 'Hook settings saved' })
      return true
    } catch (error) {
      push({
        tone: 'error',
        title: 'Save failed',
        description: error instanceof Error ? error.message : String(error),
      })
      return false
    }
  }

  const save = async () => {
    setParseError(null)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setParseError('The editor must contain a JSON object.')
      return
    }
    const previousEvents = [...(settings?.replace_plugin_events ?? [])].sort()
    const nextEvents = [...parsed.replace_plugin_events].sort()
    const replacementChanged = parsed.mode === 'replace'
      && (
        settings?.mode !== 'replace'
        || JSON.stringify(previousEvents) !== JSON.stringify(nextEvents)
      )
    if (!replacementChanged) {
      await persistSettings(parsed)
      return
    }
    try {
      const preview = await previewHookReplacement(parsed)
      const affected = preview.registrations.length === 0
        ? t('No enabled plugin workflows will be replaced.')
        : preview.registrations.map((registration) => {
            if (registration.source === 'legacy_python') {
              const uncertainty = registration.certainty === 'possible'
                ? t('This extension may affect this moment; EvoFlux did not run it to inspect its event list.')
                : t('This trusted local Python hook runs inside EvoFlux; the preview only read its source.')
              return `${eventLabel(registration.event)} — ${registration.display_name} (${t('Local Python extension')})`
                + `\n${uncertainty}`
            }
            const plugin = pluginItems.find((item) =>
              (item.inspection.manifest?.name ?? item.installation.name) === registration.plugin_id,
            )
            const displayName = plugin?.installation.name ?? registration.display_name
            return `${eventLabel(registration.event)} — ${displayName}: ${registration.hook_id}`
              + `\n${t('Installation')}: ${registration.installation_id}`
          }).join('\n')
      const hasPossibleLegacyImpact = preview.registrations.some(
        (registration) => registration.source === 'legacy_python' && registration.certainty === 'possible',
      )
      const emptyEvents = nextEvents.filter((event) => !hasRunnableSettingsWorkflow(settings!, parsed.definitions, event))
      confirm({
        title: t('Replace plugin workflows at selected moments?'),
        description: [
          `${t('Selected moments')}: ${nextEvents.map(eventLabel).join(', ')}`,
          preview.registrations.length > 0
            ? t(hasPossibleLegacyImpact
              ? 'These workflows will stop or may be affected:'
              : 'These plugin hooks will be suppressed at the selected moments:')
            : '',
          affected,
          ...emptyEvents.map((event) =>
            `${eventLabel(event)}: ${t('You have no Settings workflow for this moment, so nothing will run.')}`,
          ),
          t('EvoFlux permission and safety checks stay on.'),
        ].join('\n'),
        confirmLabel: t('Apply workflow choices'),
        destructive: true,
        onConfirm: () => void persistSettings(parsed),
      })
    } catch (error) {
      push({
        tone: 'error',
        title: 'Could not preview replacement',
        description: error instanceof Error ? error.message : String(error),
      })
    }
  }

  const startGuidedWorkflow = () => {
    setWorkflowDraft({
      workflowId: newWorkflowId(),
      hookId: null,
      name: '',
      content: '',
      loading: false,
      saving: false,
      error: null,
    })
  }

  const editGuidedWorkflow = async (definition: HookDefinition) => {
    const workflowId = settingsWorkflowFileId(definition)
    if (!workflowId) return
    setWorkflowDraft({
      workflowId,
      hookId: definition.hook_id,
      name: workflowName(definition.hook_id),
      content: '',
      loading: true,
      saving: false,
      error: null,
    })
    try {
      const saved = await getSettingsHookWorkflowContent(workflowId)
      const heading = /^#\s+([^\r\n]+)\r?\n(?:\r?\n)?/.exec(saved.content)
      setWorkflowDraft((current) => current?.workflowId === workflowId
        ? {
            ...current,
            name: heading?.[1]?.trim() || current.name,
            content: heading ? saved.content.slice(heading[0].length) : saved.content,
            loading: false,
          }
        : current)
    } catch (error) {
      setWorkflowDraft((current) => current?.workflowId === workflowId
        ? { ...current, loading: false, error: error instanceof Error ? error.message : t('Could not load this workflow.') }
        : current)
    }
  }

  const saveGuidedWorkflow = async () => {
    if (!workflowDraft || !parsed || !settings) return
    const name = workflowDraft.name.trim()
    const guidance = workflowDraft.content.trim()
    if (!name || !guidance) {
      setWorkflowDraft({ ...workflowDraft, error: t('Enter a name and some guidance text.') })
      return
    }
    const markdown = `# ${name}\n\n${guidance}\n`
    if (new TextEncoder().encode(markdown).length > 64 * 1024) {
      setWorkflowDraft({ ...workflowDraft, error: t('Guidance must be 64 KiB or less.') })
      return
    }
    setWorkflowDraft({ ...workflowDraft, saving: true, error: null })
    try {
      const contentResult = await saveWorkflowContent.mutateAsync({
        workflowId: workflowDraft.workflowId,
        content: markdown,
      })
      queryClient.setQueryData(
        queryKeys.settings.hookWorkflowContent(workflowDraft.workflowId),
        { path: contentResult.path, content: markdown },
      )
      const hookId = workflowDraft.hookId ?? workflowHookId(name, workflowDraft.workflowId)
      const definition: HookDefinition = {
        hook_id: hookId,
        event: 'session.start',
        runtime: 'native',
        command: [contentResult.path],
        files: [],
        execution_kind: 'static_context',
        context_prefix: '',
        context_suffix: '',
        timeout_seconds: 10,
        input_fields: [],
        output_fields: ['context'],
        failure_policy: 'fail_closed',
        overrides: [],
      }
      const next: HookSettings = {
        ...parsed,
        definitions: [
          ...parsed.definitions.filter((item) => item.hook_id !== hookId),
          definition,
        ],
      }
      const persisted = await persistSettings(next)
      if (persisted) setWorkflowDraft(null)
      else {
        setWorkflowDraft((current) => current?.workflowId === workflowDraft.workflowId
          ? { ...current, saving: false, error: t('The guidance file was saved, but the workflow could not be added. Retry to finish saving.') }
          : current)
      }
    } catch (error) {
      setWorkflowDraft((current) => current?.workflowId === workflowDraft.workflowId
        ? {
            ...current,
            saving: false,
            error: error instanceof Error ? error.message : t('Workflow could not be saved. Your draft is still here.'),
          }
        : current)
    }
  }

  const removeGuidedWorkflow = (hookId: string) => {
    const definition = parsed?.definitions.find((item) => item.hook_id === hookId)
    const workflowId = definition ? settingsWorkflowFileId(definition) : null
    if (!parsed || !definition || !workflowId) return
    confirm({
      title: t('Remove this workflow?'),
      description: t('This removes the Settings workflow and its approval. The plugin stays installed and enabled.'),
      confirmLabel: t('Remove workflow'),
      destructive: true,
      onConfirm: () => {
        void (async () => {
          try {
            const result = await update.mutateAsync({
              ...parsed,
              definitions: parsed.definitions.filter((item) => item.hook_id !== hookId),
            })
            setEdit({ source: result, text: formatSettings(editableSettings(result)) })
            await deleteSettingsHookWorkflowContent(workflowId)
            await queryClient.invalidateQueries({ queryKey: queryKeys.plugins.list() })
            push({ tone: 'success', title: t('Workflow removed') })
          } catch (error) {
            push({
              tone: 'error',
              title: t('Could not remove workflow'),
              description: error instanceof Error ? error.message : String(error),
            })
          }
        })()
      },
    })
  }

  return (
    <SettingsPage
      icon={Shield}
      title={t('Agent hooks')}
      lede={t('Choose what plugins do at key moments in a chat and manage your own guidance. These automatic actions are called hooks.')}
      size="wide"
      actions={(
        <Button
          type="button"
          onClick={() => void save()}
          disabled={!dirty || update.isPending || parsed === null}
        >
          <Save data-icon="inline-start" />
          Save workflows
        </Button>
      )}
    >
      <SettingsAsyncBoundary
        loading={query.isLoading}
        hasData={settings !== null}
        error={query.error}
        variant="detail"
        loadingLabel="Loading hook settings"
        errorTitle="Could not load hook settings"
        onRetry={() => void query.refetch()}
      >
        {settings && (
          <div className="space-y-8">
            {settings.execution_state === 'blocked_isolation_unavailable' && (
              <SettingsCallout tone="warning" icon={AlertTriangle}>
                <p>
                  Command hooks are blocked because this host has no verified OS
                  isolation backend. Static context hooks read one approved file and add
                  it only as untrusted session context. Saving a definition does not
                  grant trust.
                </p>
              </SettingsCallout>
            )}
            {settings.execution_state === 'available' && (
              <SettingsCallout tone="info" icon={Shield}>
                <p>
                  This host has verified OS isolation for command hooks. Each command
                  still requires digest-bound trust. Settings changes and plugin hooks
                  cannot bypass EvoFlux authorization or core runtime checks.
                </p>
              </SettingsCallout>
            )}

            <SettingsGroup
              title={t('Plugin workflows')}
              description={t('Workflows supplied by installed plugins. Pausing one here affects only that plugin workflow.')}
              stagger={false}
            >
              {pluginsQuery.isLoading ? (
                <p className="p-4 text-sm text-(--color-text-muted)">{t('Loading plugin workflows…')}</p>
              ) : pluginsQuery.error ? (
                <div className="flex flex-wrap items-center justify-between gap-3 p-4">
                  <p role="alert" className="text-sm text-(--color-error)">{t('Could not load plugin workflows.')}</p>
                  <Button type="button" size="sm" variant="outline" onClick={() => void pluginsQuery.refetch()}>{t('Retry')}</Button>
                </div>
              ) : pluginRows.length === 0 ? (
                <p className="p-4 text-sm text-(--color-text-muted)">{t('No plugin workflows found. Workflows appear here when an installed plugin provides them.')}</p>
              ) : (
                <div className="divide-y divide-(--color-border-subtle)">
                  {pluginRows.map(({ item, pluginId, hook, runtime }) => {
                    const hookId = hook.definition.hook_id
                    const paused = parsed ? hookIsPaused(parsed, pluginId, hookId) : false
                    const status = workflowState(runtime?.status, item.installation.enabled)
                    const event = hook.definition.event
                    const action = hook.definition.execution_kind === 'static_context'
                      ? t('Adds this plugin’s guidance to a new session. It does not run code.')
                      : t('Runs this plugin’s command at this moment.')
                    return (
                      <article key={`${item.installation.id}:${hookId}`} className="space-y-3 p-4 sm:p-5">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0 space-y-1">
                            <p className="text-xs font-medium text-(--color-text-muted)">{item.installation.name}</p>
                            <h3 className="text-sm font-semibold">{eventLabel(event)}</h3>
                            <p className="text-xs text-(--color-text-muted)">{action}</p>
                            <p className="text-xs font-medium">{t(status)}</p>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {runtime?.digest && hook.valid && <Button
                              type="button"
                              size="sm"
                              variant={runtime.trusted ? 'outline' : 'default'}
                              disabled={dirty}
                              onClick={() => reviewPluginWorkflow(item.installation.id, item.installation.name, hook, runtime)}
                            >{t(runtime.trusted ? 'Revoke approval' : 'Review workflow')}</Button>}
                            {item.installation.enabled && <Button
                              type="button"
                              size="sm"
                              variant={paused ? 'default' : 'outline'}
                              disabled={!parsed || update.isPending}
                              aria-label={t(paused ? 'Resume workflow' : 'Pause workflow')}
                              onClick={() => parsed && changePolicy(updatePausedHook(parsed, pluginId, hookId, !paused))}
                            >{t(paused ? 'Resume' : 'Pause')}</Button>}
                          </div>
                        </div>
                        <details className="rounded-md border border-(--color-border) px-3 py-2 text-xs">
                          <summary className="cursor-pointer font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)">{t('Workflow details')}</summary>
                          <div className="mt-2 space-y-1 text-(--color-text-muted)">
                            <p>{t('This workflow')} <code>{hookId}</code> · <code>{event}</code></p>
                            <p>{t('Reads')}: {hook.definition.input_fields.join(', ') || t('no session data')}</p>
                            <p>{t('Changes')}: {hook.definition.output_fields.join(', ') || t('nothing')}</p>
                            <p>{t('Approval')}: {runtime?.trusted ? t('approved for the current content') : t('review required')}</p>
                            {hook.diagnostics.map((diagnostic) => <p key={diagnostic.code} role="alert" className="text-(--color-error)">{diagnostic.message}</p>)}
                          </div>
                        </details>
                      </article>
                    )
                  })}
                </div>
              )}
            </SettingsGroup>

            <SettingsGroup
              title={t('Choose when plugin workflows run')}
              description={t('Your choices apply only to plugin workflows. EvoFlux permission and safety checks stay on.')}
              stagger={false}
            >
              <div className="space-y-4 p-4 sm:p-5">
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-(--color-border) p-3.5 has-checked:border-(--color-accent)/50 has-checked:bg-(--color-accent)/5">
                  <input
                    type="radio"
                    name="workflow-mode"
                    checked={parsed?.mode === 'augment'}
                    disabled={!parsed || update.isPending}
                    onChange={() => parsed && changePolicy({ ...parsed, mode: 'augment' })}
                    className="mt-0.5 accent-(--color-accent)"
                  />
                  <span className="space-y-1">
                    <span className="block text-sm font-medium">{t('Run plugin workflows alongside my workflows')}</span>
                    <span className="block text-xs text-(--color-text-muted)">{t('Recommended. Both can run when their moment arrives.')}</span>
                  </span>
                </label>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-(--color-border) p-3.5 has-checked:border-(--color-accent)/50 has-checked:bg-(--color-accent)/5">
                  <input
                    type="radio"
                    name="workflow-mode"
                    checked={parsed?.mode === 'replace'}
                    disabled={!parsed || update.isPending}
                    onChange={() => parsed && changePolicy({ ...parsed, mode: 'replace' })}
                    className="mt-0.5 accent-(--color-accent)"
                  />
                  <span className="space-y-1">
                    <span className="block text-sm font-medium">{t('Use my workflows at selected moments')}</span>
                    <span className="block text-xs text-(--color-text-muted)">{t('Plugin workflows will be skipped at the moments you choose.')}</span>
                  </span>
                </label>
                {parsed?.mode === 'replace' && (
                  <fieldset className="space-y-3 border-l-2 border-(--color-border) pl-3 sm:pl-4">
                    <legend className="px-1 text-xs font-medium">{t('Choose when to use my workflows')}</legend>
                    {(() => {
                      const renderMoments = (choices: typeof EVENT_CHOICES, showEventIds = false) => (
                        <div className="grid gap-2 sm:grid-cols-2">
                          {choices.map(({ event, label }) => {
                            const checked = parsed.replace_plugin_events.includes(event)
                            const noSettingsWorkflow = !hasRunnableSettingsWorkflow(settings, parsed.definitions, event)
                            const momentLabelId = `workflow-moment-${event.replaceAll('.', '-')}`
                            const momentWarningId = `${momentLabelId}-warning`
                            return (
                              <label
                                key={event}
                                className={`flex min-h-12 cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm transition-colors ${checked ? 'border-(--color-accent)/50 bg-(--color-accent)/5' : 'border-(--color-border) hover:bg-(--bg-hover)'}`}
                              >
                                <Checkbox
                                  checked={checked}
                                  disabled={update.isPending}
                                  aria-labelledby={momentLabelId}
                                  aria-describedby={noSettingsWorkflow && checked ? momentWarningId : undefined}
                                  onCheckedChange={(next) => {
                                    const events = next
                                      ? [...parsed.replace_plugin_events, event]
                                      : parsed.replace_plugin_events.filter((candidate) => candidate !== event)
                                    changePolicy({ ...parsed, replace_plugin_events: [...new Set(events)] })
                                  }}
                                  className="mt-0.5"
                                />
                                <span className="min-w-0 space-y-1">
                                  <span id={momentLabelId} className="block font-medium leading-snug">{t(label)}</span>
                                  {showEventIds && <code className="block text-[10px] text-(--color-text-subtle)">{event}</code>}
                                  {noSettingsWorkflow && checked && (
                                    <span id={momentWarningId} className="block text-xs leading-relaxed text-(--color-warning)">{t('No approved workflow in My workflows. Nothing will happen at this time.')}</span>
                                  )}
                                </span>
                              </label>
                            )
                          })}
                        </div>
                      )
                      const commonChoices = EVENT_CHOICES.filter(({ event }) => COMMON_EVENT_IDS.has(event))
                      const otherChoices = EVENT_CHOICES.filter(({ event }) => !COMMON_EVENT_IDS.has(event))
                      return (
                        <>
                          {renderMoments(commonChoices)}
                          <details className="rounded-lg border border-(--color-border) px-3 py-2.5">
                            <summary className="min-h-6 cursor-pointer text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)">
                              {t('Other moments')} <span className="font-normal text-(--color-text-muted)">({otherChoices.length})</span>
                            </summary>
                            <div className="mt-3 space-y-2">
                              <p className="text-xs text-(--color-text-muted)">{t('Less common events. Technical event names are shown for reference.')}</p>
                              {renderMoments(otherChoices, true)}
                            </div>
                          </details>
                        </>
                      )
                    })()}
                    {parsed.replace_plugin_events.length > 0 && (
                      <p className="text-xs text-(--color-text-muted)">
                        {t('Selected moments')}: {parsed.replace_plugin_events.length}
                      </p>
                    )}
                  </fieldset>
                )}
              </div>
            </SettingsGroup>

            <SettingsGroup
              title={t('My workflows')}
              description={t('Settings workflows are reviewed separately from plugin enablement and remain subject to the same trust checks.')}
              stagger={false}
              actions={(
                <Button type="button" size="sm" onClick={startGuidedWorkflow} disabled={!parsed || update.isPending}>
                  {workflowDraft ? t('Cancel workflow') : t('Create workflow')}
                </Button>
              )}
            >
              {workflowDraft && (
                <div className="space-y-3 border-b border-(--color-border-subtle) p-4 sm:p-5">
                  <div className="max-w-xl">
                    <label htmlFor="guided-workflow-name" className="mb-1.5 block text-xs font-medium text-(--color-text-muted)">{t('Workflow name')}</label>
                    <Input
                      id="guided-workflow-name"
                      value={workflowDraft.name}
                      disabled={workflowDraft.loading || workflowDraft.saving}
                      onChange={(event) => setWorkflowDraft({ ...workflowDraft, name: event.target.value, error: null })}
                      placeholder={t('For example, Project onboarding')}
                    />
                  </div>
                  <div>
                    <label htmlFor="guided-workflow-content" className="mb-1.5 block text-xs font-medium text-(--color-text-muted)">{t('Guidance text')}</label>
                    <Textarea
                      id="guided-workflow-content"
                      value={workflowDraft.content}
                      disabled={workflowDraft.loading || workflowDraft.saving}
                      onChange={(event) => setWorkflowDraft({ ...workflowDraft, content: event.target.value, error: null })}
                      className="min-h-36 resize-y"
                      placeholder={t('Write the guidance you want included when a new session starts.')}
                    />
                  </div>
                  <p className="text-xs leading-relaxed text-(--color-text-muted)">{t('This adds your Markdown guidance when a new session starts. It is treated as untrusted content, not EvoFlux system policy. It cannot run commands or read session data.')}</p>
                  {workflowDraft.loading && <p role="status" className="text-xs text-(--color-text-muted)">{t('Loading workflow…')}</p>}
                  {workflowDraft.error && <p role="alert" className="text-xs text-(--color-error)">{workflowDraft.error}</p>}
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button type="button" variant="outline" disabled={workflowDraft.saving} onClick={() => setWorkflowDraft(null)}>{t('Cancel')}</Button>
                    <Button
                      type="button"
                      disabled={workflowDraft.loading || workflowDraft.saving || !workflowDraft.name.trim() || !workflowDraft.content.trim()}
                      onClick={() => void saveGuidedWorkflow()}
                    >
                      {workflowDraft.saving ? t('Saving…') : t('Save workflow')}
                    </Button>
                  </div>
                </div>
              )}
              {settings.hook_statuses.length === 0 && !workflowDraft ? (
                <p className="p-4 text-sm text-(--color-text-muted)">{t('You have not created a workflow yet.')}</p>
              ) : (
                <div className="divide-y divide-(--color-border-subtle)">
                  {settings.hook_statuses.map((hook) => {
                    const definition = settings.definitions.find((item) => item.hook_id === hook.hook_id)
                    return (
                    <article key={hook.hook_id} className="space-y-3 p-4 sm:p-5">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 space-y-1">
                          {definition
                            ? <SettingsWorkflowTitle hookId={hook.hook_id} definition={definition} />
                            : <h3 className="text-sm font-medium">{workflowName(hook.hook_id)}</h3>}
                          <p className="text-xs text-(--color-text-muted)">{eventLabel(hook.event)} · {t(workflowState(hook.status, true))}</p>
                          {hook.execution_kind === 'static_context' && <p className="text-xs text-(--color-text-muted)">{t('Adds guidance as untrusted session context. No command is run.')}</p>}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {!hook.trusted && <Button type="button" size="sm" disabled={!hook.digest || trust.isPending || revoke.isPending || dirty} onClick={() => reviewHook(hook, 'trust')}>{t('Review and allow')}</Button>}
                          {hook.has_approvals && <Button type="button" size="sm" variant="outline" disabled={revoke.isPending || dirty} onClick={() => reviewHook(hook, 'revoke')}>{hook.trusted ? t('Revoke approval') : t('Clear old approvals')}</Button>}
                          {hook.execution_kind === 'static_context' && settings.definitions.some((definition) => definition.hook_id === hook.hook_id && settingsWorkflowFileId(definition)) && <Button type="button" size="sm" variant="outline" disabled={dirty || update.isPending} onClick={() => { const definition = settings.definitions.find((item) => item.hook_id === hook.hook_id); if (definition) void editGuidedWorkflow(definition) }}>{t('Edit')}</Button>}
                          {hook.execution_kind === 'static_context' && settings.definitions.some((definition) => definition.hook_id === hook.hook_id && settingsWorkflowFileId(definition)) && <Button type="button" size="sm" variant="outline" disabled={dirty || update.isPending} onClick={() => removeGuidedWorkflow(hook.hook_id)}>{t('Remove')}</Button>}
                        </div>
                      </div>
                      <details className="rounded-md border border-(--color-border) px-3 py-2 text-xs">
                        <summary className="cursor-pointer font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)">{t('Technical details')}</summary>
                        <dl className="mt-2 grid gap-2 sm:grid-cols-2">
                          <div className="sm:col-span-2"><dt className="text-(--color-text-subtle)">{hook.execution_kind === 'static_context' ? t('Static context file') : t('Command')}</dt><dd className="break-all font-mono">{hook.command.join(' ')}</dd></div>
                          <div><dt className="text-(--color-text-subtle)">{t('Data access')}</dt><dd>{t('Reads')}: {hook.input_fields.join(', ') || t('none')}</dd><dd>{t('Writes')}: {hook.output_fields.join(', ') || t('none')}</dd></div>
                          <div><dt className="text-(--color-text-subtle)">{t('Isolation profile')}</dt><dd><code>{hook.isolation_profile}</code></dd></div>
                          <div className="sm:col-span-2"><dt className="text-(--color-text-subtle)">SHA-256</dt><dd className="break-all font-mono">{hook.digest ?? t('Unavailable; source file is missing or unsafe.')}</dd></div>
                        </dl>
                      </details>
                    </article>
                    )
                  })}
                </div>
              )}
            </SettingsGroup>

            <details className="rounded-xl border border-(--color-border) bg-(--bg-card) p-4 sm:p-5">
              <summary className="cursor-pointer text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)">{t('Advanced: edit hook settings JSON')}</summary>
              <p className="mt-2 text-xs text-(--color-text-muted)">{t('For technical users. Saving a definition does not approve it; file contents are hash-bound and the execution trust checks stay in place.')}</p>
              <div className="mt-4 space-y-3">
                <label htmlFor="hook-settings-json" className="block text-xs font-medium text-(--color-text-muted)">{t('Hook settings JSON')}</label>
                <Textarea
                  id="hook-settings-json"
                  value={draft}
                  onChange={(event) => {
                    if (settings) setEdit({ source: settings, text: event.target.value })
                    setParseError(null)
                  }}
                  spellCheck={false}
                  aria-invalid={Boolean(parseError)}
                  className="min-h-[26rem] resize-y font-mono text-xs leading-relaxed"
                  placeholder={'{\n  "mode": "augment",\n  "replace_plugin_events": [],\n  "disabled_plugin_hooks": [],\n  "definitions": []\n}'}
                />
                {parseError && <p className="text-xs text-(--color-error)">{parseError}</p>}
                <p className="text-xs leading-relaxed text-(--color-text-muted)">{t('Advanced hooks declare events, runtime, files, data fields, and failure policy. Static context reads one approved file and cannot receive event input.')}</p>
              </div>
            </details>

            <p className="text-xs text-(--color-text-subtle)">
              Runtime status: <code>{settings.execution_state}</code>. Trust required: {settings.trust_required ? 'yes' : 'no'}.
            </p>
          </div>
        )}
      </SettingsAsyncBoundary>
      <ConfirmDialog request={request} onClose={close} />
    </SettingsPage>
  )
}
