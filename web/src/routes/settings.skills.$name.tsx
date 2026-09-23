import { useState } from 'react'
import { AlertTriangle, Lock, Sparkles, Trash2 } from 'lucide-react'

import type { ManagedResourceProvider, SkillDetail } from '@/api/types'
import {
  useDeleteSkillMutation,
  useSetSkillEnabledMutation,
  useSkillFileQuery,
  useUpdateSkillMutation,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { ApiValidationError } from '@/api/client'
import { EditorHeaderActions } from '@/components/settings/EditorHeaderActions'
import { ManagedResourceProviderBadge } from '@/components/settings/ManagedResourceProviderBadge'
import { ManagedResourceUpdateBanner } from '@/components/settings/ManagedResourceUpdateBanner'
import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { SkillBundleEditor } from '@/components/settings/SkillBundleEditor'
import {
  getSkillBundleChanges,
  skillBundleFilesFromApi,
  type SkillBundleDraftFile,
} from '@/components/settings/skillBundle'
import { SKILL_SOURCE_LABEL } from '@/components/settings/skillFacts'
import { contentEquals } from '@/components/settings/frontmatter'
import { validateSkillDraft } from '@/components/settings/schema'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'
import { useSettingsParams, useSettingsNavigate } from '@/contexts/SettingsContext'
import { useActiveSkillDiscoveryScope } from '@/hooks/useActiveSkillDiscoveryScope'
import { useRegisterSettingsDirty } from '@/lib/settings-dirty'
import { CONDUCTOR_RESOURCE_STATE_LABEL } from '@/lib/conductor-constants'

/**
 * Skill editor. ``SKILL.md`` and its bundle files are edited as raw text; the
 * Enabled switch is saved immediately and is the only user preference.
 * See ``documents/architecture/agent-skills.md``.
 */
export function SkillEditorPage() {
  const { name } = useSettingsParams()
  const navigate = useSettingsNavigate()
  const push = useToastStore((s) => s.push)
  const skillScope = useActiveSkillDiscoveryScope()
  const { data, isLoading, isError, error, refetch } = useSkillFileQuery(name, skillScope)
  const updateMut = useUpdateSkillMutation(skillScope)
  const enableMut = useSetSkillEnabledMutation(skillScope)
  const deleteMut = useDeleteSkillMutation(skillScope)
  const [draft, setDraft] = useState<string>(() => data?.content ?? '')
  const [files, setFiles] = useState<SkillBundleDraftFile[]>(() =>
    skillBundleFilesFromApi(data?.files ?? []),
  )
  const [deletedFiles, setDeletedFiles] = useState<string[]>([])
  const [saveError, setSaveError] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const discoveryKey = `${name}\u0000${data?.location ?? ''}\u0000${skillScope.workspaces?.join('\u0000') ?? ''}`
  // Reseed per skill — SettingsScreen keeps this page mounted across
  // skill-to-skill and discovery-scope changes, so a boolean "seeded once"
  // flag could leave a different skill's draft in place.
  const [seededFor, setSeededFor] = useState<string | null>(
    data != null ? discoveryKey : null,
  )
  if (data != null && seededFor !== discoveryKey) {
    setSeededFor(discoveryKey)
    setDraft(data.content)
    setFiles(skillBundleFilesFromApi(data.files))
    setDeletedFiles([])
    setSaveError(null)
  }

  const readOnly = data ? !data.editable : false
  const resourcesDirty =
    !!data &&
    (JSON.stringify(files) !== JSON.stringify(skillBundleFilesFromApi(data.files)) ||
      deletedFiles.length > 0)
  const dirty = !!data && !readOnly && (!contentEquals(draft, data.content) || resourcesDirty)
  const saving = updateMut.isPending
  useRegisterSettingsDirty(dirty)
  const draftErrors = dirty ? validateSkillDraft(draft, { expectedName: name }) : null
  const invalid = draftErrors !== null
  const firstDraftError = draftErrors ? Object.values(draftErrors)[0] : null

  const handleSave = async () => {
    setSaveError(null)
    if (!data || readOnly) return
    if (invalid) {
      setSaveError(firstDraftError ?? 'Form has validation errors.')
      return
    }
    try {
      const bundle = getSkillBundleChanges(files, deletedFiles)
      const res = await updateMut.mutateAsync({
        name,
        content: draft,
        files: bundle.files,
        deletedFiles: bundle.deletedFiles,
      })
      push({
        tone: 'success',
        title: `Saved "${name}"`,
        description: 'Used from the next turn.',
      })
      setDraft(res.content)
      setFiles(skillBundleFilesFromApi(res.files))
      setDeletedFiles([])
      void refetch()
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setSaveError(msg)
      push({ tone: 'error', title: 'Save failed', description: msg })
    }
  }

  const handleEnabledChange = async (enabled: boolean) => {
    try {
      await enableMut.mutateAsync({ name, enabled })
      push({
        tone: 'success',
        title: enabled ? `Enabled "${name}"` : `Disabled "${name}"`,
        description: 'Applies from the next turn.',
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      push({ tone: 'error', title: 'Could not change skill', description: msg })
    }
  }

  const handleDelete = async () => {
    try {
      await deleteMut.mutateAsync(name)
      push({ tone: 'success', title: `Deleted "${name}"` })
      navigate('/settings/skills')
    } catch (err) {
      const msg = err instanceof ApiValidationError ? err.message : String(err)
      push({ tone: 'error', title: 'Delete failed', description: msg })
    }
  }

  const handleFilesChange = (nextFiles: SkillBundleDraftFile[]) => {
    const nextPaths = new Set(nextFiles.map((file) => file.path))
    const removed = files
      .filter((file) => !nextPaths.has(file.path) && file.originalPath)
      .map((file) => file.originalPath as string)
    if (removed.length > 0) {
      setDeletedFiles((current) => [...new Set([...current, ...removed])])
    }
    setFiles(nextFiles)
  }

  const discardChanges = () => {
    if (!data) return
    setDraft(data.content)
    setFiles(skillBundleFilesFromApi(data.files))
    setDeletedFiles([])
  }

  return (
    <>
      <SettingsPage
        icon={Sparkles}
        title={name}
        lede={data?.location ? (
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs break-all">{data.location}</span>
            {data.provider && (
              <ManagedResourceProviderBadge provider={data.provider} showState />
            )}
          </span>
        ) : undefined}
        actions={
          <EditorHeaderActions
            dirty={dirty}
            invalid={invalid}
            saving={saving}
            error={saveError}
            validationHint={firstDraftError}
            onSave={handleSave}
          />
        }
      >
        <SettingsAsyncBoundary
          loading={isLoading}
          hasData={Boolean(data)}
          error={isError ? error : undefined}
          variant="detail"
          loadingLabel={`Loading skill ${name}`}
          errorTitle={`Failed to load skill ${name}`}
          onRetry={() => void refetch()}
        >
          {data && (
            <div className="space-y-7">
              {data.provider && (
                <ManagedResourceUpdateBanner
                  provider={data.provider}
                  resourceName={name}
                  onPulled={async () => { await refetch() }}
                />
              )}
              <SettingsGroup title="Status">
                <SettingsRow
                  label={<span id="skill-enabled-label">Enabled</span>}
                  className="flex-col sm:flex-row"
                  description={
                    <span id="skill-enabled-description">
                      When off, the agent does not see this skill, typing{' '}
                      <span className="font-mono">${name}</span> does nothing, and agents that
                      list it in their Skills field do not preload it.
                    </span>
                  }
                  control={
                    <Switch
                      checked={data.enabled}
                      onCheckedChange={(checked) => void handleEnabledChange(checked)}
                      disabled={enableMut.isPending}
                      aria-labelledby="skill-enabled-label"
                      aria-describedby="skill-enabled-description"
                    />
                  }
                />
                {!data.model_invocable && (
                  <SettingsRow
                    label="Hidden from model"
                    description={
                      <>
                        <span className="font-mono">disable-model-invocation: true</span> keeps
                        this skill out of the agent&apos;s skill list. It runs only when you type{' '}
                        <span className="font-mono">${name}</span> or an agent preloads it.
                      </>
                    }
                  />
                )}
                {!data.user_invocable && (
                  <SettingsRow
                    label="Not user-invocable"
                    description={
                      <>
                        <span className="font-mono">user-invocable: false</span> removes this
                        skill from the <span className="font-mono">$</span> picker and ignores{' '}
                        <span className="font-mono">${name}</span> in messages.
                      </>
                    }
                  />
                )}
              </SettingsGroup>
              <SkillDetailsGroup skill={data} />
              <SettingsGroup
                title="Skill bundle"
                description={
                  <>
                    <span className="font-mono">SKILL.md</span> holds the instructions the agent
                    reads when it uses this skill. Reference files, scripts, and assets beside it
                    are read or run only when the instructions point to them.
                  </>
                }
              >
                {readOnly && (
                  <SettingsCallout tone="info" icon={Lock} className="mb-3">
                    {readOnlyReason(data)} You can still turn it on or off.
                  </SettingsCallout>
                )}
                {data.bundle_truncated && (
                  <div
                    role="status"
                    className="mb-3 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-xs text-(--color-text-muted)"
                  >
                    <AlertTriangle
                      className="mt-0.5 size-3.5 shrink-0 text-amber-500"
                      aria-hidden="true"
                    />
                    <p>
                      This is a bounded bundle preview. Some files are not shown and will
                      remain unchanged when you save.
                    </p>
                  </div>
                )}
                <SkillBundleEditor
                  skillContent={draft}
                  onSkillContentChange={setDraft}
                  files={files}
                  onFilesChange={handleFilesChange}
                  disabled={saving}
                  readOnly={readOnly}
                  invalid={invalid}
                />
              </SettingsGroup>
            </div>
          )}
        </SettingsAsyncBoundary>
        <div className="flex items-center justify-between gap-2 text-xs text-(--color-text-muted)">
          <div className="flex items-center gap-2">
            {dirty && (
              <>
                <Button
                  variant="ghost"
                  size="xs"
                  className="min-h-11 md:min-h-0"
                  onClick={discardChanges}
                >
                  Discard changes
                </Button>
                <Button
                  variant="ghost"
                  size="xs"
                  className="min-h-11 md:min-h-0"
                  onClick={() => navigate('/settings/skills', { force: true })}
                >
                  Leave without saving
                </Button>
              </>
            )}
          </div>
          {data && data.editable && (
            <Button
              variant="destructive"
              size="xs"
              className="min-h-11 md:min-h-0"
              onClick={() => setDeleteOpen(true)}
              disabled={deleteMut.isPending}
            >
              <Trash2 size={11} aria-hidden="true" />
              Delete skill
            </Button>
          )}
        </div>
      </SettingsPage>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete skill</DialogTitle>
            <DialogDescription>
              Delete the `{name}` folder and every file in it. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="p-3">
            <Button type="button" variant="outline" onClick={() => setDeleteOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteMut.isPending}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function SkillDetailsGroup({ skill }: { skill: SkillDetail }) {
  const metadata = Object.entries(skill.metadata ?? {})
  return (
    <SettingsGroup
      title="Details"
      description="Read from the SKILL.md frontmatter and the skill folder."
    >
      <div className="grid gap-2 p-4 text-xs sm:grid-cols-3 sm:p-5">
        <SkillFact label="Source" value={SKILL_SOURCE_LABEL[skill.source] ?? skill.source} />
        {skill.plugin_id && <SkillFact label="Plugin" value={skill.plugin_id} mono />}
        <SkillFact label="Files" value={String(skill.resource_count)} />
        {skill.license && <SkillFact label="License" value={skill.license} />}
        {skill.compatibility && (
          <SkillFact label="Compatibility" value={skill.compatibility} wide />
        )}
        {skill.allowed_tools && (
          <SkillFact
            label="Allowed tools"
            value={skill.allowed_tools}
            hint="Informational — EvoFlux permissions are unchanged."
            mono
            wide
          />
        )}
        {skill.provider && (
          <>
            <SkillFact label="Provider" value={skill.provider.project_name} />
            <SkillFact label="Version" value={managedVersionLabel(skill.provider)} />
            <SkillFact
              label="Sync"
              value={CONDUCTOR_RESOURCE_STATE_LABEL[skill.provider.observed_state]}
            />
          </>
        )}
        <SkillFact label="Location" value={skill.location} mono wide />
      </div>
      {metadata.length > 0 && (
        <div className="p-4 sm:p-5">
          <p className="mb-2 text-[10px] font-semibold tracking-wide text-(--color-text-subtle) uppercase">
            Metadata
          </p>
          <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1 text-xs">
            {metadata.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="font-mono text-(--color-text-muted)">{key}</dt>
                <dd className="break-words text-(--color-text)">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      {skill.shadowed_paths.length > 0 && (
        <div className="p-4 sm:p-5">
          <p className="mb-2 text-xs text-(--color-text-muted)">
            This skill takes precedence over {skill.shadowed_paths.length} other skill
            {skill.shadowed_paths.length === 1 ? '' : 's'} with the same name:
          </p>
          <ul className="space-y-1">
            {skill.shadowed_paths.map((path) => (
              <li key={path} className="font-mono text-[11px] break-all text-(--color-text-subtle)">
                {path}
              </li>
            ))}
          </ul>
        </div>
      )}
      {skill.diagnostics.length > 0 && (
        <div className="p-4 sm:p-5">
          <div className="space-y-1 rounded-lg border border-(--color-border) bg-(--bg-key)/40 p-3">
            {skill.diagnostics.map((diagnostic) => (
              <p
                key={`${diagnostic.code}:${diagnostic.message}`}
                className="text-xs text-(--color-text-muted)"
              >
                <span
                  className={
                    diagnostic.severity === 'error'
                      ? 'font-medium text-(--color-error)'
                      : 'font-medium text-(--color-warning)'
                  }
                >
                  {diagnostic.severity === 'error' ? 'Error' : 'Warning'}
                </span>{' '}
                <span className="font-mono font-medium text-(--color-text)">{diagnostic.code}</span>
                {' — '}{diagnostic.message}
              </p>
            ))}
          </div>
        </div>
      )}
    </SettingsGroup>
  )
}

function readOnlyReason(skill: SkillDetail): string {
  if (skill.provider) return 'This skill is managed by Conductor and is read-only here.'
  if (skill.symlinked) return 'This skill is a symlink and is read-only here.'
  if (skill.source === 'builtin') return 'Built-in skills are read-only.'
  if (skill.source === 'plugin') return 'Skills from an Agent Plugin are read-only.'
  if (skill.source === 'project') return 'Project skills are edited in their repository.'
  return 'This skill is read-only here.'
}

function SkillFact({
  label,
  value,
  hint,
  mono = false,
  wide = false,
}: {
  label: string
  value: string
  hint?: string
  mono?: boolean
  wide?: boolean
}) {
  return (
    <div
      className={
        wide
          ? 'rounded-lg border border-(--color-border) bg-(--bg-key)/35 px-3 py-2.5 sm:col-span-3'
          : 'rounded-lg border border-(--color-border) bg-(--bg-key)/35 px-3 py-2.5'
      }
    >
      <p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">{label}</p>
      <p
        className={
          mono
            ? 'mt-1 font-mono font-medium break-all text-(--color-text)'
            : 'mt-1 font-medium break-words text-(--color-text)'
        }
      >
        {value}
      </p>
      {hint && <p className="mt-1 text-[11px] text-(--color-text-muted)">{hint}</p>}
    </div>
  )
}

function managedVersionLabel(provider: ManagedResourceProvider): string {
  const applied = provider.applied_version
  const desired = provider.version
  if (applied && desired && applied !== desired) return `v${applied} → v${desired}`
  if (applied) return `v${applied}`
  if (desired) return `Pending v${desired}`
  return 'Pending'
}
