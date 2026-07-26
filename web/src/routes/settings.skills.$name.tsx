import { useState } from 'react'
import { Sparkles, Trash2 } from 'lucide-react'

import { useDeleteSkillMutation, useSkillFileQuery, useUpdateSkillMutation } from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { ApiValidationError } from '@/api/client'
import { EditorHeaderActions } from '@/components/settings/EditorHeaderActions'
import {
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
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
import { Textarea } from '@/components/ui/textarea'
import { useSettingsParams, useSettingsNavigate } from '@/contexts/SettingsContext'

/**
 * Skill editor — lighter than the agent editor because skills have an
 * open-ended schema (only ``name`` + ``description`` are required).
 * We render a single raw .md textarea and let the user go wild.
 */
export function SkillEditorPage() {
  const { name } = useSettingsParams()
  const navigate = useSettingsNavigate()
  const push = useToastStore((s) => s.push)
  const { data, isLoading, isError, error, refetch } = useSkillFileQuery(name)
  const updateMut = useUpdateSkillMutation()
  const deleteMut = useDeleteSkillMutation()
  const [draft, setDraft] = useState<string>(() => data?.content ?? '')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [seeded, setSeeded] = useState(!!data?.content)
  if (!seeded && data?.content) {
    setSeeded(true)
    setDraft(data.content)
  }

  const readOnly = data ? !data.editable : false
  const dirty = !!data && !contentEquals(draft, data.content)
  const draftErrors = dirty ? validateSkillDraft(draft) : null
  const invalid = draftErrors !== null
  const firstDraftError = draftErrors ? Object.values(draftErrors)[0] : null

  const handleSave = async () => {
    setSaveError(null)
    if (readOnly) {
      setSaveError(`Read-only skill from ${data?.source ?? 'external source'}.`)
      return
    }
    if (invalid) {
      setSaveError(firstDraftError ?? 'Form has validation errors.')
      return
    }
    try {
      const res = await updateMut.mutateAsync({ name, content: draft })
      push({
        tone: 'success',
        title: `Saved "${name}"`,
        description: 'Active on next turn.',
      })
      setDraft(res.content)
      refetch()
    } catch (err) {
      const msg = err instanceof ApiValidationError ? err.message : String(err)
      setSaveError(msg)
      push({ tone: 'error', title: 'Save failed', description: msg })
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

  return (
    <>
      <SettingsPage
        icon={Sparkles}
        title={name}
        lede={data?.path ? <span className="font-mono text-xs">{data.path}</span> : undefined}
        actions={
          <EditorHeaderActions
            dirty={dirty}
            invalid={invalid}
            saving={updateMut.isPending}
            error={saveError}
            validationHint={firstDraftError}
            saveDisabledReason={
              readOnly ? `Read-only skill from ${data?.source ?? 'external source'}` : null
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
          <SettingsGroup
            title="Skill source"
            description={
              <>
                Frontmatter (<span className="font-mono">name</span>,{' '}
                <span className="font-mono">description</span>) is required; use{' '}
                <span className="font-mono">parent/sub</span> for a one-level sub-skill. The body is
                the instruction the agent loads on demand.
              </>
            }
          >
            <SettingsRow
              stacked
              control={
                <Textarea
                  aria-label="Skill source"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  disabled={updateMut.isPending}
                  readOnly={readOnly}
                  rows={28}
                  spellCheck={false}
                  aria-invalid={invalid || undefined}
                  className="min-h-96 font-mono text-[13px] leading-relaxed"
                />
              }
            />
          </SettingsGroup>
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
                  onClick={() => data && setDraft(data.content)}
                >
                  Discard changes
                </Button>
                <Button
                  variant="ghost"
                  size="xs"
                  className="min-h-11 md:min-h-0"
                  onClick={() => navigate('/settings/skills')}
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
