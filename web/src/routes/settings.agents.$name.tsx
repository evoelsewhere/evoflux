import { useState } from 'react'
import { FileCode2, ShieldCheck, Sparkles, Trash2, Users } from 'lucide-react'

import {
  useAgentFileQuery,
  useAgentFilesQuery,
  useDeleteAgentMutation,
  useUpdateAgentMutation,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { ApiValidationError } from '@/api/client'
import { AgentForm } from '@/components/settings/AgentForm'
import {
  AgentGlyph,
  AgentModelBadge,
  AgentReadyBadge,
  AgentRoleBadge,
  AgentTeamBadge,
} from '@/components/settings/AgentVisuals'
import {
  agentDisplayName,
  agentTeamFromName,
  isBuiltInAgentName,
} from '@/lib/agent-visuals'
import { EditorHeaderActions } from '@/components/settings/EditorHeaderActions'
import { SettingsPage } from '@/components/settings/SettingsLayout'
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
  const currentRole = currentSummary?.role ?? data?.config?.role
  const isBuiltIn = currentRole ? isBuiltInAgentName(name, currentRole) : false

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
        icon={Users}
        title={agentDisplayName(name)}
        lede="Shape how this agent thinks, what it can access, and the role it plays on its team."
        size="wide"
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
            <div className="space-y-5">
              <AgentDetailOverview
                name={name}
                path={data.path}
                role={currentSummary?.role ?? data.config?.role ?? 'member'}
                description={currentSummary?.description ?? data.config?.description}
                model={currentSummary?.model ?? data.config?.model}
                tools={currentSummary?.tools.length ?? data.config?.tools?.length ?? 0}
                skills={currentSummary?.skills.length ?? data.config?.skills?.length ?? 0}
                mcp={currentSummary?.mcp.length ?? 0}
                valid={currentSummary?.valid ?? !data.error}
                builtIn={isBuiltIn}
              />
              <AgentForm
                initial={data.content}
                agentPath={name}
                onChange={setDraft}
                disabled={updateMut.isPending}
                isNew={false}
                mode={mode}
                onModeChange={setMode}
              />
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

function AgentDetailOverview({
  name,
  path,
  role,
  description,
  model,
  tools,
  skills,
  mcp,
  valid,
  builtIn,
}: {
  name: string
  path: string
  role: 'lead' | 'member'
  description?: string | null
  model?: string | null
  tools: number
  skills: number
  mcp: number
  valid: boolean
  builtIn: boolean
}) {
  const team = agentTeamFromName(name)
  return (
    <section className="overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card) shadow-[0_16px_44px_rgba(0,0,0,0.035)]">
      <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:p-5">
        <AgentGlyph name={name} role={role} size="lg" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <AgentTeamBadge team={team} />
            <AgentRoleBadge role={role} />
            <AgentReadyBadge valid={valid} />
            {builtIn && (
              <span className="inline-flex items-center gap-1 text-[11px] text-(--color-text-muted)">
                <ShieldCheck size={12} aria-hidden="true" /> Built-in
              </span>
            )}
          </div>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-(--color-text-2)">
            {description || 'Add a short description so the lead knows when to delegate to this agent.'}
          </p>
        </div>
        <div className="shrink-0 sm:self-start">
          <AgentModelBadge model={model} />
        </div>
      </div>
      <div className="flex flex-col gap-3 border-t border-(--color-border-subtle) bg-(--bg-key)/25 px-4 py-3 sm:flex-row sm:items-center sm:px-5">
        <div className="flex min-w-0 flex-1 items-center gap-2 text-[11px] text-(--color-text-subtle)">
          <FileCode2 size={12} className="shrink-0" aria-hidden="true" />
          <span className="truncate font-mono" title={path}>{path}</span>
        </div>
        <div className="flex shrink-0 items-center gap-3 text-[10px] text-(--color-text-muted)">
          <span className="inline-flex items-center gap-1"><Sparkles size={10} aria-hidden="true" /> {skills} skills</span>
          <span>{tools} tools</span>
          <span>{mcp} MCP</span>
        </div>
      </div>
    </section>
  )
}
