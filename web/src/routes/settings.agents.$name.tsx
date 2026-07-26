import { useState } from 'react'
import { Trash2, Wrench } from 'lucide-react'

import {
  useAgentFileQuery,
  useAgentFilesQuery,
  useDeleteAgentMutation,
  useUpdateAgentMutation,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { ApiValidationError } from '@/api/client'
import { AgentForm } from '@/components/settings/AgentForm'
import { EditorHeaderActions } from '@/components/settings/EditorHeaderActions'
import {
  SettingsGroup,
  SettingsPage,
} from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { contentEquals } from '@/components/settings/frontmatter'
import { validateAgentDraft } from '@/components/settings/schema'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useSettingsParams, useSettingsNavigate } from '@/contexts/SettingsContext'

/**
 * Edit an existing agent. Loads the raw .md, renders the hybrid form,
 * saves via PUT (which auto-reloads the team server-side). On save
 * success the toast shows the reload diff.
 */
export function AgentEditorPage() {
  const { name } = useSettingsParams()
  const navigate = useSettingsNavigate()
  const push = useToastStore((s) => s.push)
  const { data, isLoading, isError, error, refetch } = useAgentFileQuery(name)
  const { data: agentsData } = useAgentFilesQuery()
  const updateMut = useUpdateAgentMutation()
  const deleteMut = useDeleteAgentMutation()

  // `draft` is the editor's working copy. Seed it once per `name` with the
  // server content; subsequent saves call `setDraft` explicitly from the
  // mutation response.
  const [draft, setDraft] = useState<string>(() => data?.content ?? '')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [mode, setMode] = useState<'form' | 'raw'>('form')
  const [deleteOpen, setDeleteOpen] = useState(false)

  // If the query finished *after* mount (common case), adopt its content
  // once. We derive this from state by tracking whether we've ever seeded.
  const [seeded, setSeeded] = useState(!!data?.content)
  if (!seeded && data?.content) {
    setSeeded(true)
    setDraft(data.content)
  }

  // Compare semantically: list-fields (tools, skills) are sets, body
  // trailing whitespace doesn't count. See ``contentEquals`` for rules.
  const dirty = !!data && !contentEquals(draft, data.content)

  // Client-side validation via zod — first error to report. Backend still
  // revalidates on save, but blocking here avoids a round-trip.
  const draftErrors = dirty ? validateAgentDraft(draft) : null
  const invalid = draftErrors !== null
  const firstDraftError = draftErrors ? Object.values(draftErrors)[0] : null
  const currentSummary = agentsData?.agents.find((agent) => agent.name === name)
  const isBuiltIn = currentSummary ? isBuiltInAgent(currentSummary.name, currentSummary.role) : false

  const handleSave = async () => {
    setSaveError(null)
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
      navigate('/settings/agents')
    } catch (err) {
      const msg = err instanceof ApiValidationError ? err.message : String(err)
      push({ tone: 'error', title: 'Delete failed', description: msg })
    }
  }

  return (
    <>
      <SettingsPage
        icon={Wrench}
        title={name}
        lede={data?.path ? <span className="font-mono text-xs">{data.path}</span> : undefined}
        actions={
          <EditorHeaderActions
            dirty={dirty}
            invalid={invalid}
            saving={updateMut.isPending}
            error={saveError}
            validationHint={firstDraftError}
            mode={mode}
            onModeChange={setMode}
            onSave={handleSave}
          />
        }
      >
        <SettingsAsyncBoundary
          loading={isLoading}
          hasData={Boolean(data)}
          error={isError ? error : undefined}
          variant="detail"
          loadingLabel={`Loading agent ${name}`}
          errorTitle={`Failed to load agent ${name}`}
          onRetry={() => void refetch()}
        >
          {data && (
          <SettingsGroup bare>
            <AgentForm
              initial={data.content}
              agentPath={name}
              onChange={setDraft}
              disabled={updateMut.isPending}
              isNew={false}
              mode={mode}
              onModeChange={setMode}
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
                  onClick={() => navigate('/settings/agents')}
                >
                  Leave without saving
                </Button>
              </>
            )}
          </div>
          {data && !isBuiltIn && (
            <Button
              variant="destructive"
              size="xs"
              className="min-h-11 md:min-h-0"
              onClick={() => setDeleteOpen(true)}
              disabled={deleteMut.isPending}
            >
              <Trash2 size={11} aria-hidden="true" />
              Delete agent
            </Button>
          )}
        </div>
      </SettingsPage>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete agent</DialogTitle>
            <DialogDescription>
              Delete `{name}.md` from the agents config directory. This cannot be undone.
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

const NORMAL_BUILT_INS = new Set(['EvoFlux', 'explorer', 'executor'])
const CODING_BUILT_INS = new Set(['EvoFlux', 'coder', 'explorer'])

function isBuiltInAgent(name: string, role: string): boolean {
  const isCoding = name.startsWith('coding/')
  const basename = name.split('/').pop() ?? name
  if (role === 'lead') return basename === 'EvoFlux'
  return isCoding ? CODING_BUILT_INS.has(basename) : NORMAL_BUILT_INS.has(basename)
}
