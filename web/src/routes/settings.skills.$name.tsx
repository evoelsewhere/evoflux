import { useMemo, useState } from 'react'
import { AlertTriangle, RotateCcw, Sparkles, Trash2 } from 'lucide-react'

import type { ManagedResourceProvider } from '@/api/types'
import {
  useDeleteSkillMutation,
  useSkillFileQuery,
  useResetSkillSettingsMutation,
  useUpdateSkillMutation,
  useUpdateSkillSettingsMutation,
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
} from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import {
  SkillBundleEditor,
} from '@/components/settings/SkillBundleEditor'
import {
  SkillModeSelector,
} from '@/components/settings/SkillModeSelector'
import { SkillRuntimeControls } from '@/components/settings/SkillRuntimeControls'
import {
  getSkillBundleChanges,
  skillBundleFilesFromApi,
  type SkillBundleDraftFile,
} from '@/components/settings/skillBundle'
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
import {
  useSettingsParams,
  useSettingsNavigate,
  useSettingsSearch,
} from '@/contexts/SettingsContext'
import { useActiveSkillDiscoveryScope } from '@/hooks/useActiveSkillDiscoveryScope'
import { useRegisterSettingsDirty } from '@/lib/settings-dirty'
import { resolveRequestedSkillMode } from '@/lib/skill-detail-mode'
import { CONDUCTOR_RESOURCE_STATE_LABEL } from '@/lib/conductor-constants'
import {
  availabilityFromModes,
  modesFromAvailability,
  type SkillAvailability,
} from '@/lib/skill-modes'

/**
 * Skill editor — lighter than the agent editor because skills have an
 * open-ended schema (only ``name`` + ``description`` are required).
 * We render a single raw .md textarea and let the user go wild.
 */
export function SkillEditorPage() {
  const { name } = useSettingsParams()
  const search = useSettingsSearch()
  const navigate = useSettingsNavigate()
  const push = useToastStore((s) => s.push)
  const activeSkillScope = useActiveSkillDiscoveryScope()
  const requestedMode = resolveRequestedSkillMode(search.mode)
  const skillScope = useMemo(
    () => ({ ...activeSkillScope, mode: requestedMode }),
    [activeSkillScope, requestedMode],
  )
  const { data, isLoading, isError, error, refetch } = useSkillFileQuery(name, skillScope)
  const updateMut = useUpdateSkillMutation(skillScope)
  const updateSettingsMut = useUpdateSkillSettingsMutation(skillScope)
  const resetSettingsMut = useResetSkillSettingsMutation(skillScope)
  const deleteMut = useDeleteSkillMutation(skillScope)
  const [draft, setDraft] = useState<string>(() => data?.content ?? '')
  const [files, setFiles] = useState<SkillBundleDraftFile[]>(() =>
    skillBundleFilesFromApi(data?.files ?? []),
  )
  const [availability, setAvailability] = useState<SkillAvailability>(() =>
    availabilityFromModes(data?.modes),
  )
  const [allowImplicitInvocation, setAllowImplicitInvocation] = useState(
    () => data?.allow_implicit_invocation ?? true,
  )
  const [userInvocable, setUserInvocable] = useState(
    () => data?.user_invocable ?? true,
  )
  const [deletedFiles, setDeletedFiles] = useState<string[]>([])
  const [saveError, setSaveError] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const discoveryKey = `${name}\u0000${requestedMode ?? 'all'}\u0000${skillScope.workspaces?.join('\u0000') ?? ''}`
  // Reseed per skill name — SettingsScreen keeps this page mounted across
  // skill-to-skill and discovery-scope changes, so a boolean "seeded once"
  // flag could leave a different repo/mode variant's draft in place.
  const [seededFor, setSeededFor] = useState<string | null>(
    data != null ? discoveryKey : null,
  )
  if (data != null && seededFor !== discoveryKey) {
    setSeededFor(discoveryKey)
    setDraft(data.content)
    setFiles(skillBundleFilesFromApi(data.files))
    setAvailability(availabilityFromModes(data.modes))
    setAllowImplicitInvocation(data.allow_implicit_invocation)
    setUserInvocable(data.user_invocable)
    setDeletedFiles([])
    setSaveError(null)
  }

  const readOnly = data ? !data.editable : false
  const settingsAmbiguous =
    requestedMode === null &&
    Boolean(data?.diagnostics.some((diagnostic) => diagnostic.code === 'mode-specific-collision'))
  const hasInvalidSettingsOverride = Boolean(
    data?.diagnostics.some((diagnostic) => diagnostic.code === 'invalid-runtime-settings'),
  )
  const repairableSettings = Boolean(data?.settings_overridden || hasInvalidSettingsOverride)
  const settingsReadOnly = data ? !data.settings_editable || settingsAmbiguous : false
  const resourcesDirty =
    !!data &&
    (JSON.stringify(files) !== JSON.stringify(skillBundleFilesFromApi(data.files)) ||
      deletedFiles.length > 0)
  const availabilityDirty =
    !!data && availability !== availabilityFromModes(data.modes)
  const runtimeSettingsDirty =
    !!data &&
    (availabilityDirty ||
      allowImplicitInvocation !== data.allow_implicit_invocation ||
      userInvocable !== data.user_invocable)
  const bundleDirty = !!data && (!contentEquals(draft, data.content) || resourcesDirty)
  const dirty = bundleDirty || runtimeSettingsDirty
  const saving = updateMut.isPending || updateSettingsMut.isPending || resetSettingsMut.isPending
  useRegisterSettingsDirty(dirty)
  const draftErrors = bundleDirty ? validateSkillDraft(draft) : null
  const invalid = draftErrors !== null
  const firstDraftError = draftErrors ? Object.values(draftErrors)[0] : null

  const handleSave = async () => {
    setSaveError(null)
    if (!data) return
    if (bundleDirty && readOnly) {
      setSaveError(`Read-only skill from ${data?.source ?? 'external source'}.`)
      return
    }
    if (runtimeSettingsDirty && settingsReadOnly) {
      setSaveError(
        settingsAmbiguous
          ? 'Choose Work or Coding before editing a mode-specific skill collision.'
          : 'Runtime settings are read-only for this skill.',
      )
      return
    }
    if (invalid) {
      setSaveError(firstDraftError ?? 'Form has validation errors.')
      return
    }
    let bundleSaved = false
    try {
      let res = data
      if (bundleDirty) {
        const bundle = getSkillBundleChanges(files, deletedFiles)
        res = await updateMut.mutateAsync({
          name,
          content: draft,
          files: bundle.files,
          deletedFiles: bundle.deletedFiles,
        })
        bundleSaved = true
        // Commit the successful bundle baseline immediately. If the settings
        // request fails next, retries must not replay resource deletions.
        setDraft(res.content)
        setFiles(skillBundleFilesFromApi(res.files))
        setDeletedFiles([])
      }
      if (runtimeSettingsDirty) {
        res = await updateSettingsMut.mutateAsync({
          name,
          settings: {
            settings_id: res.settings_id,
            modes: modesFromAvailability(availability),
            allow_implicit_invocation: allowImplicitInvocation,
            user_invocable: userInvocable,
          },
        })
      }
      push({
        tone: 'success',
        title: `Saved "${name}"`,
        description: 'Active on next turn.',
      })
      setDraft(res.content)
      setFiles(skillBundleFilesFromApi(res.files))
      setAvailability(availabilityFromModes(res.modes))
      setAllowImplicitInvocation(res.allow_implicit_invocation)
      setUserInvocable(res.user_invocable)
      setDeletedFiles([])
      if (requestedMode && !res.modes.includes(requestedMode)) {
        navigate('/settings/skills', { force: true })
      } else {
        void refetch()
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err)
      const partial = bundleSaved && runtimeSettingsDirty
      const msg = partial
        ? `The skill bundle was saved, but its runtime settings were not: ${detail}`
        : detail
      if (partial) void refetch()
      setSaveError(msg)
      push({
        tone: partial ? 'info' : 'error',
        title: partial ? 'Bundle saved; settings failed' : 'Save failed',
        description: msg,
      })
    }
  }

  const handleResetSettings = async () => {
    if (!data || settingsReadOnly || !repairableSettings) return
    setSaveError(null)
    try {
      const res = await resetSettingsMut.mutateAsync({
        name,
        settingsId: data.settings_id,
      })
      setAvailability(availabilityFromModes(res.modes))
      setAllowImplicitInvocation(res.allow_implicit_invocation)
      setUserInvocable(res.user_invocable)
      push({
        tone: 'success',
        title: hasInvalidSettingsOverride
          ? `Removed invalid override for "${name}"`
          : `Reset "${name}"`,
        description: 'Restored the portable skill defaults. Active on next turn.',
      })
      if (requestedMode && !res.modes.includes(requestedMode)) {
        navigate('/settings/skills', { force: true })
      } else {
        void refetch()
      }
    } catch (err) {
      const msg = err instanceof ApiValidationError ? err.message : String(err)
      setSaveError(msg)
      push({ tone: 'error', title: 'Reset failed', description: msg })
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
    setAvailability(availabilityFromModes(data.modes))
    setAllowImplicitInvocation(data.allow_implicit_invocation)
    setUserInvocable(data.user_invocable)
    setDeletedFiles([])
  }

  return (
    <>
      <SettingsPage
        icon={Sparkles}
        title={name}
        lede={data?.path ? (
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs">{data.path}</span>
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
            saveDisabledReason={
              bundleDirty && readOnly
                ? `Read-only skill bundle from ${data?.source ?? 'external source'}`
                : runtimeSettingsDirty && settingsReadOnly
                  ? settingsAmbiguous
                    ? 'Choose Work or Coding before editing this collided skill'
                    : 'Runtime settings are read-only for this skill'
                  : null
            }
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
              <SettingsGroup
                title="Availability"
                description="Mode scope controls where this skill is listed, selected, and loadable."
              >
                <SkillModeSelector
                  value={availability}
                  onChange={setAvailability}
                  disabled={settingsReadOnly || saving}
                  layoutId={`skill-availability-${name.replaceAll('/', '-')}`}
                />
              </SettingsGroup>
              <SettingsGroup
                title="Discovery"
                description={
                  hasInvalidSettingsOverride
                    ? 'An invalid EvoFlux runtime override was ignored. Remove it to restore a clean bundle-default state.'
                    : data.settings_overridden
                    ? 'Using an EvoFlux runtime override. The portable skill bundle remains unchanged.'
                    : 'Using the bundle defaults. Changes are saved as an EvoFlux runtime override without rewriting the portable skill.'
                }
                actions={
                  repairableSettings ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="xs"
                      className="min-h-11 md:min-h-0"
                      onClick={() => void handleResetSettings()}
                      disabled={settingsReadOnly || saving}
                    >
                      <RotateCcw size={11} aria-hidden="true" />
                      {hasInvalidSettingsOverride
                        ? 'Remove invalid override'
                        : 'Reset to skill default'}
                    </Button>
                  ) : undefined
                }
              >
                <SkillRuntimeControls
                  allowImplicitInvocation={allowImplicitInvocation}
                  userInvocable={userInvocable}
                  onAllowImplicitInvocationChange={setAllowImplicitInvocation}
                  onUserInvocableChange={setUserInvocable}
                  disabled={settingsReadOnly || saving}
                />
                <div className="p-4 sm:p-5">
                  <SettingsCallout tone="info">
                    Discovery changes apply on the next turn. Instructions already loaded into
                    the current task stay in that task's context.
                  </SettingsCallout>
                </div>
              </SettingsGroup>
              <SettingsGroup
                title="Package details"
                description="Read-only facts and diagnostics for the currently resolved skill bundle."
              >
                <div className="grid gap-2 p-4 text-xs sm:grid-cols-3 sm:p-5">
                  <SkillFact label="Resources" value={String(data.resource_count)} />
                  <SkillFact label="Dependencies" value={String(data.dependencies?.length ?? 0)} />
                  <SkillFact label="Source" value={data.source} />
                  {data.provider && (
                    <>
                      <SkillFact label="Provider" value={data.provider.project_name} />
                      <SkillFact
                        label="Version"
                        value={managedVersionLabel(data.provider)}
                      />
                      <SkillFact
                        label="Sync"
                        value={CONDUCTOR_RESOURCE_STATE_LABEL[data.provider.observed_state]}
                      />
                    </>
                  )}
                </div>
                {data.diagnostics.length > 0 && (
                  <div className="p-4 sm:p-5">
                    <div className="space-y-1 rounded-lg border border-(--color-border) bg-(--bg-key)/40 p-3">
                      {data.diagnostics.map((diagnostic) => (
                        <p key={`${diagnostic.code}:${diagnostic.message}`} className="text-xs text-(--color-text-muted)">
                          <span className="font-mono font-medium text-(--color-text)">{diagnostic.code}</span>
                          {' — '}{diagnostic.message}
                        </p>
                      ))}
                    </div>
                  </div>
                )}
              </SettingsGroup>
              <SettingsGroup
                title="Skill bundle"
                description={
                  <>
                    <span className="font-mono">SKILL.md</span> holds the core workflow. Related
                    references, scripts, assets, and UI metadata live beside it and remain part of
                    the same portable skill.
                  </>
                }
              >
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
                      This is a bounded bundle preview. Some resources are not shown and will
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
          {data && data.editable && !data.built_in && (
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
              Delete `{name}` from the skills config directory. This cannot be undone.
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

function SkillFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-(--color-border) bg-(--bg-key)/35 px-3 py-2.5">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">{label}</p>
      <p className="mt-1 font-medium text-(--color-text)">{value}</p>
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
